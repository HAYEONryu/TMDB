"""Explicit, isolated 10,000-row performance check; no production data."""
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import platform
import resource
import sys
from time import perf_counter
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase,override_settings
from openpyxl import Workbook
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.imports.models import ImportCandidate
from apps.imports.services import validate_upload,commit_upload,business_write
from tests.helpers import TEST_HASHERS
from tests.test_imports import Fixtures,HEADERS,uploaded


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class ImportPerformanceTests(Fixtures,TransactionTestCase):
    def test_10000_rows_actual_postgresql(self):
        self.prepare()
        book=Workbook(write_only=True);sheet=book.create_sheet("가짜 고객");sheet.append(HEADERS)
        for i in range(1,10001):
            sheet.append([None,f"성능검수가상{i:05}",f"010700{i:05}","관심" if i%3==0 else None,"2026-11-04 14:30","미확인",
                "개인정보가 없는 가상 상담 기록입니다. 다음 상담을 위한 연습 메모입니다.","2026-11-05 10:00" if i%4==0 else None,"전세"])
        output=BytesIO();book.save(output);book.close();data=output.getvalue()
        holds=[]
        @contextmanager
        def measured_write():
            acquired=None
            try:
                with business_write():
                    acquired=perf_counter()
                    yield
            finally:
                if acquired is not None:holds.append(perf_counter()-acquired)
        with patch("apps.imports.services.business_write",measured_write):
            started=perf_counter();batch=validate_upload(self.admin,self.site.pk,uploaded(data));validated=perf_counter()
            result,status=commit_upload(self.admin,batch.pk,self.body());finished=perf_counter()
        self.assertEqual((status,result["success_count"],result["failure_count"]),(200,10000,0))
        self.assertEqual(Customer.objects.count(),10000);self.assertEqual(ConsultationRevision.objects.count(),10000)
        self.assertEqual(Callback.objects.count(),2500);self.assertEqual(ImportCandidate.objects.count(),0)
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024**2 if sys.platform=="darwin" else 1024)
        evidence={"rows":10000,"xlsx_bytes":len(data),"validate_seconds":round(validated-started,3),"commit_seconds":round(finished-validated,3),
            "total_seconds":round(finished-started,3),"peak_process_rss_mib":round(peak,2),"business_lock_hold_seconds":[round(value,3) for value in holds],
            "python":platform.python_version(),"platform":platform.platform(),"postgres_version":connection.pg_version,
            "criteria":{"max_total_seconds":30,"max_peak_rss_mib":512,"max_lock_hold_seconds":10}}
        target=Path(settings.BASE_DIR)/".local/p3-performance.json";target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
        print("P3_PERFORMANCE",json.dumps(evidence,ensure_ascii=False))
        self.assertLess(finished-started,30);self.assertLess(peak,512);self.assertLess(max(holds),10)
