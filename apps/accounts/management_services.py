from django.core.exceptions import ValidationError
from django.db import IntegrityError,transaction
from django.db.models import Count,Q
from django.utils import timezone
from apps.accounts.access import AccessError,verify_actor
from apps.accounts.models import User
from apps.accounts.bootstrap import BOOTSTRAP_ADMIN_ID
from apps.common.http import identifier
from apps.common.receipts import fingerprint,replay,remember
from apps.common.transactions import business_write,retry_transient_write
from apps.common.validation import normalize_phone
from apps.operations.models import OperationEvent


def invalid(message):raise AccessError("VALIDATION_ERROR",message,422)


def public_user(person,transfer_count=0):
    return {"id":str(person.pk),"name":person.name,"phone":person.phone_normalized,"role":person.role,"is_active":person.is_active,
        "must_change_password":person.must_change_password,"version":person.updated_at.isoformat(),"transfer_needed_count":transfer_count}


def transfer_query():
    from apps.customers.models import Customer
    return Customer.objects.filter(deleted_at__isnull=True,current_assignment__ended_at__isnull=True,
        current_assignment__employee__is_active=False,current_assignment__first_activity_at__isnull=False).exclude(current_assignment=None)


def user_list(params):
    if set(params)-{"page","q"}:invalid("사용자 조회 조건을 확인해 주세요.")
    try:page=int(params.get("page",1))
    except (ValueError,TypeError):page=0
    q=params.get("q","")
    if not 1<=page<=1000000 or len(q)>200:invalid("사용자 조회 조건을 확인해 주세요.")
    query=User.objects.all()
    if q.strip():query=query.filter(Q(name__icontains=q.strip())|Q(phone_normalized__contains=q.replace("-","").strip()))
    total=query.count();rows=list(query.order_by("created_at","pk")[(page-1)*50:page*50])
    counts=dict(transfer_query().values("current_assignment__employee_id").annotate(n=Count("pk")).values_list("current_assignment__employee_id","n"))
    return {"items":[public_user(person,counts.get(person.pk,0)) for person in rows],"total":total,"page":page,"last_page":max(1,(total+49)//50)}


def transfer_list(params):
    if set(params)-{"page"}:invalid("이관 목록 조회 조건을 확인해 주세요.")
    try:page=int(params.get("page",1))
    except (ValueError,TypeError):page=0
    if not 1<=page<=1000000:invalid("페이지를 확인해 주세요.")
    query=transfer_query().select_related("site","current_assignment__employee").order_by("site_id","pk")
    total=query.count()
    return {"items":[{"id":str(c.pk),"customer_name":c.customer_name,"phone":c.phone_normalized,"site_id":str(c.site_id),"site_name":c.site.name,
        "employee_id":str(c.current_assignment.employee_id),"employee_name":c.current_assignment.employee.name} for c in query[(page-1)*50:page*50]],
        "total":total,"page":page,"last_page":max(1,(total+49)//50)}


def normalized(name,phone,role,active):
    if not isinstance(name,str) or not name.strip() or len(name.strip())>100:invalid("이름은 1~100자로 입력해 주세요.")
    if phone != BOOTSTRAP_ADMIN_ID:
        try:phone=normalize_phone(phone)
        except ValidationError:invalid("전화번호는 010으로 시작하는 11자리로 입력해 주세요.")
    if role not in User.Role.values or type(active) is not bool:invalid("활성 상태와 역할을 확인해 주세요.")
    return {"name":name.strip(),"phone_normalized":phone,"role":role,"is_active":active}


def locked_users(actor):
    users={p.pk:p for p in User.objects.select_for_update().order_by("pk")}
    current=users.get(actor.pk)
    if not current:raise AccessError("UNAUTHENTICATED","다시 로그인해 주세요.",401)
    verify_actor(actor,current,admin=True)
    return current,users


def check_capacity(before,after):
    """Called under the shared business lock, including batch handovers.

    Existing oversized installations can still reduce their active population.
    Inactive accounts retain their history without occupying an active slot.
    """
    before=list(before);after=list(after)
    for role,limit in [(User.Role.EMPLOYEE,20),(User.Role.ADMIN,5)]:
        count=lambda rows:sum(p['is_active'] and p['role']==role for p in rows)
        if count(after)>limit and count(after)>count(before):
            raise AccessError('USER_CAPACITY_LIMIT','활성 직원은 최대 20명, 활성 관리자는 최대 5명입니다.',409)


def apply_edits(actor,users,edits):
    """Validate the final batch state before any user or assignment is changed."""
    for uid, values in edits.items():
        if (users[uid].phone_normalized == BOOTSTRAP_ADMIN_ID
                and (values["phone_normalized"] != BOOTSTRAP_ADMIN_ID or values["role"] != User.Role.ADMIN)):
            raise AccessError("BOOTSTRAP_ADMIN_PROTECTED", "최초 관리자 아이디와 관리자 역할은 변경할 수 없습니다.", 409)
        if users[uid].phone_normalized != BOOTSTRAP_ADMIN_ID and values["phone_normalized"] == BOOTSTRAP_ADMIN_ID:
            invalid("admin은 최초 관리자 전용 아이디입니다.")
    final={uid:{"role":p.role,"is_active":p.is_active} for uid,p in users.items()}
    for uid,values in edits.items():final[uid].update(role=values["role"],is_active=values["is_active"])
    if not any(v["role"]==User.Role.ADMIN and v["is_active"] for v in final.values()):
        raise AccessError("LAST_ACTIVE_ADMIN","마지막 활성 관리자는 비활성화하거나 직원으로 변경할 수 없습니다.",409)
    check_capacity([{'role':p.role,'is_active':p.is_active} for p in users.values()],final.values())
    phones=[values["phone_normalized"] for values in edits.values()]
    if len(phones)!=len(set(phones)):raise AccessError("DUPLICATE_PHONE","사용자 전화번호가 중복됩니다.",409)
    for uid,values in edits.items():
        if any(p.pk!=uid and p.phone_normalized==values["phone_normalized"] for p in users.values()):
            raise AccessError("DUPLICATE_PHONE","이미 사용 중인 사용자 전화번호입니다. 먼저 해당 번호를 변경한 뒤 다시 저장해 주세요.",409)
    disabling=[uid for uid,values in edits.items() if users[uid].is_active and not values["is_active"]]
    from apps.customers.models import Customer
    from apps.sites.models import Site
    from apps.assignments.models import Assignment
    from apps.assignments.services import end_locked
    query=Customer.objects.filter(deleted_at__isnull=True,current_assignment__employee_id__in=disabling,
        current_assignment__ended_at__isnull=True,current_assignment__first_activity_at__isnull=True).exclude(current_assignment=None)
    list(Site.objects.select_for_update().filter(pk__in=query.values("site_id")).order_by("pk"))
    customers=list(query.select_for_update(of=("self",)).order_by("pk"))
    assignments=list(Assignment.objects.select_for_update().filter(pk__in=[c.current_assignment_id for c in customers]).order_by("pk"))
    now=timezone.now();end_locked(customers,assignments,actor,Assignment.EndReason.USER_DISABLED,now)
    changed=[];self_changed=False
    for uid,values in edits.items():
        person=users[uid]
        fields=[field for field,value in values.items() if getattr(person,field)!=value]
        if not fields:continue
        security=any(field in fields for field in ["phone_normalized","role","is_active"])
        for field,value in values.items():setattr(person,field,value)
        if security:person.session_version+=1
        person.save(update_fields=[*fields,*( ["session_version"] if security else []),"updated_at"])
        if uid==actor.pk and security:self_changed=True
        changed.append(uid)
    if changed:OperationEvent.objects.create(actor=actor,operation="USER_ACCESS_CHANGED",occurred_at=now,affected_count=len(changed))
    return {"ok":True,"updated_count":len(changed),"recalled_count":len(customers),"transfer_needed_count":transfer_query().count(),
        "requires_relogin":self_changed,"versions":{str(uid):users[uid].updated_at.isoformat() for uid in edits}}


@retry_transient_write
def create_user(actor,body):
    if set(body)!={"name","phone","role","idempotency_key"}:invalid("이름·전화번호·관리자 여부와 요청 키를 확인해 주세요.")
    values=normalized(body["name"],body["phone"],body["role"],True)
    if values["phone_normalized"] == BOOTSTRAP_ADMIN_ID:invalid("admin은 최초 관리자 전용 아이디입니다.")
    key=identifier(body["idempotency_key"]);body_hash=fingerprint(values)
    with business_write():
        actor,users=locked_users(actor)
        cached=replay(actor,"USER_CREATE",key,body_hash)
        if cached:return cached
        if any(p.phone_normalized==values["phone_normalized"] for p in users.values()):raise AccessError("DUPLICATE_PHONE","이미 사용 중인 사용자 전화번호입니다.",409)
        current=[{'role':p.role,'is_active':p.is_active} for p in users.values()]
        check_capacity(current,[*current,values])
        from apps.accounts.services import INITIAL_PASSWORD
        try:
            with transaction.atomic():person=User.objects.create_user(values.pop("phone_normalized"),values.pop("name"),INITIAL_PASSWORD,**values)
        except (ValidationError,IntegrityError):raise AccessError("DUPLICATE_PHONE","사용자 입력값이나 중복 전화번호를 확인해 주세요.",409)
        OperationEvent.objects.create(actor=actor,operation="USER_CREATED",occurred_at=timezone.now(),affected_count=1)
        return remember(actor,"USER_CREATE",key,body_hash,{"ok":True,"id":str(person.pk),"must_change_password":True},target_ids=[person.pk])


@retry_transient_write
def update_users(actor,body):
    if set(body)!={"rows","idempotency_key"} or not isinstance(body["rows"],list) or not 1<=len(body["rows"])<=100:invalid("사용자 1~100명을 저장해 주세요.")
    key=identifier(body["idempotency_key"]);normalized_rows=[]
    for row in body["rows"]:
        if not isinstance(row,dict) or set(row)!={"id","name","phone","role","is_active","expected_version"}:invalid("사용자 저장 형식을 확인해 주세요.")
        uid=identifier(row["id"])
        if not isinstance(row["expected_version"],str):invalid("사용자 버전을 확인해 주세요.")
        normalized_rows.append((uid,row["expected_version"],normalized(row["name"],row["phone"],row["role"],row["is_active"])))
    if len({uid for uid,_,_ in normalized_rows})!=len(normalized_rows):invalid("같은 사용자를 중복 저장할 수 없습니다.")
    body_hash=fingerprint(sorted([{"id":str(uid),"expected_version":version,**values} for uid,version,values in normalized_rows],key=lambda item:item["id"]))
    with business_write():
        actor,users=locked_users(actor)
        cached=replay(actor,"USER_UPDATE",key,body_hash)
        if cached:return cached
        for uid,version,_ in normalized_rows:
            if uid not in users:raise AccessError("NOT_FOUND","사용자를 찾을 수 없습니다.",404)
            if users[uid].updated_at.isoformat()!=version:raise AccessError("VERSION_CONFLICT","사용자가 변경되었습니다. 현재 변경값을 보관하고 다시 조회해 비교해 주세요.",409)
        result=apply_edits(actor,users,{uid:values for uid,_,values in normalized_rows})
        return remember(actor,"USER_UPDATE",key,body_hash,result,target_ids=[uid for uid,_,_ in normalized_rows])


@retry_transient_write
def update_access(actor,target_id,*,is_active=None,role=None):
    with business_write():
        actor,users=locked_users(actor)
        target=users.get(target_id)
        if target is None:raise AccessError("NOT_FOUND","사용자를 찾을 수 없습니다.",404)
        values=normalized(target.name,target.phone_normalized,target.role if role is None else role,target.is_active if is_active is None else is_active)
        apply_edits(actor,users,{target_id:values})
        return users[target_id]
