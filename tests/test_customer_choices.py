"""Fixed business selections, legacy preservation and fake AI schemas."""
from io import StringIO
from uuid import uuid4

from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from apps.customers.choices import CURRENT_CHOICES, customer_schema
from apps.customers.models import Customer, CustomerDeletionRequest
from apps.customers.services import update_row
from apps.imports.excel import HEADERS, OLD_HEADERS
from apps.imports.services import validate_upload, commit_upload
from tests.helpers import TEST_HASHERS
from tests.test_imports import workbook, uploaded
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerChoiceTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare();self.customer=Customer.objects.create(site=self.site,phone_normalized='01094000001')
        self.assign(self.customer)

    def save(self, field, value, actor=None):
        self.customer.refresh_from_db()
        return update_row(actor or self.admin,dict(customer_id=str(self.customer.pk),assignment_id=str(self.customer.current_assignment_id),
            expected_version=self.customer.version,mutation_id=str(uuid4()),changes={field:value}))

    def test_exact_current_options_and_all_choices_save_for_both_roles(self):
        expected={
            'contract_status':['청약','청약해지','계약해지','계약'],
            'route':['티엠','사이드','대표콜','개인관리','워킹','재방'],
            'housing_status':['무주택','1주택','다주택','생애최초'],
            'call_result':['가망고객','삭제 요망','거절','다음현장 연락 요청','부재']}
        for field, labels in expected.items():
            self.assertEqual(list(customer_schema()[field].values()),['-',*labels])
            for actor in [self.admin,self.employee]:
                for value in CURRENT_CHOICES[field]:self.assertTrue(self.save(field,value,actor)['ok'])
        self.assertFalse(CustomerDeletionRequest.objects.exists())
        self.customer.refresh_from_db();self.assertIsNone(self.customer.deleted_at)

    def test_unknown_choices_rejected_and_legacy_unchanged_preserved(self):
        for field,value in [('route','소개'),('housing_status','자가'),('call_result','CALL_AGAIN'),('contract_status','NO_CONTRACT'),('route',42),('contract_status',0)]:
            self.assertEqual(self.save(field,value)['error']['code'],'VALIDATION_ERROR')
        Customer.objects.filter(pk=self.customer.pk).update(route='소개',housing_status='전세',call_result='CALL_AGAIN',contract_status='NO_CONTRACT')
        for field,value in [('route','소개'),('housing_status','전세'),('call_result','CALL_AGAIN'),('contract_status','NO_CONTRACT')]:
            self.assertTrue(self.save(field,value)['ok'])
        self.assertTrue(self.save('notes','기존값 보존 상담')['ok'])
        self.assertTrue(self.save('housing_status','무주택')['ok'])
        self.assertEqual(self.save('housing_status','전세')['error']['code'],'VALIDATION_ERROR')

    def test_excel_current_and_previous_headers_validate_current_choices_only(self):
        for headers in [HEADERS,OLD_HEADERS]:
            batch=validate_upload(self.admin,self.site.pk,uploaded(workbook([
                ['가상 신규','01094000002','','무주택','',''],['가상 이전','01094000003','','전세','','']],headers=headers)))
            self.assertEqual(batch.validation_summary['ready'],1);self.assertEqual(batch.validation_summary['invalid'],1)

    def test_old_validated_candidate_is_rechecked_before_commit(self):
        batch=validate_upload(self.admin,self.site.pk,uploaded(workbook([['가상 신규','01094000002','','무주택','','']],headers=HEADERS)))
        candidate=batch.candidates.get();candidate.normalized_values['housing_status']='전세';candidate.save()
        result,_=commit_upload(self.admin,batch.pk,dict(site_id=str(self.site.pk),idempotency_key=str(uuid4())))
        self.assertEqual(result['success_count'],0)
        self.assertEqual(batch.row_results.get().error_code,'INVALID_ROW')

    def test_model_migration_matches_current_fields(self):
        call_command('makemigrations','customers',dry_run=True,check=True,stdout=StringIO())

    def test_route_select_filter_is_exact_and_keeps_legacy_contains_api(self):
        from apps.customers.queries import customer_list, filter_options
        Customer.objects.filter(pk=self.customer.pk).update(route='티엠')
        old=Customer.objects.create(site=self.site,phone_normalized='01094000002',route='티엠 소개')
        self.assign(old)
        foreign=Customer.objects.create(site=self.site,phone_normalized='01094000003',route='다른직원 이전값')
        self.assign(foreign,self.other)
        import json
        params={'site_id':str(self.site.pk),'filters':json.dumps({'route':{'values':['티엠'],'exclude':False}})}
        self.assertEqual(customer_list(self.employee,params)['total'],1)
        self.assertEqual(customer_list(self.admin,{**params,'filters':json.dumps({'route':{'contains':'티엠'}})})['total'],2)
        options=filter_options(self.employee,{'site_id':str(self.site.pk),'field':'route'})
        self.assertCountEqual(options['values'],['티엠','티엠 소개'])


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerChoiceMigrationTests(Fixtures, TransactionTestCase):
    def test_upgrade_preserves_previous_values_and_accepts_long_new_codes(self):
        self.prepare();latest=[('customers','0004_customer_selection_options')]
        try:
            MigrationExecutor(connection).migrate([('customers','0003_live_phone_unique')])
            old=MigrationExecutor(connection).loader.project_state([('customers','0003_live_phone_unique')]).apps.get_model('customers','Customer')
            previous=old.objects.create(site_id=self.site.pk,phone_normalized='01094000001',call_result='VISIT_BOOKED',contract_status='NO_CONTRACT',route='기존 자유문자',housing_status='전세',notes='가상 상담 보존')
            MigrationExecutor(connection).migrate(latest)
            current=Customer.objects.get(pk=previous.pk)
            self.assertEqual((current.call_result,current.contract_status,current.route,current.housing_status,current.notes),('VISIT_BOOKED','NO_CONTRACT','기존 자유문자','전세','가상 상담 보존'))
            current.call_result='DELETE_REQUEST';current.contract_status='CONTRACT_CANCELLED';current.save()
            current.refresh_from_db();self.assertEqual(current.contract_status,'CONTRACT_CANCELLED')
        finally:MigrationExecutor(connection).migrate(latest)
