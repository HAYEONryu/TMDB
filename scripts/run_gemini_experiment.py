"""Explicit free-only experiment. Uses a dedicated fake-data DB and durable cap."""
import argparse
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, time, timezone as utc_timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
from uuid import uuid5, NAMESPACE_URL

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.gemini_experiment_budget import ExperimentBudget,ExperimentStopped,ExperimentWait,MODEL

DIRECTORY=ROOT/'.local/gemini-experiment'
DB_NAME='test_tm_gemini_experiment'


def store(name,value):
    path=DIRECTORY/name
    temporary=path.with_suffix('.pending')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')
    temporary.chmod(0o600);os.replace(temporary,path)


def initialize():
    confirmation=json.loads((DIRECTORY/'confirmation.json').read_text())
    budget=ExperimentBudget(DIRECTORY,confirmation)
    budget.validate_confirmation()
    from config.ai import load_ai_config
    config=load_ai_config(ROOT,role='ai_worker',environment={})
    if (not config.api_key or config.provider!='gemini' or config.model!=MODEL or config.usage_tier!='free'
        or config.free_project_id!=confirmation['project_id']
        or (config.free_rpm,config.free_tpm,config.free_rpd)!=(confirmation['rpm'],confirmation['tpm'],confirmation['rpd'])):
        raise ExperimentStopped('LOCAL_CONFIGURATION_MISMATCH')
    config=replace(config,enabled=True,configured=True,free_tier_confirmed=True,
        monthly_budget_usd=Decimal(0),test_budget_usd=Decimal(0),test_budget_scope='gemini-free-live-v1')
    from apps.ai_assistant.gemini_policy import supported
    if not supported(config):raise ExperimentStopped('FREE_MODEL_CONFIGURATION_UNSUPPORTED')
    # This dedicated cluster is independent of developer and demo PostgreSQL.
    state=json.loads((ROOT/'.local/free-ai-test/state.json').read_text())
    import psycopg
    with psycopg.connect(host='127.0.0.1',port=55434,user='tm_free_test',password=state['database_password'],dbname='postgres',autocommit=True) as connection:
        if not connection.execute('SELECT 1 FROM pg_database WHERE datname=%s',(DB_NAME,)).fetchone():
            from psycopg import sql
            connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(DB_NAME)))
    for name in list(os.environ):
        if name.startswith('AI_'):os.environ.pop(name)
    os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',TM_PROCESS_ROLE='management',
        DATABASE_URL='postgresql://tm_free_test:'+quote(state['database_password'],safe='')+'@127.0.0.1:55434/'+DB_NAME,
        DJANGO_SECRET_KEY='synthetic-isolated-gemini-experiment-only',DJANGO_DEBUG='false',ALLOW_DEMO_SEED='false')
    import django;django.setup()
    from django.conf import settings
    from django.core.management import call_command
    assert settings.DATABASES['default']['NAME']==DB_NAME and str(settings.DATABASES['default']['PORT'])=='55434'
    call_command('migrate',interactive=False,verbosity=0)
    return config,budget


def seed():
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.sites.models import Site
    from apps.customers.models import Customer
    from apps.assignments.models import Assignment
    from apps.consultations.models import ConsultationRevision
    from apps.ai_assistant.models import SiteKnowledge
    path=DIRECTORY/'fixtures.json'
    if path.exists():
        meta=json.loads(path.read_text())
        assert meta['database']==DB_NAME
        return meta
    allowed={'01099770001','01099770002','01099770003'}
    if set(User.objects.values_list('phone_normalized',flat=True))-allowed or Customer.objects.exists():
        raise ExperimentStopped('UNRECOGNIZED_EXPERIMENT_DB')
    def account(phone,name,role):
        existing=User.objects.filter(phone_normalized=phone).first()
        if existing:
            if existing.name!=name or existing.role!=role:raise ExperimentStopped('FAKE_ACCOUNT_COLLISION')
            return existing
        return User.objects.create_user(phone,name,'Synthetic!Only2026',role=role,must_change_password=False)
    admin=account('01099770001','가상실험관리자','ADMIN')
    staff=account('01099770002','가상실험직원','EMPLOYEE')
    other=account('01099770003','가상실험다른직원','EMPLOYEE')
    site=Site.objects.create(name='가상 Gemini 실험 현장',created_by=admin)
    note='가상 상담 기록입니다. 오후 연락을 원한다고 말했다. 내일 14:00에 다시 통화하기로 했다. 방문과 계약은 아직 정하지 않았다. 거절 사유와 예산은 기록되지 않았다.'
    customer=Customer.objects.create(site=site,customer_name='가상실험고객',phone_normalized='01099779999',notes=note,call_result='INTERESTED')
    now=timezone.now()
    assignment=Assignment.objects.create(customer=customer,employee=staff,assigned_by=admin,assigned_at=now-timedelta(minutes=1))
    customer.current_assignment=assignment;customer.save(update_fields=['current_assignment'])
    # A prior note predates the current assignment: AI must not mark it progressed.
    origin=now-timedelta(hours=2)
    ConsultationRevision.objects.create(customer=customer,actor=staff,source='MANUAL',saved_at=origin,
        customer_version=1,changed_fields=['notes','call_result'],after_values={'notes':note,'call_result':'INTERESTED'},notes=note)
    SiteKnowledge.objects.create(site=site,title='가상 확인 안내',body='이 가상 현장의 확정 가격이나 대출 조건은 안내자료에 없습니다. 비용 관련 질문은 현장 담당자에게 확인해야 합니다.',
        reviewed_by=admin,reviewed_at=now,is_valid=True)
    meta={'database':DB_NAME,'admin_id':str(admin.pk),'staff_id':str(staff.pk),'other_staff_id':str(other.pk),
        'site_id':str(site.pk),'customer_id':str(customer.pk),'notes_saved_at':origin.isoformat(),'features':{}}
    from django.db import transaction
    transaction.on_commit(lambda:store('fixtures.json',meta))
    return meta


def fingerprint(meta):
    from django.core.serializers.json import DjangoJSONEncoder
    from apps.customers.models import Customer
    from apps.assignments.models import Assignment
    from apps.consultations.models import ConsultationRevision
    from apps.callbacks.models import Callback
    data={'customer':list(Customer.objects.filter(pk=meta['customer_id']).values()),
          'assignment':list(Assignment.objects.filter(customer_id=meta['customer_id']).values()),
          'revisions':list(ConsultationRevision.objects.filter(customer_id=meta['customer_id']).values()),
          'callbacks':list(Callback.objects.filter(customer_id=meta['customer_id']).values())}
    return hashlib.sha256(json.dumps(data,sort_keys=True,cls=DjangoJSONEncoder).encode()).hexdigest()


def run(feature,config,budget,meta,date_check=False):
    from unittest.mock import patch
    from django.test import override_settings
    from django.utils import timezone
    from apps.accounts.models import User
    from apps.accounts.access import AccessError
    from apps.customers.models import Customer
    from apps.customers.queries import KST
    from apps.ai_assistant.models import AIRequest
    from apps.ai_assistant.services import reserve
    from apps.ai_assistant.worker import run_once
    from apps.ai_assistant.gemini_adapter import GeminiAdapter,_post
    before=fingerprint(meta)
    staff=feature in {'SUMMARY','CLEANUP','NEXT_QUESTIONS'}
    customer=Customer.objects.get(pk=meta['customer_id'])
    actor=User.objects.get(pk=meta['staff_id'] if staff else meta['admin_id'])
    label=feature+('-date-context-v1' if date_check else '')
    body={'feature':feature,'idempotency_key':str(uuid5(NAMESPACE_URL,'tm-gemini-free-live-v1/'+label))}
    if staff:body.update(customer_id=str(customer.pk),assignment_id=str(customer.current_assignment_id),expected_version=customer.version)
    elif feature=='EMPLOYEE_COACHING':body['employee_id']=meta['staff_id']
    elif feature=='TEAM_GUIDE':body['site_id']=meta['site_id']
    context=nullcontext()
    if feature=='WEEKLY_BRIEFING':
        actual=timezone.now();local=timezone.localtime(actual,KST)
        sunday=local.date()+timedelta(days=(6-local.weekday())%7)
        fixed=datetime.combine(sunday,time(14),KST)
        context=patch('django.utils.timezone.now',return_value=fixed)
        # Business-date mock only. Budget uses real UTC/Pacific time separately.
    with override_settings(AI_CONFIG=config,TESTING=False,AI_FOUNDATION_TEST_MODE=False):
        if feature=='WEEKLY_BRIEFING':
            monday=datetime(2026,11,9,14,tzinfo=KST)
            with patch('django.utils.timezone.now',return_value=monday):
                try:reserve(actor,body)
                except AccessError as error:
                    if error.code!='AI_SUNDAY_ONLY':raise
                else:raise ExperimentStopped('WEEKDAY_RULE_NOT_ENFORCED')
        with context:
            task,created=reserve(actor,body)
            meta['features'][label]=str(task.pk);store('fixtures.json',meta)
            if task.status=='SUCCEEDED':
                return {'feature':feature,'status':'SUCCEEDED','reused':True,'new_external_requests':0}
            if task.status!='RESERVED':raise ExperimentStopped('PREVIOUS_FEATURE_NOT_SUCCESSFUL_RESOLVE_BEFORE_RETRY')
            budget.check(task.input_tokens_cap)
            forbidden=list(User.objects.values_list('name',flat=True))+list(User.objects.values_list('phone_normalized',flat=True))+[customer.customer_name,customer.phone_normalized]
            def transport(body,key):
                text=body.decode()
                if any(value and value in text for value in forbidden):raise ExperimentStopped('IDENTIFIER_IN_REQUEST')
                response=budget.send(feature,task.input_tokens_cap,body,key,lambda body,key:_post(body,key,model=config.model))
                # Fake-data experiment only: preserve proposed dates for quality review.
                if feature=='CLEANUP' and response[0]==200:
                    try:
                        payload=json.loads(response[1]['candidates'][0]['content']['parts'][0]['text'])
                        values={name:payload['suggestions'][name].get('value') for name in ['callback_due_at','visit_at']}
                        from django.utils.dateparse import parse_datetime
                        safe={name:value for name,value in values.items() if value is None or (isinstance(value,str) and len(value)<=40 and parse_datetime(value) is not None)}
                        store(label.lower()+'-proposed-dates.json',safe)
                    except (KeyError,TypeError,ValueError):pass
                return response
            result=run_once(GeminiAdapter(transport=transport))
            task.refresh_from_db();task.result.refresh_from_db()
            after=fingerprint(meta)
            if before!=after:raise ExperimentStopped('AI_CHANGED_CUSTOMER_WITHOUT_SELECTION')
            output={'feature':feature,'status':task.status,'error_code':task.error_code,'worker':result,
                'customer_unchanged':True,'charged_cost_usd_recorded':str(task.charged_cost),
                'payload':task.result.payload if task.result.valid else None,'billing_verified':False,
                'attempts':list(task.attempts.values('sequence','status','input_tokens','output_tokens','reasoning_tokens','cached_tokens','transport_started_at'))}
            store(label.lower()+'.json',output)
            return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('feature',choices=['prepare','SUMMARY','CLEANUP','NEXT_QUESTIONS','WEEKLY_BRIEFING','EMPLOYEE_COACHING','TEAM_GUIDE'])
    parser.add_argument('--date-context-check',action='store_true')
    args=parser.parse_args()
    config,budget=initialize()
    from django.db import transaction
    with transaction.atomic():meta=seed()
    if args.feature=='prepare':
        print(json.dumps({'database':DB_NAME,'only_fake_records':True,'requests_started':len(budget.read()['calls']),'limit':10}));return 0
    if args.date_context_check and args.feature!='CLEANUP':raise ExperimentStopped('DATE_CHECK_FEATURE_INVALID')
    output=run(args.feature,config,budget,meta,args.date_context_check)
    print(json.dumps({k:v for k,v in output.items() if k not in {'payload'}},ensure_ascii=False,default=str))
    return 0 if output['status']=='SUCCEEDED' else 2


if __name__=='__main__':
    try:raise SystemExit(main())
    except ExperimentWait as error:
        print(json.dumps({'stopped':'MINUTE_LIMIT_WAIT','seconds':error.seconds}));raise SystemExit(4)
    except ExperimentStopped as error:
        print(json.dumps({'stopped':str(error)}));raise SystemExit(3)
    except Exception as error:
        # Never print exception text, transport bodies, secrets or connection DSNs.
        import traceback
        cause=getattr(error,'__cause__',None);diag=getattr(cause,'diag',None)
        print(json.dumps({'stopped':'LOCAL_SETUP_OR_VALIDATION_ERROR','type':type(error).__name__,
            'column':getattr(diag,'column_name',None),'constraint':getattr(diag,'constraint_name',None),
            'locations':[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(error.__traceback__) if str(ROOT) in frame.filename][-5:]}));raise SystemExit(5)
