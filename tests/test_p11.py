import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
from django.db import close_old_connections,connection
from django.test import TransactionTestCase,override_settings,Client
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.ai_assistant.adapters import FoundationFakeAdapter
from apps.ai_assistant.admin_schema import validate
from apps.ai_assistant.inputs import build
from apps.ai_assistant.models import AIRequest,AIResult,AIReportSnapshot,AIReportSlot,AIUsageAttempt,AIResultSource,AINoteClassification,GuidePublication,SiteKnowledge
from apps.ai_assistant.privacy import invalidate_results
from apps.ai_assistant.services import reserve
from apps.ai_assistant.worker import claim,finish,run_once,ProviderResponse
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.common.transactions import business_write
from apps.customers.queries import KST
from apps.customers.services import trash_operation
from apps.customers.deletions import hard_delete_customer
from apps.operations.models import OperationEvent,IdempotencyRecord
from tests.helpers import login,user,TEST_HASHERS
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI


@override_settings(PASSWORD_HASHERS=TEST_HASHERS,AI_FOUNDATION_TEST_MODE=True,AI_CONFIG=TEST_AI)
class P11Tests(Fixtures,TransactionTestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0];self.now=timezone.now();self.at=self.now-timedelta(days=2)
        self.revision=self.note(self.customer,self.employee,self.at,'가격 비교 후 나중에 연락 요청',1)
        self.client=login(self.admin)
    def note(self,customer,actor,at,notes,version=1,source='MANUAL'):
        return ConsultationRevision.objects.create(customer=customer,actor=actor,saved_at=at,customer_version=version,changed_fields=['notes','call_result'],after_values={'notes':notes,'call_result':'CALL_AGAIN'},notes=notes,source=source)
    def task(self,feature='TEAM_GUIDE',actor=None,at=None,**values):
        body={'feature':feature,'idempotency_key':str(uuid4())}
        if feature=='TEAM_GUIDE':body['site_id']=str(self.site.pk)
        if feature=='EMPLOYEE_COACHING':body['employee_id']=str(self.employee.pk)
        body.update(values)
        with patch('django.utils.timezone.now',return_value=at or self.now):return reserve(actor or self.admin,body)[0]
    def success(self,task):
        with patch('django.utils.timezone.now',return_value=task.period_end):self.assertEqual(run_once()['succeeded'],1)
        task.refresh_from_db();return task.result
    def write(self,result,body=None,reviewed=True,version=None,key=None):
        payload={'body':body or result.guide_body,'reviewed':reviewed,'expected_version':version or result.guide_version,'idempotency_key':key or str(uuid4())}
        return self.client.patch(f'/api/ai/guides/{result.pk}',payload,content_type='application/json')
    def publish(self,result):
        return self.client.post(f'/api/ai/guides/{result.pk}/publish',{'expected_version':result.guide_version,'idempotency_key':str(uuid4())},content_type='application/json')
    def test_weekly_sunday_year_boundary_cutoff_shared_slot_and_weekday_read(self):
        sunday=datetime(2027,1,3,23,59,tzinfo=KST)
        task=self.task('WEEKLY_BRIEFING',at=sunday)
        self.assertEqual(task.period_key,'2026-12-28');self.assertEqual(task.period_start,datetime(2026,12,28,tzinfo=KST));self.assertEqual(task.period_end,sunday)
        running=claim(now=sunday);response=FoundationFakeAdapter().execute_task(running,running.input_payload)
        self.assertTrue(finish(task.pk,running.lease_token,response=response,now=sunday+timedelta(minutes=2)))
        with patch('django.utils.timezone.now',return_value=sunday+timedelta(days=1)):
            self.client=login(self.admin)
            self.assertEqual(self.client.get('/api/ai/weekly-briefings').status_code,200)
            response=self.client.post('/api/ai/weekly-briefings',{'idempotency_key':str(uuid4())},content_type='application/json')
        self.assertEqual(response.json()['error']['code'],'AI_SUNDAY_ONLY');self.assertEqual(AIRequest.objects.count(),1)
    def test_future_revisions_and_system_notes_excluded(self):
        self.note(self.customer,self.employee,self.now+timedelta(seconds=1),'미래',2)
        self.note(self.customer,self.admin,self.at,'시스템 승인',3,'SYSTEM_DELETE_NOTE')
        task=self.task();self.assertEqual(len(task.input_payload['records']),1);self.assertEqual(task.report_snapshot.data['statistics']['changed_customers'],1)
    def test_latest_customer_actor_korean_day_and_actual_author_not_assignee(self):
        self.assign(self.customer,self.other);last=self.note(self.customer,self.employee,self.at+timedelta(minutes=1),'위치 가격 확인',2)
        task=self.task('EMPLOYEE_COACHING');self.assertEqual([r['source_id'] for r in task.input_payload['records']],[str(last.pk)])
        rows=task.report_snapshot.data['statistics']['employees'];self.assertEqual(rows[0]['actor_id'],str(self.employee.pk));self.assertEqual(rows[0]['changed_customers'],1);self.assertEqual(rows[0]['assigned'],0)
    def test_korean_date_groups_cross_utc_midnight(self):
        one=datetime(2026,11,1,23,59,tzinfo=KST);two=one+timedelta(minutes=2)
        ConsultationRevision.objects.all().delete();self.note(self.customer,self.employee,one,'가격',1);self.note(self.customer,self.employee,two,'위치',2)
        task=self.task(at=two+timedelta(hours=1));self.assertEqual(task.report_snapshot.data['sampling']['total_note_groups'],2)
    def test_inactive_and_promoted_actual_workers_in_weekly_sql_totals(self):
        self.employee.is_active=False;self.employee.save();self.other.role='ADMIN';self.other.save();self.note(self.customer,self.other,self.at,'비교',2)
        sunday=self.now+timedelta(days=(6-self.now.astimezone(KST).weekday())%7)
        task=self.task('WEEKLY_BRIEFING',at=sunday);ids={r['actor_id'] for r in task.report_snapshot.data['statistics']['employees']}
        self.assertIn(str(self.employee.pk),ids);self.assertIn(str(self.other.pk),ids)
    def test_callback_completion_and_overdue_attributed_to_real_actor(self):
        self.assign(self.customer,self.other);Callback.objects.create(customer=self.customer,due_at=self.at,created_by=self.employee,updated_by=self.employee,completed_by=self.employee,completed_at=self.at+timedelta(hours=1),status='COMPLETED')
        Callback.objects.update(created_at=self.at)
        task=self.task('EMPLOYEE_COACHING');row=task.report_snapshot.data['statistics']['employees'][0];self.assertEqual(row['callbacks_completed'],1);self.assertEqual(row['callbacks_overdue_created'],0)
    def test_numeric_full_scope_not_sample_100_plus_and_bounded_provider_input(self):
        customers=self.customers(150,offset=10)
        ConsultationRevision.objects.bulk_create([ConsultationRevision(customer=c,actor=self.employee,saved_at=self.at,customer_version=1,changed_fields=['notes'],notes='가격 문의 '*300,source='MANUAL') for c in customers])
        task=self.task();self.assertLessEqual(len(json.dumps(task.input_payload,ensure_ascii=False).encode()),12000)
        snap=task.report_snapshot.data;self.assertEqual(snap['statistics']['changed_customers'],151);self.assertGreater(snap['sampling']['omitted_groups'],0)
        self.assertEqual(snap['sampling']['total_note_groups'],151)
    def test_reaction_multilabel_distinct_customers_and_classification_cache(self):
        self.note(self.customer,self.employee,self.at+timedelta(days=1),'가격 비교',2)
        result=self.success(self.task());stats=result.payload['reaction_statistics'];self.assertEqual(stats['analyzed_customers'],1);self.assertEqual(stats['labels']['PRICE'],1);self.assertEqual(stats['labels']['COMPARISON'],1)
        self.assertEqual(AINoteClassification.objects.count(),2)
        next_task=self.task(at=self.now+timedelta(days=1));self.assertEqual(next_task.report_snapshot.data['sampling']['cached_groups'],2)
    def test_unknown_source_or_unproven_label_is_not_counted(self):
        task=self.task();payload=FoundationFakeAdapter().execute_task(task,task.input_payload).payload
        payload['classifications']=[{'source_id':str(uuid4()),'labels':['PRICE'],'evidence':'가격'},{'source_id':str(self.revision.pk),'labels':['LOCATION'],'evidence':'가격'}]
        valid=validate(task,payload);self.assertEqual(valid['classifications'],[]);self.assertGreater(valid['unverified_items'],0)
    def test_source_injection_url_html_key_numeric_claim_fails_closed(self):
        task=self.task('EMPLOYEE_COACHING');base=FoundationFakeAdapter().execute_task(task,task.input_payload).payload
        for unsafe in ['전체 99명 향상','https://example.invalid','<script>실행</script>',TEST_AI.api_key,'성격이 좋다']:
            payload=json.loads(json.dumps(base));payload['findings'][0]['text']=unsafe;self.assertIsNone(validate(task,payload))
    def test_first_coaching_no_history_and_insufficient_comparison(self):
        result=self.success(self.task('EMPLOYEE_COACHING'));self.assertEqual(result.payload['comparison']['status'],'판단 불가');self.assertEqual(result.payload['sampling']['previous_coaching_included'],0)
        self.assertFalse(any(r['section']=='CHANGES' for r in result.payload['findings']))
    def test_last_three_valid_coachings_and_older_actions_are_sources(self):
        results=[]
        for days in [6,5,4,3]:results.append(self.success(self.task('EMPLOYEE_COACHING',at=self.now-timedelta(days=days))))
        # These early examples have no in-window records, add structured follow-up explicitly as an old valid coaching.
        results[0].payload['actions']=[{'text':'추가 확인','source_ids':[],'evidence':'','confirmed':False}];results[0].save()
        task=self.task('EMPLOYEE_COACHING');self.assertEqual(len(task.input_payload['previous_coaching']),3);self.assertEqual(len(task.input_payload['older_actions']),1)
        self.assertEqual(task.result.sources.filter(previous_result__isnull=False).count(),4)
    def test_comparison_windows_observations_and_no_causal_claim(self):
        prior=self.success(self.task('EMPLOYEE_COACHING',at=self.now-timedelta(days=1)))
        self.note(self.customer,self.employee,self.now-timedelta(hours=1),'위치 문의',2)
        task=self.task('EMPLOYEE_COACHING');comparison=task.report_snapshot.data['comparison'];self.assertEqual(comparison['status'],'관찰 가능');self.assertEqual((comparison['before_customers'],comparison['after_customers']),(1,1));self.assertIn('인과',comparison['reason'])
    def test_only_reviewed_valid_knowledge_and_fact_quotes(self):
        SiteKnowledge.objects.create(site=self.site,title='미검토',body='금액 확정',is_valid=False)
        good=SiteKnowledge.objects.create(site=self.site,title='공식',body='예약 전 현장 담당자 확인이 필요합니다.',is_valid=True,reviewed_by=self.admin,reviewed_at=self.at)
        task=self.task();self.assertEqual([r['source_id'] for r in task.input_payload['knowledge']],[str(good.pk)])
        payload=FoundationFakeAdapter().execute_task(task,task.input_payload).payload;payload['facts'].append({'source_id':str(good.pk),'quote':'무료 혜택 확정'})
        valid=validate(task,payload);self.assertEqual(len(valid['facts']),1);self.assertGreater(valid['unverified_items'],0)
    def test_guide_draft_hidden_review_publish_read_only_no_extra_calls(self):
        result=self.success(self.task());staff=login(self.employee)
        self.assertFalse(staff.get(f'/api/sites/{self.site.pk}/published-guide').json()['available']);self.assertEqual(staff.get(f'/api/ai/results/{result.pk}').status_code,403)
        self.assertEqual(self.publish(result).json()['error']['code'],'GUIDE_REVIEW_REQUIRED')
        self.assertEqual(self.write(result).status_code,200);result.refresh_from_db();self.assertEqual(self.publish(result).status_code,200)
        data=staff.get(f'/api/sites/{self.site.pk}/published-guide').json();self.assertTrue(data['available']);self.assertTrue(data['is_test']);self.assertNotIn('payload',data);self.assertNotIn('価格',data['body']);self.assertNotIn(self.customer.customer_name,data['body']);self.assertEqual(AIUsageAttempt.objects.count(),1)
    def test_editing_or_generating_new_draft_keeps_previous_publication(self):
        result=self.success(self.task());self.assertEqual(self.write(result).status_code,200);result.refresh_from_db();self.assertEqual(self.publish(result).status_code,200);old=GuidePublication.objects.get().body
        self.write(result,body='다음 상담에서 확인할 질문을 준비하세요.',reviewed=False);self.assertEqual(GuidePublication.objects.get().body,old)
        self.success(self.task(at=self.now+timedelta(days=1)));self.assertEqual(GuidePublication.objects.get().body,old)
    def test_edit_optimistic_version_review_reset_and_idempotent_replay(self):
        result=self.success(self.task());key=str(uuid4());response=self.write(result,key=key);self.assertEqual(response.status_code,200);version=response.json()['version']
        self.assertEqual(self.write(result,key=key).json()['version'],version);self.assertEqual(self.write(result).status_code,409)
        result.refresh_from_db();self.assertEqual(self.publish(result).status_code,200);self.write(result,reviewed=False);result.refresh_from_db();self.assertEqual(self.publish(result).status_code,409)
        self.assertTrue(all('body' not in r.result for r in IdempotencyRecord.objects.filter(operation__startswith='AI_GUIDE')))
    def test_staff_or_initial_password_and_csrf_cannot_write_guides(self):
        result=self.success(self.task());staff=login(self.employee);url=f'/api/ai/guides/{result.pk}/publish'
        self.assertEqual(staff.post(url,{},content_type='application/json').status_code,403)
        protected=Client(enforce_csrf_checks=True);protected.cookies=self.client.cookies;self.assertEqual(protected.post('/api/ai/weekly-briefings',{},content_type='application/json').status_code,403)
        initial=user('01000000008',role='ADMIN');self.assertEqual(login(initial).get('/app/admin/ai').status_code,302)
    def test_private_or_unsupported_product_facts_block_publication_edit(self):
        result=self.success(self.task())
        for body in [self.customer.customer_name+' 상담', '01012345678 연락','무료 혜택 확정','방문은 2026년 12월 1일','https://example.invalid']:
            self.assertEqual(self.write(result,body).status_code,422)
    def test_knowledge_change_unpublishes_and_erases_snapshot_and_result(self):
        k=SiteKnowledge.objects.create(site=self.site,title='공식',body='예약은 담당자 확인 필요',is_valid=True,reviewed_by=self.admin,reviewed_at=self.at)
        result=self.success(self.task());self.assertEqual(self.write(result).status_code,200);result.refresh_from_db();self.assertEqual(self.publish(result).status_code,200)
        response=self.client.patch(f'/api/sites/{self.site.pk}/knowledge/{k.pk}',{'title':k.title,'body':'변경 자료','is_valid':True,'reviewed':True,'expected_version':1},content_type='application/json')
        self.assertEqual(response.status_code,200);result.refresh_from_db();self.assertFalse(result.valid);self.assertEqual(result.guide_body,'');self.assertEqual(result.request.report_snapshot.data,{});self.assertFalse(GuidePublication.objects.exists())
    def test_deletion_propagates_previous_coaching_and_excludes_future_inputs(self):
        first=self.success(self.task('EMPLOYEE_COACHING'));second=self.success(self.task('EMPLOYEE_COACHING',at=self.now+timedelta(days=1)))
        with business_write():invalidate_results([first.pk])
        second.refresh_from_db();self.assertFalse(second.valid);self.assertEqual(second.payload,{})
        task=self.task('EMPLOYEE_COACHING',at=self.now+timedelta(days=2));self.assertEqual(task.input_payload['previous_coaching'],[])
    def test_customer_hard_delete_removes_classification_and_mixed_guide_publication(self):
        result=self.success(self.task());self.assertEqual(self.write(result).status_code,200);result.refresh_from_db();self.assertEqual(self.publish(result).status_code,200)
        trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.customer.pk)],'idempotency_key':str(uuid4())});self.customer.refresh_from_db()
        hard_delete_customer(self.admin,self.customer.pk,{'confirm':True,'expected_version':self.customer.version,'idempotency_key':str(uuid4())})
        result.refresh_from_db();self.assertFalse(result.valid);self.assertFalse(GuidePublication.objects.exists());self.assertFalse(AINoteClassification.objects.exists());self.assertEqual(result.payload,{})
    def test_get_pages_lists_and_published_reads_do_not_generate(self):
        for path in ['/app/admin/ai','/app/guides','/api/ai/weekly-briefings',f'/api/ai/employees/{self.employee.pk}/coaching',f'/api/ai/sites/{self.site.pk}/guides',f'/api/sites/{self.site.pk}/published-guide']:
            self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(AIRequest.objects.count(),0);self.assertEqual(AIUsageAttempt.objects.count(),0)
    def test_admin_availability_and_safe_case_links_no_contact_urls(self):
        data=self.client.get('/api/ai/availability').json();self.assertTrue(data['generation_available']);self.assertIsNone(data['daily_limit'])
        result=self.success(self.task('EMPLOYEE_COACHING'));data=self.client.get(f'/api/ai/results/{result.pk}').json();self.assertIn(str(self.employee.pk),data['actors']);self.assertTrue(all(r['url'].startswith('/app/admin/ai/cases/') for r in data['case_links']))
        self.assertNotIn(self.customer.phone_normalized,json.dumps(data));self.assertEqual(login(self.employee).get(data['case_links'][0]['url']).status_code,403)
    def test_api_specific_routes_reject_untrusted_scope_and_staff(self):
        url=f'/api/ai/employees/{self.employee.pk}/coaching';body={'idempotency_key':str(uuid4())}
        self.assertEqual(login(self.employee).post(url,body,content_type='application/json').status_code,403)
        self.assertEqual(self.client.post(url,{**body,'prompt':'override'},content_type='application/json').status_code,422)
        self.assertEqual(self.client.post(url,body,content_type='application/json').status_code,202)
    def test_concurrent_admin_same_site_day_receives_one_shared_task(self):
        other=user('01000000006',role='ADMIN',initial=False);barrier=Barrier(2)
        def submit(uid):
            close_old_connections()
            try:
                actor=User.objects.get(pk=uid);barrier.wait(timeout=10);return self.task(actor=actor).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(submit,[self.admin.pk,other.pk]))
        self.assertEqual(ids[0],ids[1]);self.assertEqual(AIRequest.objects.count(),1);self.assertEqual(AIReportSlot.objects.count(),1)

    def test_record_review_hints_do_not_create_callback_or_change_customer(self):
        self.revision.notes='재콜 요청. 방문 취소';self.revision.after_values={'call_result':'VISIT_BOOKED','visit_at':'2026-11-08T10:00:00+09:00'};self.revision.save()
        result=self.success(self.task());checks=result.payload['record_checks'];self.assertEqual(len(checks),2);self.assertTrue(all('확인 필요' in r['message'] for r in checks));self.assertEqual(Callback.objects.count(),0);self.customer.refresh_from_db();self.assertEqual(self.customer.version,1)
    def test_guide_uses_general_questions_from_reaction_without_publishing_customer_content(self):
        result=self.success(self.task());self.assertIn('비용의 어떤 항목',result.guide_body);self.assertNotIn('가격 비교 후 나중에 연락 요청',result.guide_body)
        task=result.request
        # Generated body remains a draft. Only validated closed questions and reviewed facts enter it.
        self.assertFalse(GuidePublication.objects.exists())
    def test_coaching_and_guide_bad_scope_or_disabled_actor_revokes_results(self):
        result=self.success(self.task('EMPLOYEE_COACHING'));staff=login(self.employee)
        self.assertEqual(staff.get(f'/api/ai/results/{result.pk}').status_code,403)
        self.admin.is_active=False;self.admin.save();self.assertEqual(self.client.get(f'/api/ai/results/{result.pk}').status_code,401)
    def test_guides_current_review_version_constraint_in_real_postgresql(self):
        from django.db import IntegrityError,transaction
        result=self.success(self.task())
        with self.assertRaises(IntegrityError),transaction.atomic():AIResult.objects.filter(pk=result.pk).update(guide_version=0)
        with self.assertRaises(IntegrityError),transaction.atomic():AIResult.objects.filter(pk=result.pk).update(guide_reviewed_version=1)
    def test_operations_actual_actor_time_and_full_totals_in_snapshot(self):
        OperationEvent.objects.create(actor=self.admin,operation='DISTRIBUTE',occurred_at=self.at,affected_count=7)
        sunday=self.now+timedelta(days=(6-self.now.astimezone(KST).weekday())%7)
        task=self.task('WEEKLY_BRIEFING',at=sunday);stats=task.report_snapshot.data['statistics'];row=next(r for r in stats['operations'] if r['operation']=='DISTRIBUTE')
        self.assertEqual(row['affected'],7);self.assertEqual(row['actor_id'],str(self.admin.pk));self.assertEqual(stats['operation_events'][0]['occurred_at'],self.at.isoformat())
    def test_publish_same_key_replay_keeps_one_operation_and_no_body_receipt(self):
        result=self.success(self.task());self.assertEqual(self.write(result).status_code,200);result.refresh_from_db();body={'expected_version':result.guide_version,'idempotency_key':str(uuid4())};url=f'/api/ai/guides/{result.pk}/publish'
        first=self.client.post(url,body,content_type='application/json');second=self.client.post(url,body,content_type='application/json');self.assertEqual(first.status_code,200);self.assertEqual(first.json(),second.json());self.assertEqual(OperationEvent.objects.filter(operation='AI_GUIDE_PUBLISH').count(),1);self.assertNotIn('body',first.json())

    def test_schema_oversized_and_non_json_output_is_rejected(self):
        task=self.task('EMPLOYEE_COACHING');base=FoundationFakeAdapter().execute_task(task,task.input_payload).payload
        oversized={**base,'actions':base['actions']*96};self.assertIsNone(validate(task,oversized));self.assertIsNone(validate(task,{**base,'unexpected':object()}))
    def test_invalidated_success_slot_is_not_recharged_same_day(self):
        result=self.success(self.task())
        with business_write():invalidate_results([result.pk])
        again=self.task();self.assertEqual(again.pk,result.request_id);self.assertEqual(AIRequest.objects.count(),1);self.assertEqual(AIUsageAttempt.objects.count(),1)
    def test_prior_fingerprints_do_not_mix_models_and_guide_text_has_no_individual_notes(self):
        result=self.success(self.task());self.assertNotIn(self.customer.customer_name,result.guide_body);self.assertNotIn(str(self.revision.pk),result.guide_body)
        cached=AINoteClassification.objects.get();cached.fingerprint='0'*64;cached.save();task=self.task(at=self.now+timedelta(days=1));self.assertEqual(task.report_snapshot.data['sampling']['cached_groups'],0)
