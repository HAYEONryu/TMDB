from scripts.verification_evidence import artifact_path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,date,time
from threading import Event,Barrier
from unittest.mock import patch
from uuid import uuid4
import io
import json,os,subprocess
from pathlib import Path
from urllib.parse import quote
from datetime import timezone as utc_timezone
from django.conf import settings
from django.db import connection
from django.core.management import call_command,CommandError
from django.db import close_old_connections
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.assignments.services import change_assignee
from apps.callbacks.models import Callback
from apps.callbacks.services import complete
from apps.common.receipts import cleanup_mutation_receipts,cleanup_p4_receipts
from apps.common.transactions import business_write
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer,CustomerChangeEvent
from apps.customers.queries import KST
from apps.customers.services import update_row,trash_operation
from apps.operations.models import SchedulerState,ScheduledJobRun,OperationEvent,MutationReceipt,IdempotencyRecord
from apps.operations.scheduler import prepare_jobs,claim,execute,run_jobs,cutoff_for,JOB
from apps.sites.models import GlobalSettings,DefaultSiteHistory,Site
from apps.sites.services import set_default_site
from tests.helpers import TEST_HASHERS,login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS,SCHEDULER_START_DATE='')
class P6Tests(Fixtures,TransactionTestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0];self.assignment=self.assign(self.customer)
        self.now=datetime.combine(timezone.localdate(),time(23,5),KST)
        clock=patch('django.utils.timezone.now',return_value=self.now);clock.start();self.addCleanup(clock.stop)
        self.client=login(self.employee)
        # Fix all fixture timestamps independent of the host's current clock.
        DefaultSiteHistory.objects.update(changed_at=self.now.replace(hour=12))
        Assignment.objects.update(assigned_at=self.now.replace(hour=10))
        self.assignment.refresh_from_db()
    def callback(self,customer=None,**values):return Callback.objects.create(customer=customer or self.customer,due_at=self.now-timedelta(hours=1),created_by=self.employee,updated_by=self.employee,**values)
    def completion(self,callback=None,customer=None,**values):
        c=customer or self.customer;b=callback or self.callback()
        return {'callback_id':str(b.pk),'callback_version':b.version,'assignment_id':str(c.current_assignment_id),'expected_version':c.version,'idempotency_key':str(uuid4()),**values}
    def call(self,body=None):return complete(self.employee,self.customer.pk,body or self.completion())
    def tick(self,now=None,**kwargs):
        at=now or self.now
        with patch('apps.operations.scheduler.timezone.now',return_value=at):return run_jobs(now=at,**kwargs)
    def history(self,person=None,**params):
        return login(person or self.employee).get(f'/api/customers/{self.customer.pk}/history',{**({'assignment_id':str(self.customer.current_assignment_id)} if self.customer.current_assignment_id else {}),**params})

    def test_complete_atomic_progress_revision_and_replay_preserves_new_schedule(self):
        callback=self.callback();body=self.completion(callback);result,status=self.call(body);self.assertEqual(status,200);self.assertTrue(result['changed'])
        callback.refresh_from_db();self.customer.refresh_from_db();self.assignment.refresh_from_db()
        self.assertEqual(callback.status,'COMPLETED');self.assertIsNotNone(self.assignment.first_activity_at);self.assertEqual(ConsultationRevision.objects.count(),1)
        self.assertEqual(CustomerChangeEvent.objects.count(),1);self.assertIsNone(result['row']['callback_id'])
        revision=ConsultationRevision.objects.get();self.assertEqual(revision.before_values['callback_due_at'],callback.due_at.isoformat());self.assertIsNone(revision.after_values['callback_due_at'])
        mutation=self.mutation(self.customer);mutation['changes']={'callback_due_at':(self.now+timedelta(days=1)).isoformat()};update_row(self.employee,mutation)
        again,_=self.call(body);new=Callback.objects.get(status='PENDING');self.assertEqual(again['callback_id'],str(callback.pk));self.assertEqual(again['row']['callback_id'],str(new.pk));self.assertEqual(ConsultationRevision.objects.count(),2)
        other_key={**body,'idempotency_key':str(uuid4())};self.assertFalse(self.call(other_key)[0]['changed']);self.assertEqual(Callback.objects.filter(status='PENDING').count(),1)

    def test_complete_version_conflict_cancelled_and_bad_body_write_nothing(self):
        callback=self.callback();body=self.completion(callback)
        for changes,code in [({'callback_version':2},'VERSION_CONFLICT'),({'expected_version':True},'VALIDATION_ERROR')]:
            with self.assertRaises(AccessError) as error:self.call({**body,**changes})
            self.assertEqual(error.exception.code,code)
        mutation=self.mutation(self.customer);mutation['changes']={'callback_due_at':None};update_row(self.employee,mutation)
        with self.assertRaises(AccessError) as error:self.call(body)
        self.assertEqual(error.exception.code,'CALLBACK_CHANGED');self.assertEqual(Callback.objects.get().status,'CANCELLED');self.assertEqual(ConsultationRevision.objects.count(),1)

    def test_permissions_old_assignment_replay_and_cross_account_header(self):
        body=self.completion()
        with self.assertRaises(AccessError) as error:complete(self.other,self.customer.pk,body)
        self.assertEqual(error.exception.code,'FORBIDDEN')
        self.call(body);self.customer.refresh_from_db();change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.other))
        with self.assertRaises(AccessError) as error:self.call(body)
        self.assertEqual(error.exception.code,'ASSIGNMENT_CHANGED')
        response=login(self.admin).post(f'/api/customers/{self.customer.pk}/callback-complete',body,content_type='application/json',HTTP_X_TM_ACTOR=str(self.employee.pk))
        self.assertEqual(response.status_code,403)

    def test_complete_rolls_back_on_revision_failure(self):
        body=self.completion()
        with patch('apps.callbacks.services.ConsultationRevision.objects.create',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.call(body)
        self.assertEqual(Callback.objects.get().status,'PENDING');self.assignment.refresh_from_db();self.assertIsNone(self.assignment.first_activity_at);self.assertEqual(IdempotencyRecord.objects.count(),0)

    def test_history_paging_previous_owner_contents_and_authority(self):
        self.call();self.customer.refresh_from_db()
        for i in range(51):self.callback(status='CANCELLED',cancelled_at=self.now)
        first=self.history().json();second=self.history(page=2).json();self.assertEqual((first['total'],len(first['data']),len(second['data'])),(52,50,2))
        consultation=self.history(kind='consultations').json()['data'][0];self.assertEqual(consultation['actor'],self.employee.name)
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.other));self.customer.refresh_from_db()
        self.assertEqual(self.history().status_code,403);self.assertEqual(self.history(self.other,kind='consultations').json()['data'][0]['actor'],self.employee.name)
        former_id=str(self.customer.current_assignment_id);trash_operation(self.admin,{'customer_ids':[str(self.customer.pk)],'site_id':str(self.site.pk),'idempotency_key':str(uuid4())});self.customer.refresh_from_db()
        self.assertEqual(self.history(self.other,assignment_id=former_id).status_code,409);self.assertEqual(self.history(self.admin).json()['total'],52)

    def test_dashboard_unique_assignments_current_results_and_explicit_denominators(self):
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer));self.customer.refresh_from_db()
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.employee));self.customer.refresh_from_db()
        transferred=self.customers(offset=10)[0];self.assign(transferred);change_assignee(self.admin,transferred.pk,self.assignee_body(transferred,self.other))
        old=self.customers(offset=11)[0];self.assign(old,at=self.now-timedelta(days=1));Customer.objects.filter(pk=old.pk).update(call_result='REJECTED')
        mutation=self.mutation(self.customer);mutation['changes']={'call_result':'INTERESTED'};update_row(self.employee,mutation)
        admin=login(self.admin).get('/api/dashboard',{'site_id':self.site.pk}).json();e=next(row for row in admin['employees'] if row['id']==str(self.employee.pk))
        self.assertEqual((e['assigned_today_unique'],e['assignment_operations_today'],e['held_total'],e['assigned_today_held'],e['assigned_today_removed']),(2,3,2,1,1))
        self.assertEqual((e['unprogressed_today_held'],e['unprogressed_total']),(0,1));results={r['value']:r['count'] for r in e['call_results']};self.assertEqual(results['INTERESTED'],1);self.assertEqual(results['REJECTED'],0)
        own=self.client.get('/api/dashboard',{'site_id':self.site.pk}).json();self.assertNotIn('employees',own);self.assertEqual(own['employee']['id'],str(self.employee.pk))
        self.assertEqual(self.client.get('/api/dashboard',{'employee_id':self.other.pk}).status_code,422)

    def test_dashboard_callback_today_future_overdue_and_site_selection_no_setting_write(self):
        before=GlobalSettings.objects.get(pk=1).version;now=timezone.now();end=now.astimezone(KST).replace(hour=23,minute=59,second=59)
        self.callback();second=self.customers(offset=10)[0];self.assign(second);Callback.objects.create(customer=second,due_at=end,created_by=self.employee,updated_by=self.employee)
        with patch('apps.operations.dashboard.timezone.now',return_value=self.now):
            data=self.client.get('/api/dashboard',{'site_id':self.site.pk}).json()['employee']
        self.assertEqual(data['callbacks_due_today_or_past'],2);self.assertEqual(data['callbacks_overdue'],1)
        self.client.get('/api/dashboard',{'site_id':self.second.pk});self.assertEqual(GlobalSettings.objects.get(pk=1).version,before)

    def test_recall_boundaries_existing_values_and_completed_job_replay(self):
        c=self.customer;Customer.objects.filter(pk=c.pk).update(notes='가상 상담 보존',visit_at=self.now);callback=self.callback()
        rows=self.customers(5,offset=10)
        for row,at,progress in [(rows[0],self.now.replace(hour=0,minute=0),False),(rows[1],cutoff_for(self.now.date()),False),(rows[2],cutoff_for(self.now.date())+timedelta(seconds=1),False),(rows[3],self.now-timedelta(days=1),False),(rows[4],self.now.replace(hour=10),True)]:self.assign(row,at=at,progress=progress)
        other_site=self.customers(site=self.second,offset=30)[0];self.assign(other_site)
        self.assertEqual(self.tick(),{'completed':1,'failed':0});job=ScheduledJobRun.objects.get();self.assertEqual(job.affected_count,3)
        c.refresh_from_db();callback.refresh_from_db();self.assertEqual(c.notes,'가상 상담 보존');self.assertIsNone(c.current_assignment_id);self.assertEqual(callback.status,'PENDING');self.assertEqual(Assignment.objects.filter(end_reason='AUTO_RECALL').count(),3)
        self.assertEqual(self.tick(),{'completed':0,'failed':0});self.assertEqual(OperationEvent.objects.filter(operation=JOB).count(),1)
        for row in rows[2:]:row.refresh_from_db();self.assertIsNotNone(row.current_assignment_id)

    def test_failure_rollback_fixed_cutoff_site_and_retry_after_default_changes(self):
        from apps.assignments.services import end_locked
        def fail(*args):end_locked(*args);raise RuntimeError('가상 민감 원문은 로그 금지')
        with patch('apps.operations.scheduler.end_locked',side_effect=fail):self.assertEqual(self.tick()['failed'],1)
        self.customer.refresh_from_db();self.assertEqual(self.customer.current_assignment_id,self.assignment.pk);self.assignment.refresh_from_db();self.assertIsNone(self.assignment.ended_at)
        job=ScheduledJobRun.objects.get();self.assertEqual(job.status,'FAILED');self.assertEqual(job.last_error_code,'EXECUTION_FAILED');self.assertEqual(job.target_site_id_snapshot,self.site.pk)
        later=self.now+timedelta(minutes=2)
        with patch('apps.sites.services.timezone.now',return_value=later):set_default_site(self.admin,self.second.pk,GlobalSettings.objects.get(pk=1).version)
        self.assertEqual(self.tick(later)['completed'],1);job.refresh_from_db();self.assertEqual((job.attempt_count,job.affected_count),(2,1));self.assertEqual(job.target_site_id_snapshot,self.site.pk)

    def test_delayed_job_does_not_undo_saved_activity_or_new_assignment(self):
        prepare_jobs(self.now);second=self.customers(offset=10)[0];self.assign(second,at=self.now.replace(hour=10))
        mutation=self.mutation(self.customer,'지연 회수 전 가상 저장');update_row(self.employee,mutation)
        with patch('apps.assignments.services.timezone.now',return_value=self.now+timedelta(minutes=1)):
            change_assignee(self.admin,second.pk,self.assignee_body(second));second.refresh_from_db();change_assignee(self.admin,second.pk,self.assignee_body(second,self.employee))
        self.assertEqual(self.tick()['completed'],1);self.assertEqual(ScheduledJobRun.objects.get().affected_count,0)
        self.customer.refresh_from_db();second.refresh_from_db();self.assertIsNotNone(self.customer.current_assignment_id);self.assertIsNotNone(second.current_assignment_id)

    def test_default_changes_at_exact_cutoff_use_settings_version_order(self):
        cutoff=cutoff_for(self.now.date())
        with patch('apps.sites.services.timezone.now',return_value=cutoff):
            set_default_site(self.admin,self.second.pk,GlobalSettings.objects.get(pk=1).version)
            set_default_site(self.admin,self.site.pk,GlobalSettings.objects.get(pk=1).version)
        prepare_jobs(self.now);self.assertEqual(ScheduledJobRun.objects.get().target_site_id_snapshot,self.site.pk)

    def test_lease_expiry_fences_old_worker_and_recovers_once(self):
        prepare_jobs(self.now);job=ScheduledJobRun.objects.get();first=claim(job.pk,now=self.now);self.assertIsNone(claim(job.pk,now=self.now+timedelta(seconds=10)))
        later=self.now+timedelta(seconds=121);second=claim(job.pk,now=later);self.assertNotEqual(first,second)
        with patch('apps.operations.scheduler.timezone.now',return_value=later):self.assertFalse(execute(job.pk,first));self.assertTrue(execute(job.pk,second))
        self.assertEqual(Assignment.objects.filter(end_reason='AUTO_RECALL').count(),1);self.assertEqual(OperationEvent.objects.filter(operation=JOB).count(),1)

    def test_attempt_limit_reaps_running_and_explicit_retry_keeps_attempt_history(self):
        prepare_jobs(self.now);job=ScheduledJobRun.objects.get();ScheduledJobRun.objects.filter(pk=job.pk).update(status='RUNNING',attempt_count=5,lease_expires_at=self.now-timedelta(seconds=1),lease_token=uuid4())
        self.tick();job.refresh_from_db();self.assertEqual((job.status,job.attempt_count,job.last_error_code),('FAILED',5,'LEASE_TIMEOUT'))
        self.assertEqual(self.tick(retry_date=self.now.date())['completed'],1);job.refresh_from_db();self.assertEqual(job.attempt_count,6)

    def test_persisted_start_date_bounded_catchup_and_no_future_job(self):
        start=self.now.date()-timedelta(days=3)
        with override_settings(SCHEDULER_START_DATE=start.isoformat(),SCHEDULER_JOBS_PER_TICK=2):
            self.tick();self.assertEqual(ScheduledJobRun.objects.count(),2);self.assertEqual(SchedulerState.objects.get().start_date,start)
            self.tick();self.assertEqual(ScheduledJobRun.objects.count(),4)
        with override_settings(SCHEDULER_START_DATE=''):
            self.tick(self.now+timedelta(days=1,hours=-1));self.assertEqual(SchedulerState.objects.get().start_date,start);self.assertFalse(ScheduledJobRun.objects.filter(business_date=self.now.date()+timedelta(days=1)).exists())

    def test_missing_or_deleted_cutoff_site_completes_zero(self):
        prepare_jobs(self.now);job=ScheduledJobRun.objects.get()
        # Simulate the target FK being gone, while retaining its historical UUID.
        trash_operation(self.admin,{'customer_ids':[str(self.customer.pk)],'site_id':str(self.site.pk),'idempotency_key':str(uuid4())})
        Site.objects.filter(pk=self.site.pk).delete()
        self.assertEqual(self.tick()['completed'],1);job.refresh_from_db();self.assertEqual(job.affected_count,0);self.assertEqual(job.target_site_id_snapshot,self.site.pk)

    def test_completion_receipt_and_mutation_cleanup_preserves_business_history(self):
        self.call();self.customer.refresh_from_db();update_row(self.employee,self.mutation(self.customer,'가상 이력 유지'))
        IdempotencyRecord.objects.filter(operation='CALLBACK_COMPLETE').update(expires_at=timezone.now()-timedelta(seconds=1));MutationReceipt.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(cleanup_p4_receipts(),1);self.assertEqual(cleanup_mutation_receipts(),1);self.assertEqual(ConsultationRevision.objects.count(),2);self.assertEqual(Callback.objects.get().status,'COMPLETED')

    def test_management_once_start_date_and_failure_reporting(self):
        output=io.StringIO()
        with patch('apps.operations.scheduler.timezone.now',return_value=self.now):call_command('run_scheduler',once=True,stdout=output)
        self.assertIn('자동 회수 완료 1',output.getvalue())
        with self.assertRaises(CommandError):call_command('run_scheduler',retry_date=self.now.date())

    def test_first_start_date_is_persisted_and_invalid_config_creates_no_jobs(self):
        with override_settings(SCHEDULER_START_DATE=''):
            prepare_jobs(self.now-timedelta(hours=1));self.assertEqual(SchedulerState.objects.get().start_date,self.now.date());self.assertEqual(ScheduledJobRun.objects.count(),0)
        SchedulerState.objects.all().delete()
        with override_settings(SCHEDULER_START_DATE=(self.now.date()+timedelta(days=1)).isoformat()):
            with self.assertRaises(ValueError):prepare_jobs(self.now)
        self.assertFalse(SchedulerState.objects.exists())

    def test_missing_default_history_is_failed_not_wrong_site_or_zero_success(self):
        DefaultSiteHistory.objects.all().delete();GlobalSettings.objects.filter(pk=1).update(updated_at=self.now)
        self.assertEqual(self.tick()['failed'],1);job=ScheduledJobRun.objects.get();self.assertEqual((job.status,job.last_error_code,job.attempt_count),('FAILED','DEFAULT_HISTORY_MISSING',1));self.assertEqual(OperationEvent.objects.filter(operation=JOB).count(),0)

    def test_command_failure_does_not_print_customer_or_exception_payload(self):
        output=io.StringIO()
        with patch('apps.operations.scheduler.timezone.now',return_value=self.now),patch('apps.operations.scheduler.end_locked',side_effect=RuntimeError('가상 비공개 상담 원문')):
            with self.assertRaises(CommandError):call_command('run_scheduler',once=True,stdout=output)
        self.assertNotIn('비공개 상담',output.getvalue());self.assertEqual(ScheduledJobRun.objects.get().status,'FAILED')

    def test_concurrent_duplicate_completion_one_revision(self):
        body=self.completion();barrier=Barrier(2)
        def worker():
            close_old_connections()
            try:barrier.wait(timeout=5);return self.call(body)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker) for _ in range(2)];results=[future.result(timeout=15) for future in futures]
        self.assertEqual(results[0],results[1]);self.assertEqual(ConsultationRevision.objects.count(),1)

    def ordered(self,first,second):
        held,release=Event(),Event()
        def a():
            close_old_connections()
            try:
                with business_write():
                    value=first();held.set();assert release.wait(10);return value
            finally:close_old_connections()
        def b():
            close_old_connections()
            try:return second()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(a);self.assertTrue(held.wait(10));two=pool.submit(b);release.set();return one.result(timeout=15),two.result(timeout=15)

    def test_saved_commit_wins_against_automatic_recall(self):
        with patch('apps.operations.scheduler.timezone.now',return_value=self.now):self.ordered(lambda:update_row(self.employee,self.mutation(self.customer,'먼저 커밋 가상 상담')),lambda:run_jobs(now=self.now))
        self.assertEqual(ScheduledJobRun.objects.get().affected_count,0);self.customer.refresh_from_db();self.assertIsNotNone(self.customer.current_assignment_id)

    def test_automatic_recall_commit_wins_against_late_save(self):
        def save_late():
            try:update_row(self.employee,self.mutation(self.customer));return 'UNEXPECTED'
            except AccessError as error:return error.code
        with patch('apps.operations.scheduler.timezone.now',return_value=self.now):_,code=self.ordered(lambda:run_jobs(now=self.now),save_late)
        self.assertEqual(code,'ASSIGNMENT_CHANGED');self.assertEqual(ConsultationRevision.objects.count(),0)

    def test_real_process_exits_after_claim_then_restart_recovers_without_duplicate(self):
        yesterday=self.now.date()-timedelta(days=1);SchedulerState.objects.create(pk=1,start_date=yesterday)
        Assignment.objects.filter(pk=self.assignment.pk).update(assigned_at=datetime.combine(yesterday,time(10),KST))
        job=ScheduledJobRun.objects.create(job_type=JOB,business_date=yesterday,cutoff=cutoff_for(yesterday),target_site=self.site,target_site_id_snapshot=self.site.pk,status='FAILED')
        config=connection.settings_dict;environment=os.environ.copy()
        environment['DATABASE_URL']=f"postgresql://{quote(config['USER'],safe='')}:{quote(config['PASSWORD'],safe='')}@{config['HOST']}:{config['PORT']}/{quote(config['NAME'],safe='')}"
        command=[str(settings.BASE_DIR/'.venv/bin/python'),'manage.py']
        claim_code=f"from apps.operations.scheduler import claim;from uuid import UUID;import os;assert claim(UUID('{job.pk}'));os._exit(23)"
        crashed=subprocess.run([*command,'shell','-c',claim_code],cwd=settings.BASE_DIR,env=environment,capture_output=True,text=True,timeout=30)
        self.assertEqual(crashed.returncode,23,crashed.stderr);job.refresh_from_db();self.assertEqual((job.status,job.attempt_count),('RUNNING',1));self.assertFalse(OperationEvent.objects.filter(operation=JOB).exists())
        # Advance only the lease timestamp; do not wait two real minutes in the suite.
        ScheduledJobRun.objects.filter(pk=job.pk).update(lease_expires_at=datetime.now(utc_timezone.utc)-timedelta(seconds=1))
        for _ in range(2):
            restarted=subprocess.run([*command,'run_scheduler','--once'],cwd=settings.BASE_DIR,env=environment,capture_output=True,text=True,timeout=30)
            self.assertEqual(restarted.returncode,0,restarted.stderr)
        job.refresh_from_db();self.assertEqual((job.status,job.attempt_count,job.affected_count),('COMPLETED',2,1));self.assertEqual(OperationEvent.objects.filter(operation=JOB).count(),1)
        evidence={'claim_process_exit_code':23,'state_after_exit':'RUNNING','final_state':job.status,'attempt_count':job.attempt_count,'affected_count':job.affected_count,'completion_events':1,'restart_processes':2,'test_database_only':True}
        Path(artifact_path('p6-process-restart.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
