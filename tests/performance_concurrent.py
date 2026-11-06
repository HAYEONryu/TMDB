"""Actual two-worker Gunicorn + PostgreSQL, twenty independent HTTP sessions."""
from concurrent.futures import ThreadPoolExecutor
import http.cookiejar
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
from threading import Barrier
import time
from urllib.parse import quote, urlencode
import urllib.request
from uuid import uuid4

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from apps.assignments.models import Assignment
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from tests.helpers import STRONG_PASSWORD, user
from tests.runtime_helpers import free_port, wait_http
from tests.test_p4 import Fixtures


class ConcurrentHTTPTests(Fixtures, TransactionTestCase):
    def test_twenty_sessions_read_and_save_10000_customers(self):
        self.prepare()
        employees = [self.employee, self.other] + [user(f'0109100{i:04}', initial=False, name=f'부하가상직원{i}') for i in range(17)]
        customers = self.customers(10000)
        assignments = []
        for index, employee in enumerate(employees):
            for customer in customers[index*500:(index+1)*500]:
                assignments.append(Assignment(customer=customer, employee=employee, assigned_by=self.admin, assigned_at=timezone.now()))
        Assignment.objects.bulk_create(assignments, batch_size=1000)
        for customer, assignment in zip(customers, assignments):
            customer.current_assignment = assignment
        Customer.objects.bulk_update(customers[:9500], ['current_assignment'], batch_size=1000)
        accounts = employees + [self.admin]
        targets = [customers[index*500] for index in range(20)]
        source = connection.settings_dict
        database_url = f"postgresql://{quote(source['USER'],safe='')}:{quote(source['PASSWORD'],safe='')}@{source['HOST']}:{source['PORT']}/{source['NAME']}"
        port = free_port(); origin = f'http://127.0.0.1:{port}'
        with tempfile.TemporaryDirectory(prefix='tm-p13-load-', dir='/private/tmp') as directory:
            env = {k: v for k, v in os.environ.items() if not k.startswith('AI_')}
            env.update(DJANGO_SETTINGS_MODULE='config.test_settings', DATABASE_URL=database_url,
                       AI_ENV_FILE=str(Path(directory)/'missing.ai'), LOGIN_REQUEST_FAILURE_LIMIT='100')
            if os.environ.get('TM_PROFILE_SQL') == 'true':
                env['DJANGO_SETTINGS_MODULE']='tests.load_settings'
            with (Path(directory)/'server.log').open('w') as log:
                process = subprocess.Popen([str(settings.BASE_DIR/'.venv/bin/gunicorn'), 'config.wsgi:application', '--bind', f'127.0.0.1:{port}',
                    '--workers', '2', '--worker-class', 'gthread', '--threads', '4', '--access-logfile', str(settings.BASE_DIR/'.local/p13-load-access.log'),
                    '--access-logformat', '%(m)s %(U)s %(D)s'], cwd=settings.BASE_DIR, env=env, stdout=log, stderr=log)
                try:
                    wait_http(origin+'/healthz', process)
                    barrier = Barrier(20)

                    def session(index):
                        account, customer = accounts[index], targets[index]
                        cookies = http.cookiejar.CookieJar()
                        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
                        def request(path, data=None, queue=False):
                            headers = {'Content-Type':'application/json'}
                            if data is not None:
                                headers['X-CSRFToken'] = next(cookie.value for cookie in cookies if cookie.name == 'csrftoken')
                            if queue: headers['X-TM-Queue-User'] = str(account.pk)
                            request = urllib.request.Request(origin+path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
                            start = time.perf_counter()
                            with client.open(request, timeout=15) as response:
                                result = json.loads(response.read())
                                if response.status != 200: raise AssertionError('Unexpected HTTP status')
                            return result, time.perf_counter()-start
                        with client.open(origin+'/auth/login', timeout=15) as response: response.read()
                        request('/auth/login', {'phone':account.phone_normalized, 'password':STRONG_PASSWORD})
                        barrier.wait(timeout=30)
                        reads, writes = [], []
                        admin = account.role == 'ADMIN'
                        for iteration in range(5):
                            data, elapsed = request('/api/customers?' + urlencode({'site_id':self.site.pk,'view':'all' if admin else 'mine','page_size':50}), queue=not admin)
                            if len(data['data']) != 50 or data['total'] != (10000 if admin else 500): raise AssertionError('Scoped grid/count mismatch')
                            if not admin and any(row['assignee_id'] != str(account.pk) for row in data['data']): raise AssertionError('Cross-account data exposed')
                            reads.append(elapsed)
                            payload = {'rows':[{'customer_id':str(customer.pk), 'assignment_id':str(customer.current_assignment_id) if customer.current_assignment_id else None,
                                'expected_version':iteration+1,'mutation_id':str(uuid4()),'changes':{'notes':f'동시 검수 가짜 상담 {iteration}'}}]}
                            data, elapsed = request('/api/customers/batch-update' if admin else '/api/employee/batch-update', payload, queue=not admin)
                            if not data['results'][0]['ok']: raise AssertionError('Concurrent save failed')
                            writes.append(elapsed)
                        return reads, writes

                    started = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=20) as pool:
                        outcomes = list(pool.map(session, range(20)))
                    elapsed = time.perf_counter()-started
                finally:
                    process.terminate(); process.wait(timeout=20)
                self.assertEqual(process.returncode, 0)
        reads = sorted(value for read, _ in outcomes for value in read)
        writes = sorted(value for _, write in outcomes for value in write)
        p95 = lambda values: values[math.ceil(.95*len(values))-1]
        report = {'sessions':20,'customers':10000,'gunicorn_workers':2,'threads_per_worker':4,'rounds_per_session':5,
            'measured_requests':200,'failed_requests':0,'elapsed_including_login_seconds':round(elapsed,3),
            'read_p95_seconds':round(p95(reads),3),'write_p95_seconds':round(p95(writes),3),
            'read_max_seconds':round(max(reads),3),'write_max_seconds':round(max(writes),3),
            'criteria':{'read_p95_max_seconds':2,'write_p95_max_seconds':3},
            'scope':'local synthetic data; production infrastructure SLA not certified'}
        (settings.BASE_DIR/'.local/p13-concurrency.json').write_text(json.dumps(report,indent=2))
        self.assertEqual(ConsultationRevision.objects.count(),100)
        self.assertEqual(Customer.objects.filter(version=6).count(),20)
        self.assertLess(p95(reads),2)
        self.assertLess(p95(writes),3)
