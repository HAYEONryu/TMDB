import io
import json
import os
from pathlib import Path
import runpy
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from apps.consultations.models import ConsultationRevision
from apps.customers.services import update_row
from tests.helpers import TEST_HASHERS,login
from tests.test_p4 import Fixtures


class WebMemorySettingsTests(SimpleTestCase):
    def config(self,**values):
        env={k:v for k,v in os.environ.items() if not k.startswith('TM_WEB_')}
        with patch.dict(os.environ,{**env,**values},clear=True):
            return runpy.run_path(str(settings.BASE_DIR/'config/gunicorn.py'))

    def test_defaults_and_optional_small_server_settings(self):
        config=self.config()
        self.assertEqual((config['workers'],config['threads'],config['max_requests']),(2,4,0))
        self.assertTrue(config['control_socket_disable'])
        config=self.config(TM_WEB_WORKERS='1',TM_WEB_THREADS='4',TM_WEB_MAX_REQUESTS='1000')
        self.assertEqual((config['workers'],config['threads'],config['max_requests_jitter']),(1,4,50))

    def test_invalid_settings_are_rejected_without_echoing_values(self):
        for name,value in [('TM_WEB_WORKERS','0'),('TM_WEB_THREADS','99'),('TM_WEB_WORKERS','private-marker'),('TM_WEB_MAX_REQUESTS','-1')]:
            with self.assertRaises(ValueError) as error:self.config(**{name:value})
            self.assertNotIn(value,str(error.exception))


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DatabaseOptimizationTests(Fixtures,TransactionTestCase):
    def setUp(self):
        self.prepare();self.customer=self.customers()[0];self.assign(self.customer)
        self.customer.notes='보존할 가상 상담 원문';self.customer.memo='기존 일반 비고';self.customer.admin_notes='SYNTHETIC_PRIVATE_MEMO'
        self.customer.save()
        self.client=login(self.employee);self.headers={'HTTP_X_TM_QUEUE_USER':str(self.employee.pk)}

    def test_new_revisions_keep_changed_values_and_report_fields_without_unchanged_long_text(self):
        body=self.mutation(self.customer)|{'changes':{'call_result':'INTERESTED'}}
        self.assertTrue(update_row(self.employee,body)['ok'])
        revision=ConsultationRevision.objects.get(customer=self.customer)
        self.assertEqual(revision.before_values['call_result'],None)
        self.assertEqual(revision.after_values['call_result'],'INTERESTED')
        self.assertIn('contract_status',revision.after_values)
        self.assertEqual(revision.notes,self.customer.notes)
        for field in ['notes','memo','admin_notes']:
            self.assertNotIn(field,revision.before_values);self.assertNotIn(field,revision.after_values)
        self.customer.refresh_from_db()
        self.assertTrue(update_row(self.employee,self.mutation(self.customer)|{'changes':{'notes':'가상 새 상담'}})['ok'])
        revision=ConsultationRevision.objects.order_by('-customer_version').first()
        self.assertEqual(revision.before_values['notes'],'보존할 가상 상담 원문')
        self.assertEqual(revision.after_values['notes'],'가상 새 상담')
        self.assertEqual(revision.notes,'가상 새 상담')

    def test_name_only_audit_keeps_name_before_after_and_customer_original_notes(self):
        old_name=self.customer.customer_name
        self.assertTrue(update_row(self.employee,self.mutation(self.customer)|{'changes':{'customer_name':'가상 정정'}})['ok'])
        revision=ConsultationRevision.objects.get(customer=self.customer)
        self.assertEqual((revision.before_values['customer_name'],revision.after_values['customer_name']),(old_name,'가상 정정'))
        self.assertEqual(revision.notes,'')
        self.customer.refresh_from_db();self.assertEqual(self.customer.notes,'보존할 가상 상담 원문')

    def test_sql_projection_supports_legacy_full_snapshots_and_empty_baseline_fields(self):
        for version,fields in [(1,['call_result']),(2,[])]:
            ConsultationRevision.objects.create(customer=self.customer,actor=self.employee,customer_version=version,
                source='MANUAL' if fields else 'BASELINE',changed_fields=fields,notes=self.customer.notes,
                before_values={'call_result':None,'notes':self.customer.notes,'admin_notes':self.customer.admin_notes},
                after_values={'call_result':'INTERESTED','notes':self.customer.notes,'admin_notes':self.customer.admin_notes})
        with CaptureQueriesContext(connection) as queries:
            response=self.client.get(f'/api/customers/{self.customer.pk}/history',{'kind':'consultations','assignment_id':str(self.customer.current_assignment_id)},**self.headers)
        self.assertEqual(response.status_code,200)
        rows=response.json()['data'];self.assertEqual(set(rows[1]['after_values']),{'call_result'})
        self.assertEqual(rows[0]['after_values']['notes'],self.customer.notes)
        self.assertNotIn('SYNTHETIC_PRIVATE_MEMO',response.content.decode())
        self.assertTrue(any('jsonb_each' in row['sql'] for row in queries))
        self.assertLess(len(queries),15)

    def test_employee_grid_does_not_fetch_private_memo_or_full_user_record(self):
        with CaptureQueriesContext(connection) as queries:
            response=self.client.get('/api/customers',{'site_id':str(self.site.pk)},**self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['total'],1)
        selected=[q['sql'] for q in queries if '"customers_customer"' in q['sql'] and 'LIMIT 50' in q['sql']]
        self.assertEqual(len(selected),1)
        self.assertNotIn('"admin_notes"',selected[0]);self.assertNotIn('"password"',selected[0])
        self.assertNotIn('SYNTHETIC_PRIVATE_MEMO',response.content.decode())

    def test_database_usage_is_read_only_aggregate_without_customer_or_credentials(self):
        output=io.StringIO();call_command('database_usage',stdout=output)
        data=json.loads(output.getvalue());self.assertTrue(data['read_only'])
        self.assertTrue(data['row_counts_are_estimates']);self.assertGreater(data['database_bytes'],0)
        for forbidden in [self.customer.phone_normalized,self.customer.notes,self.customer.admin_notes,settings.SECRET_KEY]:
            self.assertNotIn(forbidden,output.getvalue())
        self.assertIn('autovacuum',data['settings'])
