from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
import json,platform,resource,sys
from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase,override_settings
from apps.assignments.models import Assignment
from apps.assignments.services import distribute,recall,business_write
from apps.customers.models import Customer
from apps.accounts.models import User
from tests.test_p4 import Fixtures
from tests.helpers import user,TEST_HASHERS


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class AssignmentPerformanceTests(Fixtures,TransactionTestCase):
    def test_10000_random_distribution_and_recall(self):
        self.prepare();user("01000000004",initial=False);user("01000000005",initial=False);self.customers(10000)
        holds=[]
        @contextmanager
        def measured():
            acquired=None
            try:
                with business_write():acquired=perf_counter();yield
            finally:
                if acquired is not None:holds.append(perf_counter()-acquired)
        with patch("apps.assignments.services.business_write",measured):
            start=perf_counter();result,status=distribute(self.admin,self.body(quantity=2500));distributed=perf_counter()
            recalled,status2=recall(self.admin,self.recall_body());finished=perf_counter()
        self.assertEqual((status,result["allocated_count"],status2,recalled["recalled_count"]),(200,10000,200,10000))
        self.assertEqual(Customer.objects.filter(current_assignment=None).count(),10000)
        self.assertEqual(Assignment.objects.filter(end_reason="MANUAL_RECALL").count(),10000)
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=="darwin" else 1024)
        evidence={"rows":10000,"employees":4,"quantity_per_employee":2500,"random_distribute_seconds":round(distributed-start,3),"recall_seconds":round(finished-distributed,3),
            "total_seconds":round(finished-start,3),"peak_process_rss_mib":round(peak,2),"business_lock_hold_seconds":[round(n,3) for n in holds],
            "python":platform.python_version(),"platform":platform.platform(),"postgres_version":connection.pg_version,
            "criteria":{"max_total_seconds":30,"max_peak_rss_mib":512,"max_lock_hold_seconds":10}}
        path=Path(settings.BASE_DIR)/".local/p4-performance.json";path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
        print("P4_PERFORMANCE",json.dumps(evidence,ensure_ascii=False))
        self.assertLess(finished-start,30);self.assertLess(peak,512);self.assertLess(max(holds),10)
