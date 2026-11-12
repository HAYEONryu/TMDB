"""Synthetic PostgreSQL storage and Python allocation comparisons, never live data."""
import gc
import json
import random
import statistics
import string
import time
import tracemalloc

from django.db import connection
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from apps.common.query_expressions import JSONSubset
from apps.consultations.models import ConsultationRevision
from apps.consultations.snapshots import audit_snapshot
from scripts.verification_evidence import artifact_path
from tests.helpers import TEST_HASHERS
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class DatabaseMemoryPerformanceTests(Fixtures,TransactionTestCase):
    def test_history_query_allocations_and_new_snapshot_storage(self):
        self.prepare();customer=self.customers()[0]
        generator=random.Random(20261113)
        prose='SYNTHETIC '+''.join(generator.choices(string.ascii_letters+' ',k=6000))
        before={'notes':prose,'memo':prose[:2000],'admin_notes':prose[2000:4000],
                'callback_due_at':None,'call_result':'INTERESTED','contract_status':'UNKNOWN'}
        after={**before,'callback_due_at':timezone.now().isoformat()}
        ConsultationRevision.objects.bulk_create([
            ConsultationRevision(customer=customer,actor=self.employee,customer_version=i+1,source='MANUAL',changed_fields=['callback_due_at'],
                before_values=before,after_values=after,notes=prose) for i in range(100)],batch_size=50)
        query=ConsultationRevision.objects.filter(customer=customer).order_by('-saved_at','-pk')

        def legacy():
            rows=list(query.values('before_values','after_values','changed_fields')[:50])
            return [{'before':{k:v for k,v in r['before_values'].items() if k in r['changed_fields']},
                     'after':{k:v for k,v in r['after_values'].items() if k in r['changed_fields']}} for r in rows]

        def projected():
            return list(query.annotate(before=JSONSubset('before_values','changed_fields',empty_means_all=True),
                after=JSONSubset('after_values','changed_fields',empty_means_all=True)).values('before','after')[:50])

        self.assertEqual(legacy(),projected())
        # One warm-up per path above, then alternate to limit cache-order bias.
        results={'legacy':[],'projected':[]}
        for _ in range(3):
            for name,load in [('legacy',legacy),('projected',projected)]:
                gc.collect();tracemalloc.start();started=time.perf_counter()
                rows=load();elapsed=time.perf_counter()-started
                _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
                results[name].append({'seconds':elapsed,'python_peak_bytes':peak});self.assertEqual(len(rows),50)
        compact_before=audit_snapshot(before,{'callback_due_at'});compact_after=audit_snapshot(after,{'callback_due_at'})
        with connection.cursor() as cursor:
            # Fresh isolated temporary tables: no rewrites of project tables.
            for name in ['memory_legacy_audit','memory_compact_audit']:
                cursor.execute('CREATE TEMP TABLE '+name+' (before_values jsonb, after_values jsonb, notes text)')
            for name,before_value,after_value in [('memory_legacy_audit',before,after),('memory_compact_audit',compact_before,compact_after)]:
                cursor.executemany('INSERT INTO '+name+' VALUES (%s::jsonb,%s::jsonb,%s)',[
                    (json.dumps(before_value),json.dumps(after_value),prose) for _ in range(300)])
            sizes={}
            for name in ['memory_legacy_audit','memory_compact_audit']:
                cursor.execute('SELECT pg_total_relation_size(%s::regclass)',['pg_temp.'+name]);sizes[name]=cursor.fetchone()[0]
            for name in ['memory_legacy_audit','memory_compact_audit']:cursor.execute('DROP TABLE '+name)
        summary={name:{'median_seconds':round(statistics.median(r['seconds'] for r in rows),6),
                       'median_python_peak_bytes':int(statistics.median(r['python_peak_bytes'] for r in rows))} for name,rows in results.items()}
        summary.update(synthetic=True,history_page_rows=50,measurement_rounds=3,storage_sample_rows=300,
            postgres_temp_relation_bytes=sizes,notes_chars=len(prose),real_customer_data=False,
            memory_scope='tracemalloc Python allocations, not process RSS or PostgreSQL RAM',
            storage_scope='fresh temporary tables with audit JSON/text columns, not production table savings')
        artifact_path('database-memory-benchmark.json').write_text(json.dumps(summary,indent=2))
        self.assertLess(summary['projected']['median_python_peak_bytes'],summary['legacy']['median_python_peak_bytes']/2)
        self.assertLess(sizes['memory_compact_audit'],sizes['memory_legacy_audit'])
