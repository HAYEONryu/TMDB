from scripts.verification_evidence import artifact_path
import json,resource,time
from contextlib import contextmanager
from datetime import datetime,timedelta,time as day_time
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from django.db import connection
from apps.assignments.models import Assignment
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.operations.scheduler import run_jobs
from apps.operations.models import ScheduledJobRun
from apps.common.transactions import business_write
from tests.helpers import TEST_HASHERS
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS,SCHEDULER_START_DATE='')
class SchedulerPerformanceTests(Fixtures,TransactionTestCase):
    def test_10000_automatic_recall_actual_postgresql(self):
        self.prepare();rows=self.customers(10000);now=datetime.combine(timezone.localdate(),day_time(23,5),KST)
        assignments=[Assignment(customer=row,employee=self.employee,assigned_by=self.admin,assigned_at=now.replace(hour=10)) for row in rows]
        Assignment.objects.bulk_create(assignments,batch_size=500)
        for row,assignment in zip(rows,assignments):row.current_assignment=assignment
        Customer.objects.bulk_update(rows,['current_assignment'],batch_size=500)
        locks=[]
        @contextmanager
        def timed_write():
            with business_write():
                start=time.monotonic()
                try:yield
                finally:locks.append(time.monotonic()-start)
        queries=[]
        def profile(execute,sql,params,many,context):
            started=time.monotonic()
            try:return execute(sql,params,many,context)
            finally:
                duration=time.monotonic()-started
                if duration>.02:queries.append({'sql_prefix':sql[:180],'seconds':round(duration,3)})
        started=time.monotonic()
        with patch('apps.operations.scheduler.timezone.now',return_value=now),patch('apps.operations.scheduler.business_write',timed_write),connection.execute_wrapper(profile):result=run_jobs(now=now)
        elapsed=time.monotonic()-started;rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024/1024
        self.assertEqual(result,{'completed':1,'failed':0});self.assertEqual(ScheduledJobRun.objects.get().affected_count,10000);self.assertFalse(Customer.objects.exclude(current_assignment=None).exists());self.assertLess(elapsed,30);self.assertLess(rss,512)
        evidence={'rows':10000,'automatic_recall_seconds':round(elapsed,3),'peak_process_rss_mib':round(rss,2),'business_lock_hold_seconds':[round(value,3) for value in locks],'criteria':{'max_seconds':30,'max_peak_rss_mib':512,'max_lock_hold_seconds':10}}
        Path(artifact_path('p6-performance-profile.json')).write_text(json.dumps(queries,ensure_ascii=False,indent=2));Path(artifact_path('p6-performance.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print('P6_PERFORMANCE',json.dumps(evidence));self.assertLess(max(locks),10)
