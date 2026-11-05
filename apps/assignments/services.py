from datetime import datetime,time,timedelta
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.assignments.models import Assignment
from apps.common.http import identifier
from apps.common.receipts import fingerprint,replay,remember,failure
from apps.common.transactions import business_write,retry_transient_write
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.operations.models import OperationEvent
from apps.sites.models import Site
from apps.sites.services import locked_actor


def invalid(message):raise AccessError("VALIDATION_ERROR",message,422)


def selected_employee(value):return "all" if value=="all" else identifier(value)


def employee_rows():
    return User.objects.filter(is_active=True,role=User.Role.EMPLOYEE).order_by("created_at","pk")


def recipients(value,*,lock=False):
    query=employee_rows()
    if lock:query=query.select_for_update().order_by("pk")
    rows=list(query if value=="all" else query.filter(pk=value))
    if not rows:
        if value=="all":raise AccessError("NO_ACTIVE_EMPLOYEES","분배할 활성 직원이 없습니다.",409)
        raise AccessError("INVALID_EMPLOYEE","활성 직원만 선택할 수 있습니다. 직원 목록을 다시 확인해 주세요.",409)
    return rows


def site_for(site_id,*,lock=False):
    query=Site.objects.select_for_update() if lock else Site.objects
    site=query.filter(pk=site_id).first()
    if not site:raise AccessError("SITE_DELETED","현장이 삭제되었거나 존재하지 않습니다.",409)
    return site


def eligible(site_id):return Customer.objects.filter(site_id=site_id,deleted_at__isnull=True,current_assignment__isnull=True)


def availability(params):
    if set(params)!={"site_id"}:invalid("현장을 선택해 주세요.")
    site=site_for(identifier(params["site_id"]))
    return {"site_id":str(site.pk),"available_count":eligible(site.pk).count(),
        "employees":[{"id":str(person.pk),"name":person.name,"phone":person.phone_normalized} for person in employee_rows()]}


def today_query(site_id,people,now):
    start=datetime.combine(timezone.localdate(now,KST),time.min,KST)
    return Customer.objects.filter(site_id=site_id,deleted_at__isnull=True,current_assignment__employee_id__in=[p.pk for p in people],
        current_assignment__ended_at__isnull=True,current_assignment__assigned_at__gte=start,current_assignment__assigned_at__lt=start+timedelta(days=1))


def recall_preview(body):
    if set(body)!={"site_id","employee_id"}:invalid("현장과 직원을 확인해 주세요.")
    site_id,value=identifier(body["site_id"]),selected_employee(body["employee_id"])
    site_for(site_id)
    people=recipients(value)
    now=timezone.now()
    return {"site_id":str(site_id),"business_date":timezone.localdate(now,KST).isoformat(),"employee_count":len(people),"target_count":today_query(site_id,people,now).count()}


def end_locked(customers,assignments,actor,reason,now):
    """Caller owns global lock, sorted sites/customers and assignment row locks."""
    for customer in customers:
        customer.current_assignment=None;customer.version+=1;customer.updated_at=now
    for assignment in assignments:
        assignment.ended_at=now;assignment.end_reason=reason;assignment.ended_by=actor;assignment.updated_at=now
    # Values are identical for every row; avoid constructing tens of thousands
    # of CASE expressions while the business lock is held.
    for offset in range(0,len(customers),500):
        Customer.objects.filter(pk__in=[c.pk for c in customers[offset:offset+500]]).update(current_assignment=None,version=F("version")+1,updated_at=now)
    for offset in range(0,len(assignments),500):
        Assignment.objects.filter(pk__in=[a.pk for a in assignments[offset:offset+500]]).update(ended_at=now,end_reason=reason,ended_by=actor,updated_at=now)


def checked_body(body,*,distribute):
    fields={"site_id","employee_id","idempotency_key"}|({"quantity"} if distribute else set())
    if set(body)!=fields:invalid("분배·회수 요청 형식을 확인해 주세요.")
    site_id,value,key=identifier(body["site_id"]),selected_employee(body["employee_id"]),identifier(body["idempotency_key"])
    if distribute and (type(body["quantity"]) is not int or body["quantity"]<=0):invalid("직원당 수량은 양의 정수로 입력해 주세요.")
    normalized={"site_id":str(site_id),"employee_id":str(value),**({"quantity":body["quantity"]} if distribute else {})}
    return site_id,value,key,fingerprint(normalized)


@retry_transient_write
def distribute(actor,body):
    site_id,value,key,body_hash=checked_body(body,distribute=True)
    with business_write():
        # Resolve all-team membership while holding the global write boundary.
        users=list(employee_rows().values_list("pk",flat=True)) if value=="all" else [value]
        actor=locked_actor(actor,admin=True,extra_ids=users)
        site_for(site_id,lock=True)
        cached=replay(actor,"DISTRIBUTE",key,body_hash)
        if cached:return cached
        try:
            with transaction.atomic():
                people=recipients(value)
                available=eligible(site_id).count();quantity=body["quantity"];needed=quantity*len(people)
                if available<needed:
                    raise AccessError("INSUFFICIENT_CUSTOMERS",f"{available//len(people)}개씩 분배할 수 있습니다.",409,
                        {"available_count":available,"employee_count":len(people),"max_per_employee":available//len(people),"allocated_count":0})
                ids=list(eligible(site_id).order_by("?").values_list("pk",flat=True)[:needed])
                customers={c.pk:c for c in Customer.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
                now=timezone.now();new=[]
                for index,cid in enumerate(ids):
                    assignment=Assignment(customer=customers[cid],employee=people[index//quantity],assigned_by=actor,assigned_at=now)
                    new.append(assignment)
                    customer=customers[cid];customer.current_assignment=assignment;customer.version+=1;customer.updated_at=now
                Assignment.objects.bulk_create(new,batch_size=500)
                Customer.objects.bulk_update(list(customers.values()),["current_assignment","version","updated_at"],batch_size=500)
                OperationEvent.objects.create(actor=actor,operation="DISTRIBUTE",occurred_at=now,affected_count=len(ids))
                result={"ok":True,"site_id":str(site_id),"allocated_count":len(ids),"available_count":available-len(ids),
                    "employees":[{"employee_id":str(p.pk),"name":p.name,"count":quantity} for p in people]}
                status=200
        except AccessError as error:result,status=failure(error)
        return remember(actor,"DISTRIBUTE",key,body_hash,result,status=status,target_ids=[site_id])


@retry_transient_write
def recall(actor,body):
    site_id,value,key,body_hash=checked_body(body,distribute=False)
    with business_write():
        ids=list(employee_rows().values_list("pk",flat=True)) if value=="all" else [value]
        actor=locked_actor(actor,admin=True,extra_ids=ids)
        site_for(site_id,lock=True)
        cached=replay(actor,"MANUAL_RECALL",key,body_hash)
        if cached:return cached
        try:
            people=recipients(value);now=timezone.now()
            customers=list(today_query(site_id,people,now).select_for_update(of=("self",)).order_by("pk"))
            assignments=list(Assignment.objects.select_for_update().filter(pk__in=[c.current_assignment_id for c in customers]).order_by("pk"))
            end_locked(customers,assignments,actor,Assignment.EndReason.MANUAL_RECALL,now)
            OperationEvent.objects.create(actor=actor,operation="MANUAL_RECALL",occurred_at=now,affected_count=len(customers))
            result={"ok":True,"site_id":str(site_id),"business_date":timezone.localdate(now,KST).isoformat(),"recalled_count":len(customers),"available_count":eligible(site_id).count()};status=200
        except AccessError as error:result,status=failure(error)
        return remember(actor,"MANUAL_RECALL",key,body_hash,result,status=status,target_ids=[site_id])


@retry_transient_write
def change_assignee(actor,customer_id,body):
    if set(body)!={"site_id","employee_id","assignment_id","expected_version","idempotency_key"}:invalid("담당자 변경 형식을 확인해 주세요.")
    site_id,target_id,old_id,key=identifier(body["site_id"]),identifier(body["employee_id"],nullable=True),identifier(body["assignment_id"],nullable=True),identifier(body["idempotency_key"])
    if type(body["expected_version"]) is not int or body["expected_version"]<1:invalid("고객 버전을 확인해 주세요.")
    body_hash=fingerprint({"customer_id":str(customer_id),"site_id":str(site_id),"employee_id":str(target_id) if target_id else None,
        "assignment_id":str(old_id) if old_id else None,"expected_version":body["expected_version"]})
    with business_write():
        current_owner=Customer.objects.filter(pk=customer_id).values_list("current_assignment__employee_id",flat=True).first()
        actor=locked_actor(actor,admin=True,extra_ids=[uid for uid in [target_id,current_owner] if uid])
        site_for(site_id,lock=True)
        customer=Customer.objects.select_for_update().filter(pk=customer_id,site_id=site_id).first()
        if not customer:raise AccessError("CUSTOMER_DELETED","고객정보를 사용할 수 없습니다.",409)
        cached=replay(actor,"ASSIGNEE_CHANGE",key,body_hash)
        if cached:return cached
        try:
            with transaction.atomic():
                if customer.deleted_at:raise AccessError("CUSTOMER_DELETED","휴지통의 고객은 담당자를 변경할 수 없습니다.",409)
                if customer.current_assignment_id!=old_id:raise AccessError("ASSIGNMENT_CHANGED","담당자가 변경되었습니다. 다시 조회해 주세요.",409)
                if customer.version!=body["expected_version"]:raise AccessError("VERSION_CONFLICT","상담정보가 변경되었습니다. 다시 조회한 후 담당자를 선택해 주세요.",409)
                assignment=Assignment.objects.select_for_update().filter(pk=old_id).first()
                if assignment and (assignment.customer_id!=customer.pk or assignment.ended_at):raise AccessError("ASSIGNMENT_CHANGED","현재 할당 상태를 확인해 주세요.",409)
                current_id=assignment.employee_id if assignment else None
                changed=current_id!=target_id
                if changed:
                    target=None if target_id is None else recipients(target_id)[0]
                    now=timezone.now()
                    if assignment:
                        end_locked([customer],[assignment],actor,Assignment.EndReason.REASSIGNED if target else Assignment.EndReason.MANUAL_RECALL,now)
                    else:customer.version+=1
                    if target:
                        customer.current_assignment=Assignment.objects.create(customer=customer,employee=target,assigned_by=actor,assigned_at=now)
                    customer.save(update_fields=["current_assignment","version","updated_at"])
                    OperationEvent.objects.create(actor=actor,operation="ASSIGNEE_CHANGED",occurred_at=now,affected_count=1)
                result={"ok":True,"changed":changed,"customer_id":str(customer.pk),"assignment_id":str(customer.current_assignment_id) if customer.current_assignment_id else None,
                    "employee_id":str(target_id) if target_id else None,"version":customer.version};status=200
        except AccessError as error:result,status=failure(error)
        return remember(actor,"ASSIGNEE_CHANGE",key,body_hash,result,status=status,target_ids=[site_id,customer_id])
