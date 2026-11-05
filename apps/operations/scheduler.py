"""DB-backed KST recall. Claims survive crashes; execution and completion commit together."""
from datetime import date,datetime,time,timedelta
from uuid import uuid4
from django.conf import settings
from django.db import connection,DatabaseError
from django.db.models import Q
from django.utils import timezone
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.assignments.services import end_locked
from apps.common.transactions import business_write,retry_transient_write
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.operations.models import SchedulerState,ScheduledJobRun,OperationEvent
from apps.sites.models import Site,DefaultSiteHistory
from apps.sites.services import locked_settings

JOB='AUTO_RECALL'


def cutoff_for(day):return datetime.combine(day,time(23),KST)


def cutoff_site(cutoff,global_settings):
    before=DefaultSiteHistory.objects.filter(changed_at__lte=cutoff).order_by('-changed_at','-settings_version','-created_at','-pk').first()
    if before:return before.new_site_id_snapshot
    after=DefaultSiteHistory.objects.filter(changed_at__gt=cutoff).order_by('changed_at','settings_version','created_at','pk').first()
    if after:return after.previous_site_id_snapshot
    if not global_settings.default_site_id:return None
    if global_settings.updated_at<=cutoff:return global_settings.default_site_id
    raise ValueError('DEFAULT_HISTORY_MISSING')


@retry_transient_write
def prepare_jobs(now=None):
    now=now or timezone.now();today=timezone.localdate(now,KST)
    last=today if now>=cutoff_for(today) else today-timedelta(days=1)
    with business_write():
        config=locked_settings()
        ScheduledJobRun.objects.filter(job_type=JOB,status='RUNNING',attempt_count__gte=settings.SCHEDULER_MAX_ATTEMPTS).filter(Q(lease_expires_at__lte=now)|Q(lease_expires_at=None)).update(status='FAILED',lease_expires_at=None,last_error_code='LEASE_TIMEOUT',next_retry_at=None)
        state=SchedulerState.objects.select_for_update().filter(pk=1).first()
        if not state:
            start=date.fromisoformat(settings.SCHEDULER_START_DATE) if settings.SCHEDULER_START_DATE else today
            if start>today:raise ValueError('SCHEDULER_START_DATE_FUTURE')
            state=SchedulerState.objects.create(pk=1,start_date=start)
        completed_or_present=set(ScheduledJobRun.objects.filter(job_type=JOB,business_date__gte=state.start_date,business_date__lte=last).values_list('business_date',flat=True))
        day=state.start_date;created=0
        while day<=last and created<settings.SCHEDULER_JOBS_PER_TICK:
            if day not in completed_or_present:
                cutoff=cutoff_for(day)
                try:target=cutoff_site(cutoff,config);code='NOT_STARTED'
                except ValueError:target=None;code='DEFAULT_HISTORY_MISSING'
                ScheduledJobRun.objects.create(job_type=JOB,business_date=day,cutoff=cutoff,target_site_id=target if Site.objects.filter(pk=target).exists() else None,
                    target_site_id_snapshot=target,status='FAILED',last_error_code=code,next_retry_at=now)
                created+=1
            day+=timedelta(days=1)
    return created


@retry_transient_write
def claim(job_id,*,now=None,force=False):
    now=now or timezone.now()
    with business_write():
        job=ScheduledJobRun.objects.select_for_update().get(pk=job_id)
        if job.status=='COMPLETED' or job.cutoff>now:return None
        if job.status=='RUNNING' and job.lease_expires_at and job.lease_expires_at>now:return None
        if not force and (job.attempt_count>=settings.SCHEDULER_MAX_ATTEMPTS or job.next_retry_at and job.next_retry_at>now):return None
        if job.last_error_code=='DEFAULT_HISTORY_MISSING':
            try:
                target=cutoff_site(job.cutoff,locked_settings());job.target_site_id_snapshot=target;job.target_site_id=target if Site.objects.filter(pk=target).exists() else None
            except ValueError:
                job.attempt_count+=1;job.next_retry_at=now+timedelta(seconds=60);job.save();return None
        job.status='RUNNING';job.attempt_count+=1;job.started_at=now;job.lease_token=uuid4();job.lease_expires_at=now+timedelta(seconds=settings.SCHEDULER_LEASE_SECONDS);job.next_retry_at=None;job.last_error_code='';job.save()
        return job.lease_token


class LeaseLost(Exception):pass


@retry_transient_write
def execute(job_id,token):
    with business_write():
        job=ScheduledJobRun.objects.select_for_update().get(pk=job_id);now=timezone.now()
        if job.status!='RUNNING' or job.lease_token!=token or not job.lease_expires_at or job.lease_expires_at<=now:return False
        with connection.cursor() as cursor:cursor.execute("SELECT set_config('statement_timeout', %s, true)",[str(settings.SCHEDULER_STATEMENT_TIMEOUT_MS)])
        start=datetime.combine(job.business_date,time.min,KST)
        def eligible():return Customer.objects.filter(site_id=job.target_site_id_snapshot,deleted_at=None,current_assignment__ended_at=None,current_assignment__isnull=False,
            current_assignment__assigned_at__gte=start,current_assignment__assigned_at__lte=job.cutoff,current_assignment__first_activity_at=None)
        # This small installation already serializes domain writes. Lock the small
        # user ID set in order, avoiding a costly DISTINCT customer/assignment join.
        list(User.objects.select_for_update().only('pk').order_by('pk'))
        locked_settings()
        site=Site.objects.select_for_update().filter(pk=job.target_site_id_snapshot).first()
        customers=list(eligible().select_for_update(of=('self',)).order_by('pk')) if site else []
        assignments=list(Assignment.objects.select_for_update().filter(pk__in=[c.current_assignment_id for c in customers]).order_by('pk'))
        end_locked(customers,assignments,None,Assignment.EndReason.AUTO_RECALL,now)
        OperationEvent.objects.create(actor=None,operation=JOB,occurred_at=now,affected_count=len(customers))
        if timezone.now()>=job.lease_expires_at:raise LeaseLost()
        job.status='COMPLETED';job.completed_at=timezone.now();job.affected_count=len(customers);job.lease_expires_at=None;job.last_error_code='';job.save()
        return True


@retry_transient_write
def failed(job_id,token,code):
    with business_write():
        job=ScheduledJobRun.objects.select_for_update().get(pk=job_id)
        if job.status!='RUNNING' or job.lease_token!=token:return
        job.status='FAILED';job.lease_expires_at=None;job.last_error_code=code;job.next_retry_at=timezone.now()+timedelta(seconds=min(3600,60*2**min(job.attempt_count-1,6)));job.save()


def run_jobs(*,now=None,retry_date=None):
    now=now or timezone.now();prepare_jobs(now)
    if retry_date is not None:
        candidates=ScheduledJobRun.objects.filter(job_type=JOB,business_date=retry_date,cutoff__lte=now)
        if not candidates.exists():raise ValueError('SCHEDULED_JOB_NOT_FOUND')
    else:
        candidates=ScheduledJobRun.objects.filter(job_type=JOB,cutoff__lte=now,attempt_count__lt=settings.SCHEDULER_MAX_ATTEMPTS).filter(
            Q(status='RUNNING')&(Q(lease_expires_at__lte=now)|Q(lease_expires_at=None))|Q(status='FAILED')&(Q(next_retry_at__lte=now)|Q(next_retry_at=None)))
    done=0
    for job_id in candidates.order_by('business_date').values_list('pk',flat=True)[:settings.SCHEDULER_JOBS_PER_TICK]:
        token=claim(job_id,now=now,force=retry_date is not None)
        if not token:continue
        try:
            if execute(job_id,token):done+=1
            else:failed(job_id,token,'LEASE_TIMEOUT')
        except Exception as exc:
            code='LEASE_TIMEOUT' if isinstance(exc,LeaseLost) else 'DATABASE_ERROR' if isinstance(exc,DatabaseError) else 'EXECUTION_FAILED'
            failed(job_id,token,code)
    outstanding=ScheduledJobRun.objects.filter(job_type=JOB,cutoff__lte=now,status='FAILED').exclude(last_error_code='NOT_STARTED').count()
    return {'completed':done,'failed':outstanding}
