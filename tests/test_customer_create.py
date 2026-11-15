"""Single customer creation: synthetic data, existing contact and role policies."""
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.access import AccessError
from apps.callbacks.models import Callback
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.customers.services import create_customer
from apps.operations.models import IdempotencyRecord, OperationEvent
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerCreateTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare()
        self.client = login(self.admin)

    def body(self, **values):
        return {'site_id': str(self.second.pk), 'idempotency_key': str(uuid4()),
                'values': {'phone_normalized': '010-9400-0001', **values}}

    def post(self, body, **headers):
        return self.client.post('/api/customers/create', body, content_type='application/json', **headers)

    def test_selected_site_optional_name_contact_normalization_and_defaults(self):
        response = self.post(self.body())
        self.assertEqual(response.status_code, 201)
        customer = Customer.objects.get(pk=response.json()['customer_id'])
        self.assertEqual((customer.site_id, customer.customer_name, customer.phone_normalized),
                         (self.second.pk, '', '01094000001'))
        self.assertEqual((customer.version, customer.contract_status, customer.current_assignment_id, customer.import_batch_id),
                         (1, 'UNKNOWN', None, None))
        self.assertFalse(ConsultationRevision.objects.exists())
        self.assertEqual(OperationEvent.objects.filter(operation='CUSTOMER_CREATED', actor=self.admin).count(), 1)

    def test_initial_fields_callback_and_exact_replay_after_lost_response(self):
        body = self.body(customer_name=' 가상 신규 고객 ', call_result='INTERESTED', contract_status='CONTRACTED',
                         notes='가상 상담\r\n다음 줄', admin_notes='SYNTHETIC_PRIVATE', housing_status='무주택',
                         residence='서울', route='티엠', memo='가상 비고', visit_at='2026-11-15T14:30:00+09:00',
                         callback_due_at='2026-11-16T00:00:00+09:00')
        first = self.post(body)
        self.assertEqual(first.status_code, 201)
        customer = Customer.objects.get()
        self.assertEqual((customer.customer_name, customer.notes, customer.admin_notes),
                         ('가상 신규 고객', '가상 상담\n다음 줄', 'SYNTHETIC_PRIVATE'))
        callback = Callback.objects.get(customer=customer)
        self.assertEqual((callback.due_at.isoformat(), callback.created_by_id), ('2026-11-15T15:00:00+00:00', self.admin.pk))
        self.assertEqual(self.post(body).json(), first.json())
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(Callback.objects.count(), 1)
        self.assertEqual(OperationEvent.objects.filter(operation='CUSTOMER_CREATED').count(), 1)
        changed = deepcopy(body);changed['values']['customer_name'] = '다른 입력'
        self.assertEqual(self.post(changed).json()['error']['code'], 'IDEMPOTENCY_CONFLICT')
        IdempotencyRecord.objects.filter(operation='CUSTOMER_CREATE').update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post(body).json()['error']['code'], 'IDEMPOTENCY_EXPIRED')

    def test_live_phone_duplicate_across_sites_rejected_but_trash_phone_allowed(self):
        existing = Customer.objects.create(site=self.site, phone_normalized='01094000001')
        body = self.body()
        self.assertEqual(self.post(body).json()['error']['code'], 'DUPLICATE_PHONE')
        self.assertEqual(Customer.objects.count(), 1)
        existing.deleted_at = timezone.now();existing.deleted_by = self.admin;existing.save()
        self.assertEqual(self.post(body).status_code, 201)
        self.assertEqual(Customer.objects.filter(deleted_at=None).count(), 1)

    def test_invalid_fields_are_atomic_and_correctable(self):
        for values in [{}, {'phone_normalized': '---'}, {'phone_normalized': 1094000001},
                       {'customer_name': '가'*101}, {'notes': '가'*10001}, {'call_result': 'NOT_A_CHOICE'},
                       {'visit_at': '2026-11-31T00:00'}, {'callback_due_at': 'bad'},
                       {'current_assignment_id': str(uuid4())}, {'deleted_at': None}, {'site_id': str(self.site.pk)}]:
            body = self.body(**values)
            if not values:body['values'] = {}
            with self.subTest(fields=list(values)):
                self.assertEqual(self.post(body).status_code, 422)
        self.assertFalse(Customer.objects.exists());self.assertFalse(Callback.objects.exists())
        self.assertFalse(IdempotencyRecord.objects.filter(operation='CUSTOMER_CREATE').exists())
        body = self.body(phone_normalized='---')
        self.assertEqual(self.post(body).status_code, 422)
        body['values']['phone_normalized'] = '010 9400 0001'
        self.assertEqual(self.post(body).status_code, 201)

    def test_staff_forgery_actor_mismatch_and_stale_admin_are_rejected(self):
        response = login(self.employee).post('/api/customers/create', self.body(), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.post(self.body(), HTTP_X_TM_ACTOR=str(self.employee.pk)).status_code, 403)
        from apps.accounts.models import User
        User.objects.filter(pk=self.admin.pk).update(role=User.Role.EMPLOYEE)
        with self.assertRaises(AccessError) as denied:create_customer(self.admin, self.body())
        self.assertEqual(denied.exception.code, 'FORBIDDEN')
        self.assertFalse(Customer.objects.exists())

    def test_missing_site_and_malformed_body_rejected(self):
        body = self.body();body['site_id'] = str(uuid4())
        self.assertEqual(self.post(body).json()['error']['code'], 'SITE_DELETED')
        for body in [{}, {**self.body(), 'extra': True}, {**self.body(), 'values': []},
                     {**self.body(), 'site_id': 'all'}, {**self.body(), 'idempotency_key': 'invalid'}]:
            self.assertEqual(self.post(body).status_code, 422)
        self.assertFalse(Customer.objects.exists())


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections
from django.test import TransactionTestCase


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class CustomerCreateConcurrencyTests(Fixtures, TransactionTestCase):
    def setUp(self):self.prepare()

    def create_together(self, bodies):
        barrier = Barrier(2)
        def create(body):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:return create_customer(self.admin, body)[0]['customer_id']
                except AccessError as error:return error.code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(create, bodies))

    def test_simultaneous_retry_creates_once(self):
        body = {'site_id': str(self.site.pk), 'idempotency_key': str(uuid4()), 'values': {'phone_normalized': '01094000001'}}
        results = self.create_together([body, body])
        self.assertEqual(results[0], results[1])
        self.assertEqual(Customer.objects.count(), 1)
        self.assertEqual(OperationEvent.objects.filter(operation='CUSTOMER_CREATED').count(), 1)

    def test_simultaneous_different_sites_cannot_claim_same_live_phone(self):
        bodies = [{'site_id': str(site.pk), 'idempotency_key': str(uuid4()), 'values': {'phone_normalized': '01094000001'}}
                  for site in [self.site, self.second]]
        results = self.create_together(bodies)
        self.assertEqual(results.count('DUPLICATE_PHONE'), 1)
        self.assertEqual(Customer.objects.count(), 1)
