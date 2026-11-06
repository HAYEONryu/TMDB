import json,resource,time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from apps.ai_assistant.models import AIResultSource
from apps.ai_assistant.services import reserve
from apps.common.transactions import business_write
from apps.consultations.models import ConsultationRevision
from tests.helpers import TEST_HASHERS
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI
from uuid import uuid4


@override_settings(PASSWORD_HASHERS=TEST_HASHERS,AI_FOUNDATION_TEST_MODE=True,AI_CONFIG=TEST_AI)
class ReportPerformanceTests(Fixtures,TransactionTestCase):
    def test_10000_report_full_sql_totals_bounded_evidence_actual_postgresql(self):
        self.prepare();rows=self.customers(10000);now=timezone.now()
        ConsultationRevision.objects.bulk_create([ConsultationRevision(customer=row,actor=self.employee if i%2 else self.other,saved_at=now,customer_version=1,changed_fields=['notes'],notes='가격과 위치 확인을 요청한 가짜 기록',source='MANUAL') for i,row in enumerate(rows)],batch_size=500)
        locks=[]
        @contextmanager
        def timed():
            with business_write():
                started=time.monotonic()
                try:yield
                finally:locks.append(time.monotonic()-started)
        started=time.monotonic()
        with patch('apps.ai_assistant.services.business_write',timed):task,_=reserve(self.admin,{'feature':'TEAM_GUIDE','site_id':str(self.site.pk),'idempotency_key':str(uuid4())})
        elapsed=time.monotonic()-started;rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024/1024;stats=task.report_snapshot.data['statistics'];sample=task.report_snapshot.data['sampling'];size=len(json.dumps(task.input_payload,ensure_ascii=False).encode())
        self.assertEqual(stats['changed_customers'],10000);self.assertEqual(sample['total_note_groups'],10000);self.assertGreater(sample['omitted_groups'],9900);self.assertLessEqual(size,12000);self.assertEqual(AIResultSource.objects.filter(result=task.result).count(),20000)
        evidence={'rows':10000,'report_seconds':round(elapsed,3),'peak_process_rss_mib':round(rss,2),'business_lock_hold_seconds':[round(v,3) for v in locks],'provider_input_bytes':size,'sampling':sample,'criteria':{'max_seconds':30,'max_peak_rss_mib':512,'max_lock_hold_seconds':10}}
        Path(settings.BASE_DIR/'.local/p11-performance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print('P11_PERFORMANCE',json.dumps(evidence));self.assertLess(elapsed,30);self.assertLess(rss,512);self.assertLess(max(locks),10)
