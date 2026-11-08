"""Final acceptance regressions: synthetic actors and blocked external transport."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime,timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from apps.accounts.access import AccessError
from apps.accounts.management_services import create_user, update_access, update_users
from apps.accounts.models import User
from apps.ai_assistant.services import validate_config
from apps.consultations.models import ConsultationRevision
from apps.customers.services import update_row
from apps.customers.models import Customer
from apps.customers.queries import KST
from apps.assignments.models import Assignment
from apps.assignments.services import distribute
from apps.operations.scheduler import run_jobs,cutoff_for
from apps.operations.models import ScheduledJobRun
from tests import test_free_ai_limits as free_tests
from tests.helpers import TEST_HASHERS, login, user
from tests.test_p4 import Fixtures


class FreeOnlyRuntimeTests(SimpleTestCase):
    @override_settings(TESTING=False, AI_FOUNDATION_TEST_MODE=False)
    def test_real_runtime_blocks_paid_and_other_providers_even_with_legacy_budget(self):
        for config in [replace(free_tests.FREE, usage_tier='paid', input_price=free_tests.PAID.input_price,
                               output_price=free_tests.PAID.output_price),
                       replace(free_tests.FREE, provider='openai')]:
            with self.subTest(provider=config.provider), override_settings(AI_CONFIG=config):
                with self.assertRaises(AccessError) as error:
                    validate_config()
                self.assertEqual(error.exception.code, 'AI_FREE_ONLY')
        with override_settings(AI_CONFIG=free_tests.FREE):
            self.assertEqual(validate_config().model, 'gemini-3.5-flash-lite')


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_FOUNDATION_TEST_MODE=False, AI_CONFIG=free_tests.FREE)
class StalePermissionResultTests(Fixtures, TransactionTestCase):
    body = free_tests.FreeAILimitTests.body
    process = free_tests.FreeAILimitTests.process
    task = free_tests.FreeAILimitTests.task
    setUp = free_tests.FreeAILimitTests.setUp

    def test_role_roundtrip_cannot_read_or_apply_old_result_with_new_session(self):
        task = self.task('CLEANUP')
        self.assertEqual(self.process(task)[0]['succeeded'], 1)
        task.refresh_from_db()
        update_access(self.admin, self.employee.pk, role='ADMIN')
        update_access(self.admin, self.employee.pk, role='EMPLOYEE')
        self.employee.refresh_from_db()
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.version, task.customer_version)
        client = login(self.employee)
        self.assertEqual(client.get(f'/api/ai/results/{task.result.pk}').status_code, 403)
        row = self.mutation(self.customer, '가짜 상담 관심')
        row['source_ai_result_id'] = str(task.result.pk)
        result = update_row(self.employee, row)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error']['code'], 'FORBIDDEN')
        self.assertEqual(ConsultationRevision.objects.count(), 0)
        response=client.get('/api/ai/customer-results', {'customer_id':str(self.customer.pk),
            'assignment_id':str(self.customer.current_assignment_id)}, HTTP_X_TM_QUEUE_USER=str(self.employee.pk))
        self.assertEqual(response.json()['items'], [])
        fresh=self.task('CLEANUP')
        self.assertNotEqual(fresh.pk,task.pk)
        self.assertEqual(fresh.actor_session_version,self.employee.session_version)
        self.assertEqual(fresh.status,'RESERVED')


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class AccountCapacityTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()

    def fill_staff(self, total):
        for index in range(total - 2):
            user(f'0109900{index:04}', initial=False)

    def new_user(self, role='EMPLOYEE', suffix='9999'):
        return {'name': '가상 정원 검수', 'phone': '0109900'+suffix, 'role': role, 'idempotency_key': str(uuid4())}

    def test_staff20_admin5_create_reactivate_and_role_change_are_atomic(self):
        self.fill_staff(20)
        for index in range(4):
            user(f'0109910{index:04}', role='ADMIN', initial=False)
        for role in ['EMPLOYEE', 'ADMIN']:
            with self.assertRaises(AccessError) as error:
                create_user(self.admin, self.new_user(role))
            self.assertEqual(error.exception.code, 'USER_CAPACITY_LIMIT')
        inactive = user('01099209999', initial=False)
        inactive.is_active = False
        inactive.save()
        for values in [{'is_active': True}, {'is_active': True, 'role': 'ADMIN'}]:
            with self.assertRaises(AccessError):
                update_access(self.admin, inactive.pk, **values)
        with self.assertRaises(AccessError):
            update_access(self.admin, self.employee.pk, role='ADMIN')
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.role, 'EMPLOYEE')
        # A single transaction can hand over one occupied staff slot.
        result = update_users(self.admin, self.user_body(self.edit(self.employee, is_active=False),
                                                       self.edit(inactive, is_active=True)))
        self.assertEqual(result[0]['updated_count'], 2)
        self.assertEqual(User.objects.filter(role='EMPLOYEE', is_active=True).count(), 20)

    def test_last_staff_slot_two_concurrent_creates_have_one_success(self):
        self.fill_staff(19)
        barrier = Barrier(2)
        def create(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return create_user(User.objects.get(pk=self.admin.pk), self.new_user(suffix=f'{9900+index:04}'))[0]['ok']
                except AccessError as error:
                    return error.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        self.assertCountEqual(results, [True, 'USER_CAPACITY_LIMIT'])
        self.assertEqual(User.objects.filter(role='EMPLOYEE', is_active=True).count(), 20)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS,SCHEDULER_START_DATE='')
class MixedRecallTests(Fixtures,TransactionTestCase):
    def test_save_distribution_recall_race_and_midnight_replay_preserve_invariants(self):
        self.now=datetime(2026,11,8,22,tzinfo=KST)
        with patch('django.utils.timezone.now',side_effect=lambda:self.now):
            self.prepare()
            customer,other=self.customers(2)
            old=self.assign(customer)
            mutation=self.mutation(customer,'동시 실행 가상 상담')
            body=self.body(employee_id=str(self.employee.pk))
            self.now=self.now.replace(hour=23,minute=1)
            barrier=Barrier(3)
            def execute(action):
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    try:return action()
                    except AccessError as error:return error.code
                finally:close_old_connections()
            with ThreadPoolExecutor(max_workers=3) as pool:
                saved,allocated,recalled=list(pool.map(execute,[lambda:update_row(self.employee,mutation),
                    lambda:distribute(self.admin,body),lambda:run_jobs(now=self.now)]))
            self.assertEqual(allocated[1],200)
            self.assertEqual(recalled,{'completed':1,'failed':0})
            job=ScheduledJobRun.objects.get()
            old.refresh_from_db()
            if isinstance(saved,dict) and saved.get('ok'):
                self.assertIsNotNone(old.first_activity_at)
                self.assertIsNone(old.ended_at)
                self.assertEqual(job.affected_count,0)
            else:
                self.assertEqual(saved,'ASSIGNMENT_CHANGED')
                self.assertIsNotNone(old.ended_at)
                self.assertEqual(job.affected_count,1)
            active=set(Assignment.objects.filter(ended_at=None).values_list('pk',flat=True))
            self.assertEqual(active,set(Customer.objects.exclude(current_assignment=None).values_list('current_assignment_id',flat=True)))
            self.assertFalse(Assignment.objects.filter(ended_at=None,assigned_at__lte=cutoff_for(self.now.date()),first_activity_at=None).exists())
            before=list(Customer.objects.order_by('pk').values('pk','current_assignment_id','version','notes'))
            self.now=(self.now+timedelta(days=1)).replace(hour=0,minute=1)
            self.assertEqual(run_jobs(now=self.now),{'completed':0,'failed':0})
            self.assertEqual(before,list(Customer.objects.order_by('pk').values('pk','current_assignment_id','version','notes')))
