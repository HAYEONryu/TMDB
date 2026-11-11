"""Site rename permissions, preserved references and concurrent writes (synthetic DB)."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.db import IntegrityError, close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings

from apps.accounts.access import AccessError
from apps.customers.deletions import confirm_site, hard_delete_site
from apps.operations.models import OperationEvent
from apps.sites.models import Site, GlobalSettings, DefaultSiteHistory
from apps.sites.services import rename_site
from tests.helpers import TEST_HASHERS, login
from tests.test_p2 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class SiteRenameTests(Fixtures, TestCase):
    def setUp(self):
        self.prepare()
        self.client = login(self.admin)

    def body(self, name='가상 변경 현장'):
        self.site.refresh_from_db()
        return {'name': name, 'expected_version': self.site.updated_at.isoformat()}

    def rename(self, body, site_id=None):
        return self.client.patch(f'/api/sites/{site_id or self.site.pk}', body, content_type='application/json')

    def test_admin_rename_preserves_ids_default_history_and_customer_assignment(self):
        settings = GlobalSettings.objects.get()
        history_count = DefaultSiteHistory.objects.count()
        old_stamp = self.site.updated_at
        result = self.rename(self.body('  가상 변경 현장  '))
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['changed'])
        self.assertEqual(result.json()['id'], str(self.site.pk))
        self.site.refresh_from_db(); settings.refresh_from_db(); self.customer.refresh_from_db()
        self.assertEqual((self.site.name, self.site.name_key), ('가상 변경 현장', '가상변경현장'))
        self.assertGreater(self.site.updated_at, old_stamp)
        self.assertEqual(settings.default_site_id, self.site.pk)
        self.assertEqual(settings.version, 2)
        self.assertEqual(DefaultSiteHistory.objects.count(), history_count)
        self.assertEqual(self.customer.site_id, self.site.pk)
        self.assertEqual(self.customer.current_assignment_id, self.assignment.pk)
        self.assertEqual(self.customer.version, 1)
        self.assertEqual(OperationEvent.objects.filter(operation='SITE_RENAMED', actor=self.admin, affected_count=1).count(), 1)
        self.client = login(self.employee)
        row = next(r for r in self.client.get('/api/sites').json()['items'] if r['id'] == str(self.site.pk))
        self.assertEqual((row['name'], row['version']), ('가상 변경 현장', result.json()['version']))

    def test_normalized_duplicate_and_invalid_inputs_leave_original_name(self):
        original = self.site.name
        response = self.rename(self.body(' 가 상 현 장 b '))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'DUPLICATE_SITE')
        for name in [None, '', '  ', '가' * 101, 12, [], 'İ' * 100]:
            self.assertEqual(self.rename(self.body(name)).status_code, 422)
        for body in [{}, [], {'name': 'X'}, {**self.body(), 'extra': True}, {**self.body(), 'expected_version': 1}]:
            self.assertEqual(self.rename(body).status_code, 422)
        self.site.refresh_from_db()
        self.assertEqual(self.site.name, original)
        self.assertFalse(OperationEvent.objects.filter(operation='SITE_RENAMED').exists())

    def test_stale_change_rejected_and_lost_response_repeat_is_noop(self):
        body = self.body()
        first = self.rename(body).json()
        self.assertTrue(first['changed'])
        repeat = self.rename(body)
        self.assertEqual(repeat.status_code, 200)
        self.assertFalse(repeat.json()['changed'])
        self.assertEqual(repeat.json()['version'], first['version'])
        response = self.rename({**body, 'name': '이전 화면의 다른 이름'})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error']['code'], 'VERSION_CONFLICT')
        self.assertEqual(OperationEvent.objects.filter(operation='SITE_RENAMED').count(), 1)

    def test_employee_anonymous_and_other_actor_cannot_rename(self):
        body = self.body()
        self.client = login(self.employee)
        self.assertEqual(self.rename(body).status_code, 403)
        self.client = Client()
        self.assertEqual(self.rename(body).status_code, 401)
        self.client = login(self.admin)
        response = self.client.patch(f'/api/sites/{self.site.pk}', body, content_type='application/json',
                                     HTTP_X_TM_ACTOR=str(self.employee.pk))
        self.assertEqual(response.status_code, 403)
        with self.assertRaises(AccessError) as caught:
            rename_site(self.employee, self.site.pk, **{'name': body['name'], 'expected_version': body['expected_version']})
        self.assertEqual(caught.exception.code, 'FORBIDDEN')

    def test_service_rechecks_disabled_admin_and_session_version(self):
        body = self.body()
        for updates, error in [({'is_active': False}, 'ACCOUNT_DISABLED'), ({'session_version': self.admin.session_version + 1}, 'UNAUTHENTICATED')]:
            type(self.admin).objects.filter(pk=self.admin.pk).update(**updates)
            with self.assertRaises(AccessError) as caught:
                rename_site(self.admin, self.site.pk, body['name'], body['expected_version'])
            self.assertEqual(caught.exception.code, error)
            type(self.admin).objects.filter(pk=self.admin.pk).update(is_active=True, session_version=self.admin.session_version)

    def test_missing_site_and_journal_failure_do_not_partially_write(self):
        body = self.body()
        self.assertEqual(self.rename(body, uuid4()).json()['error']['code'], 'SITE_DELETED')
        with patch('apps.sites.services.OperationEvent.objects.create', side_effect=IntegrityError('synthetic')):
            self.assertEqual(self.rename(body).status_code, 503)
        self.site.refresh_from_db()
        self.assertEqual(self.site.name, '가상현장 A')
        self.assertFalse(Site.objects.filter(name_key='가상변경현장').exists())

    def test_rename_invalidates_old_site_deletion_confirmation(self):
        key = str(uuid4())
        proof = confirm_site(self.admin, self.site.pk, {'confirm_name': self.site.name, 'idempotency_key': key})
        self.assertEqual(self.rename(self.body()).status_code, 200)
        with self.assertRaises(AccessError) as caught:
            hard_delete_site(self.admin, self.site.pk, {**proof, 'idempotency_key': key})
        self.assertEqual(caught.exception.code, 'VALIDATION_ERROR')
        self.assertTrue(Site.objects.filter(pk=self.site.pk).exists())
        self.customer.refresh_from_db()


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class SiteRenameConcurrencyTests(Fixtures, TransactionTestCase):
    def run_pair(self, targets, names):
        barrier = Barrier(2)
        def save(args):
            site, name = args
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    rename_site(self.admin, site.pk, name, site.updated_at.isoformat())
                    return 'ok'
                except AccessError as exc:
                    return exc.code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(save, zip(targets, names)))

    def test_same_site_concurrent_changes_have_one_winner(self):
        self.prepare()
        self.assertCountEqual(self.run_pair([self.site, self.site], ['가상 정정1', '가상 정정2']), ['ok', 'VERSION_CONFLICT'])
        self.assertEqual(OperationEvent.objects.filter(operation='SITE_RENAMED').count(), 1)

    def test_two_sites_cannot_claim_same_normalized_name(self):
        self.prepare()
        self.assertCountEqual(self.run_pair([self.site, self.second], ['가상 정정', ' 가 상 정 정 ']), ['ok', 'DUPLICATE_SITE'])
        self.assertEqual(Site.objects.filter(name_key='가상정정').count(), 1)
