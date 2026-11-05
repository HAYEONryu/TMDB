import json,io,time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier,Event
from unittest.mock import patch
from uuid import uuid4
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import close_old_connections
from django.test import TransactionTestCase,override_settings,Client
from django.utils import timezone
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.accounts.services import set_user_access
from apps.assignments.models import Assignment
from apps.assignments.services import change_assignee
from apps.callbacks.models import Callback
from apps.common.transactions import business_write
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer,CustomerDeletionRequest,CustomerChangeEvent
from apps.customers.services import update_row,trash_operation
from apps.customers.deletions import submit,approve,hard_delete_customer,hard_delete_site,confirm_site
from apps.imports.models import ImportBatch,ImportCandidate,ImportRowResult
from apps.imports.services import commit_upload
from apps.operations.models import MutationReceipt,IdempotencyRecord,OperationEvent,ScheduledJobRun
from apps.sites.models import Site,GlobalSettings,DefaultSiteHistory
from tests.helpers import TEST_HASHERS,login,user,STRONG_PASSWORD
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class P7Tests(Fixtures,TransactionTestCase):
    def setUp(self):self.prepare();self.customer=self.customers()[0];self.assignment=self.assign(self.customer)
    def request_body(self,customer=None,**values):
        c=customer or self.customer
        return {'assignment_id':str(c.current_assignment_id),'expected_version':c.version,'idempotency_key':str(uuid4()),**values}
    def request(self,**kwargs):return submit(self.employee,self.customer.pk,self.request_body(**kwargs))[0]
    def approve(self,rid=None,actor=None,**kwargs):return approve(actor or self.admin,rid or self.request()['request_id'],{'idempotency_key':str(uuid4()),**kwargs})
    def trash(self,restore=False):return trash_operation(self.admin,{'site_id':str(self.site.pk),'customer_ids':[str(self.customer.pk)],'idempotency_key':str(uuid4())},restore=restore)
    def hard_body(self):self.customer.refresh_from_db();return {'expected_version':self.customer.version,'confirm':True,'idempotency_key':str(uuid4())}
    def site_body(self,site=None,actor=None):
        s=site or self.site;key=str(uuid4());proof=confirm_site(actor or self.admin,s.pk,{'confirm_name':s.name,'idempotency_key':key});return {'confirmation':proof['confirmation'],'idempotency_key':key}

    def test_request_is_metadata_only_duplicate_keys_and_current_owner_pending(self):
        before=self.customer.version;body=self.request_body();one,status=submit(self.employee,self.customer.pk,body);two,_=submit(self.employee,self.customer.pk,{**body,'idempotency_key':str(uuid4())})
        self.assertEqual(one,two);self.assertEqual(status,200);self.customer.refresh_from_db();self.assignment.refresh_from_db();self.assertEqual(self.customer.version,before);self.assertIsNone(self.customer.deleted_at);self.assertIsNone(self.assignment.first_activity_at)
        self.assertEqual((CustomerDeletionRequest.objects.count(),ConsultationRevision.objects.count()),(1,0));self.assertEqual(OperationEvent.objects.filter(operation='DELETION_REQUEST').count(),1)
        change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.other));self.customer.refresh_from_db();three,_=submit(self.other,self.customer.pk,self.request_body());self.assertEqual(three['request_id'],one['request_id'])
        self.assertEqual(CustomerDeletionRequest.objects.get().requested_by,self.employee)

    def test_request_authentication_structure_assignment_and_version(self):
        for actor,body,code in [(self.other,self.request_body(),'FORBIDDEN'),(self.employee,self.request_body(assignment_id=str(uuid4())),'FORBIDDEN'),(self.employee,self.request_body(expected_version=99),'VERSION_CONFLICT'),(self.employee,{**self.request_body(),'customer_ids':[str(self.customer.pk)]},'VALIDATION_ERROR')]:
            with self.assertRaises(AccessError) as error:submit(actor,self.customer.pk,body)
            self.assertEqual(error.exception.code,code)
        self.assertFalse(CustomerDeletionRequest.objects.exists())

    def test_approval_latest_notes_long_notes_empty_and_no_staff_progress(self):
        for index,value in enumerate(['', '가'*10000],1):
            customer=self.customer;request=self.request();mutation=self.mutation(customer);mutation['changes']={'notes':value};update_row(self.employee,mutation)
            request_id=request['request_id'];result,_=self.approve(request_id);customer.refresh_from_db();deletion=CustomerDeletionRequest.objects.get(pk=request_id)
            note=f"[{timezone.localtime(deletion.approved_at):%Y-%m-%d %H:%M}] 고객요청으로 인한 삭제"
            self.assertEqual(customer.notes,value+('\n' if value else '')+note);self.assertEqual(customer.deleted_at,deletion.approved_at);self.assertEqual(result['approved_by'],str(self.admin.pk))
            self.assertEqual(ConsultationRevision.objects.filter(source='SYSTEM_DELETE_NOTE',customer=customer).count(),index)
            self.assignment.refresh_from_db()
            if not value:self.assertIsNone(self.assignment.first_activity_at)
            self.trash(restore=True);customer.refresh_from_db();self.assignment=self.assign(customer)
            if not value:Customer.objects.filter(pk=customer.pk).update(notes='');customer.refresh_from_db()

    def test_two_admins_replay_preserves_first_approval_and_restore_is_not_redeleted(self):
        rid=self.request()['request_id'];body={'idempotency_key':str(uuid4())};first,_=approve(self.admin,rid,body)
        second_admin=user('01000000004',role='ADMIN',initial=False);second,_=approve(second_admin,rid,{'idempotency_key':str(uuid4())});self.assertEqual(first,second)
        self.trash(restore=True);again,_=approve(self.admin,rid,body);self.customer.refresh_from_db();self.assertEqual(first,again);self.assertIsNone(self.customer.deleted_at)
        self.assign(self.customer);new=self.request();self.assertNotEqual(new['request_id'],rid);self.assertEqual(self.customer.notes.count('고객요청으로 인한 삭제'),1)

    def test_request_survives_recall_reassignment_and_inactive_requester(self):
        rid=self.request()['request_id'];change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer,self.other))
        set_user_access(self.admin,self.employee.pk,is_active=False)
        result,_=self.approve(rid);self.assertEqual(result['status'],'APPROVED');self.customer.refresh_from_db();self.assertIsNotNone(self.customer.deleted_at)

    def test_general_trash_closes_pending_without_approval_note(self):
        rid=self.request()['request_id'];self.trash();request=CustomerDeletionRequest.objects.get(pk=rid);self.assertEqual((request.status,request.close_reason),('CLOSED','ALREADY_DELETED'))
        with self.assertRaises(AccessError) as error:self.approve(rid)
        self.assertEqual(error.exception.code,'DELETION_REQUEST_CLOSED');self.customer.refresh_from_db();self.assertEqual(self.customer.notes,'')

    def test_approval_failure_rolls_back_all_domain_changes(self):
        rid=self.request()['request_id']
        with patch('apps.customers.deletions.ConsultationRevision.objects.create',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.approve(rid)
        self.customer.refresh_from_db();self.assignment.refresh_from_db();self.assertIsNone(self.customer.deleted_at);self.assertIsNone(self.assignment.ended_at);self.assertEqual(CustomerDeletionRequest.objects.get().status,'PENDING');self.assertEqual(self.customer.notes,'')

    def test_global_notifications_pagination_and_read_does_not_approve(self):
        self.request();others=self.customers(51,site=self.second,offset=10)
        for c in others:self.assign(c);submit(self.employee,c.pk,self.request_body(c))
        client=login(self.admin);first=client.get('/api/deletion-requests').json();second=client.get('/api/deletion-requests',{'page':2}).json();self.assertEqual((first['total'],len(first['items']),len(second['items'])),(52,50,2))
        self.assertEqual(CustomerDeletionRequest.objects.filter(status='PENDING').count(),52);self.assertEqual(client.get('/api/deletion-requests',{'site_id':self.site.pk}).status_code,422)
        self.assertEqual(login(self.employee).get('/api/deletion-requests').status_code,403)

    def test_http_identity_and_csrf_reject_invalid_submissions(self):
        path=f'/api/customers/{self.customer.pk}/deletion-request';body=self.request_body();client=login(self.employee)
        self.assertEqual(client.post(path,body,content_type='application/json').status_code,403)
        self.assertEqual(client.post(path,body,content_type='application/json',HTTP_X_TM_QUEUE_USER=str(self.other.pk)).status_code,403)
        self.assertEqual(client.post(path,body,content_type='application/json',HTTP_X_TM_QUEUE_USER=str(self.employee.pk)).status_code,200)
        csrf=Client(enforce_csrf_checks=True);csrf.get('/auth/login');token=csrf.cookies['csrftoken'].value
        self.assertEqual(csrf.post('/auth/login',{'phone':self.admin.phone_normalized,'password':STRONG_PASSWORD},content_type='application/json',HTTP_X_CSRFTOKEN=token).status_code,200)
        self.assertEqual(csrf.post(f'/api/deletion-requests/{CustomerDeletionRequest.objects.get().pk}/approve',{'idempotency_key':str(uuid4())},content_type='application/json').status_code,403)

    def test_hard_customer_deletes_all_history_receipts_and_allows_new_uuid(self):
        Callback.objects.create(customer=self.customer,due_at=timezone.now(),created_by=self.employee,updated_by=self.employee)
        update_row(self.employee,self.mutation(self.customer,'가상 원문 제거'));self.customer.refresh_from_db();self.approve();self.customer.refresh_from_db();old=self.customer.pk;phone=self.customer.phone_normalized;body=self.hard_body()
        other=Customer.objects.create(site=self.second,customer_name='다른 현장 보존',phone_normalized=phone)
        first,_=hard_delete_customer(self.admin,old,body);again,_=hard_delete_customer(self.admin,old,body);self.assertEqual(first,again)
        for model in [CustomerDeletionRequest,ConsultationRevision,CustomerChangeEvent,MutationReceipt,Assignment,Callback]:self.assertFalse(model.objects.exists(),model)
        self.assertTrue(Customer.objects.filter(pk=other.pk).exists());new=Customer.objects.create(site=self.site,customer_name='가상 재등록',phone_normalized=phone);self.assertNotEqual(old,new.pk)
        receipt=IdempotencyRecord.objects.get(operation='CUSTOMER_HARD_DELETE');self.assertEqual(receipt.target_ids,[]);self.assertNotIn(str(old),json.dumps(receipt.result));self.assertNotIn('가상 원문',json.dumps(receipt.result))

    def test_active_customer_hard_delete_and_version_conflict_rejected(self):
        with self.assertRaises(AccessError) as error:hard_delete_customer(self.admin,self.customer.pk,self.hard_body())
        self.assertEqual(error.exception.code,'FORBIDDEN');self.trash();body=self.hard_body();body['expected_version']+=1
        with self.assertRaises(AccessError) as error:hard_delete_customer(self.admin,self.customer.pk,body)
        self.assertEqual(error.exception.code,'VERSION_CONFLICT');self.assertTrue(Customer.objects.exists())

    def test_scrub_validated_upload_keeps_other_rows_and_cannot_resurrect_deleted_input(self):
        self.trash();now=timezone.now();batch=ImportBatch.objects.create(site=self.site,created_by=self.admin,expires_at=now+timedelta(hours=1),total_count=2,failure_count=0,validation_summary={'total':2,'ready':2,'duplicate_in_file':0,'duplicate_existing':0,'invalid':0})
        for number,phone,name in [(2,self.customer.phone_normalized,self.customer.customer_name),(3,'01080009999','다른 가상 입력')]:
            values={'customer_name':name,'phone_normalized':phone,'call_result':None,'contract_status':'UNKNOWN','notes':'가상 업로드 원문','housing_status':'','visit_at':None,'callback_due_at':None}
            ImportCandidate.objects.create(batch=batch,row_number=number,normalized_values=values);ImportRowResult.objects.create(batch=batch,row_number=number,success=True,customer_name=name,phone_input=phone[:3]+'-'+phone[3:7]+'-'+phone[7:])
        hard_delete_customer(self.admin,self.customer.pk,self.hard_body());removed=ImportRowResult.objects.get(batch=batch,row_number=2);self.assertEqual((removed.customer_name,removed.phone_input,removed.error_code),('','','SOURCE_DELETED'));self.assertEqual(ImportCandidate.objects.filter(batch=batch).count(),1)
        result,status=commit_upload(self.admin,batch.pk,{'site_id':str(self.site.pk),'idempotency_key':str(uuid4())});self.assertEqual(status,200);self.assertEqual(result['success_count'],1);self.assertFalse(Customer.objects.filter(site=self.site,phone_normalized=self.customer.phone_normalized).exists());self.assertTrue(Customer.objects.filter(phone_normalized='01080009999').exists())

    def test_site_deletion_default_fallback_then_none_and_original_name_not_in_receipt(self):
        self.request();body=self.site_body();name=self.site.name;sid=self.site.pk;first,_=hard_delete_site(self.admin,sid,body);self.assertEqual(first['affected_count'],1);self.assertEqual(hard_delete_site(self.admin,sid,body)[0],first)
        self.assertEqual(GlobalSettings.objects.get().default_site_id,self.second.pk);self.assertFalse(CustomerDeletionRequest.objects.exists());self.assertFalse(Customer.objects.exists())
        receipt=IdempotencyRecord.objects.get(operation='SITE_HARD_DELETE');self.assertNotIn(name,json.dumps(receipt.result));self.assertEqual(receipt.target_ids,[]);self.assertTrue(DefaultSiteHistory.objects.filter(previous_site_id_snapshot=sid).exists())
        hard_delete_site(self.admin,self.second.pk,self.site_body(self.second));self.assertIsNone(GlobalSettings.objects.get().default_site_id);self.assertFalse(Site.objects.exists())

    def test_site_exact_confirmation_bound_to_actor_key_and_expiry(self):
        with self.assertRaises(AccessError):confirm_site(self.admin,self.site.pk,{'confirm_name':self.site.name+' ','idempotency_key':str(uuid4())})
        body=self.site_body();another=user('01000000004',role='ADMIN',initial=False)
        with self.assertRaises(AccessError):hard_delete_site(another,self.site.pk,body)
        with patch('django.core.signing.time.time',return_value=time.time()+8*86400):
            with self.assertRaises(AccessError):hard_delete_site(self.admin,self.site.pk,body)
        self.assertTrue(Site.objects.filter(pk=self.site.pk).exists())

    def test_ai_privacy_guard_blocks_new_unhandled_model_atomically(self):
        self.trash()
        with patch('apps.ai_assistant.privacy.apps.get_app_config') as config:
            config.return_value.get_models.return_value=[object()]
            with self.assertRaises(ImproperlyConfigured):hard_delete_customer(self.admin,self.customer.pk,self.hard_body())
        self.assertTrue(Customer.objects.filter(pk=self.customer.pk).exists())

    def test_committed_upload_and_untagged_legacy_receipt_are_scrubbed(self):
        batch=ImportBatch.objects.create(site=self.site,created_by=self.admin,status='COMMITTED',expires_at=timezone.now()+timedelta(hours=1),total_count=1,success_count=1)
        ImportRowResult.objects.create(batch=batch,row_number=2,success=True,customer_name=self.customer.customer_name,phone_input=self.customer.phone_normalized)
        IdempotencyRecord.objects.create(actor=self.admin,operation='LEGACY',key=uuid4(),body_hash='x'*64,target_ids=[],result={'row':{'id':str(self.customer.pk),'notes':'가상 이전 원문'}},expires_at=timezone.now()+timedelta(days=1))
        self.trash();hard_delete_customer(self.admin,self.customer.pk,self.hard_body());row=ImportRowResult.objects.get();batch.refresh_from_db();self.assertEqual((row.customer_name,row.phone_input,row.success),('','',True));self.assertEqual(batch.success_count,1);self.assertFalse(IdempotencyRecord.objects.filter(operation='LEGACY').exists())

    def test_approval_after_recall_without_current_assignment(self):
        rid=self.request()['request_id'];change_assignee(self.admin,self.customer.pk,self.assignee_body(self.customer));result,_=self.approve(rid);self.assertEqual(result['status'],'APPROVED');self.assertIsNone(ConsultationRevision.objects.get().assignment_id)

    def test_site_deletion_removes_import_sources_and_preserves_other_site_and_job_snapshot(self):
        other=Customer.objects.create(site=self.second,customer_name='다른 현장 고객',phone_normalized=self.customer.phone_normalized)
        for site in [self.site,self.second]:
            batch=ImportBatch.objects.create(site=site,created_by=self.admin,expires_at=timezone.now()+timedelta(hours=1))
            ImportCandidate.objects.create(batch=batch,row_number=2,normalized_values={'phone_normalized':self.customer.phone_normalized,'notes':'가상 입력'})
            ImportRowResult.objects.create(batch=batch,row_number=2,customer_name='가상 입력',phone_input=self.customer.phone_normalized)
        job=ScheduledJobRun.objects.create(job_type='AUTO_RECALL',business_date=timezone.localdate(),cutoff=timezone.now(),target_site=self.site,target_site_id_snapshot=self.site.pk,status='COMPLETED')
        hard_delete_site(self.admin,self.site.pk,self.site_body());self.assertEqual(ImportBatch.objects.count(),1);self.assertEqual(ImportCandidate.objects.count(),1);self.assertTrue(Customer.objects.filter(pk=other.pk).exists());job.refresh_from_db();self.assertIsNone(job.target_site_id);self.assertEqual(job.target_site_id_snapshot,self.site.pk)

    def test_concurrent_approvals_one_note_one_event(self):
        rid=self.request()['request_id'];other=user('01000000004',role='ADMIN',initial=False);barrier=Barrier(2)
        def run(actor):
            close_old_connections()
            try:barrier.wait(timeout=5);return self.approve(rid,actor)[0]
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=[f.result(timeout=15) for f in [pool.submit(run,self.admin),pool.submit(run,other)]]
        self.assertEqual(results[0],results[1]);self.customer.refresh_from_db();self.assertEqual(self.customer.notes.count('고객요청으로 인한 삭제'),1);self.assertEqual(OperationEvent.objects.filter(operation='DELETION_APPROVE').count(),1)

    def ordered(self,first,second):
        held,release=Event(),Event()
        def a():
            close_old_connections()
            try:
                with business_write():result=first();held.set();assert release.wait(10);return result
            finally:close_old_connections()
        def b():
            close_old_connections()
            try:return second()
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:one=pool.submit(a);self.assertTrue(held.wait(10));two=pool.submit(b);release.set();return one.result(timeout=15),two.result(timeout=15)

    def test_save_before_approval_uses_latest_note_and_approval_before_save_rejects(self):
        rid=self.request()['request_id'];late_body=self.mutation(self.customer,'거부');self.ordered(lambda:update_row(self.employee,self.mutation(self.customer,'최신 가상 상담')),lambda:self.approve(rid));self.customer.refresh_from_db();self.assertTrue(self.customer.notes.startswith('최신 가상 상담\n'))
        with self.assertRaises(AccessError) as error:update_row(self.employee,late_body)
        self.assertEqual(error.exception.code,'CUSTOMER_DELETED')

    def test_approval_commits_before_waiting_save(self):
        rid=self.request()['request_id'];body=self.mutation(self.customer,'뒤늦은 가상 저장')
        def late():
            try:update_row(self.employee,body);return 'UNEXPECTED'
            except AccessError as error:return error.code
        _,code=self.ordered(lambda:self.approve(rid),late);self.assertEqual(code,'CUSTOMER_DELETED');self.customer.refresh_from_db();self.assertNotIn('뒤늦은',self.customer.notes)
