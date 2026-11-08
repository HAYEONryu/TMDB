from scripts.verification_evidence import artifact_path
import json,time,resource,sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from apps.assignments.models import Assignment
from apps.callbacks.models import Callback
from apps.common.transactions import business_write
from apps.customers.models import Customer,CustomerDeletionRequest
from apps.customers.deletions import hard_delete_site,confirm_site
from apps.operations.models import IdempotencyRecord
from tests.helpers import TEST_HASHERS
from tests.test_p4 import Fixtures
from uuid import uuid4


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DeletionPerformanceTests(Fixtures,TransactionTestCase):
    def test_10000_site_deletion_actual_postgresql(self):
        self.prepare();rows=self.customers(10000);assignments=[Assignment(customer=c,employee=self.employee,assigned_by=self.admin,assigned_at=timezone.now()) for c in rows];Assignment.objects.bulk_create(assignments,batch_size=500)
        for c,a in zip(rows,assignments):c.current_assignment=a
        Customer.objects.bulk_update(rows,['current_assignment'],batch_size=500)
        Callback.objects.bulk_create([Callback(customer=c,due_at=timezone.now(),created_by=self.employee,updated_by=self.employee) for c in rows[:100]],batch_size=500)
        CustomerDeletionRequest.objects.bulk_create([CustomerDeletionRequest(customer=c,requested_by=self.employee,requested_assignment=a,requested_at=timezone.now()) for c,a in zip(rows[:100],assignments[:100])],batch_size=500)
        key=str(uuid4());proof=confirm_site(self.admin,self.site.pk,{'confirm_name':self.site.name,'idempotency_key':key});holds=[]
        @contextmanager
        def measured():
            with business_write():
                started=time.monotonic()
                try:yield
                finally:holds.append(time.monotonic()-started)
        started=time.monotonic()
        with patch('apps.customers.deletions.business_write',measured):result,status=hard_delete_site(self.admin,self.site.pk,{'idempotency_key':key,**proof})
        elapsed=time.monotonic()-started;peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=='darwin' else 1024)
        report={'rows':10000,'site_delete_seconds':round(elapsed,3),'business_lock_hold_seconds':[round(value,3) for value in holds],'peak_process_rss_mib':round(peak,2),'criteria':{'max_seconds':30,'max_lock_seconds':10,'max_rss_mib':512}}
        Path(artifact_path('p7-performance.json')).write_text(json.dumps(report,indent=2));print('P7_PERFORMANCE',json.dumps(report));self.assertEqual((status,result['affected_count']),(200,10000));self.assertFalse(Customer.objects.exists());self.assertFalse(Assignment.objects.exists());self.assertFalse(Callback.objects.exists());self.assertFalse(CustomerDeletionRequest.objects.exists());self.assertLess(elapsed,30);self.assertLess(max(holds),10);self.assertLess(peak,512)
