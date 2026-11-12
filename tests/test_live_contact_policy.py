"""Global live contact checks, trash reuse and synthetic schema upgrade."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.accounts.access import AccessError
from apps.customers.models import Customer
from apps.customers.services import trash_operation, update_row
from apps.imports.services import validate_upload, commit_upload
from tests.helpers import TEST_HASHERS
from tests.test_imports import Fixtures, uploaded, workbook, row


class ContactFixtures(Fixtures):
    def upload_for(self, site, rows):
        return validate_upload(self.admin, site.pk, uploaded(workbook(rows)))

    def commit_for(self, batch):
        return commit_upload(self.admin, batch.pk, self.body(site_id=str(batch.site_id)))

    def restore(self, *customers):
        return trash_operation(self.admin, {'customer_ids':[str(c.pk) for c in customers],
            'site_id':'all','idempotency_key':str(uuid4())}, restore=True)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class LiveContactPolicyTests(ContactFixtures, TestCase):
    def setUp(self):self.prepare()

    def test_upload_a_then_b_skips_a_numbers_without_overwriting_existing(self):
        a=self.upload_for(self.site,[row('가상 A1','01093000001'),row('가상 A2','01093000002',**{'6':'기존 상담 보존'})])
        self.assertEqual(self.commit_for(a)[0]['success_count'],2)
        previous=Customer.objects.get(phone_normalized='01093000002')
        b=self.upload_for(self.other_site,[row('다른 이름','010-9300-0002',**{'6':'덮어쓰지 않음'}),row('가상 B3','01093000003')])
        self.assertEqual(b.validation_summary['duplicate_existing'],1)
        self.assertEqual(self.commit_for(b)[0]['success_count'],1)
        previous.refresh_from_db();self.assertEqual(previous.notes,'기존 상담 보존')
        self.assertEqual(Customer.objects.filter(site=self.other_site).count(),1)
        self.assertEqual(Customer.objects.get(site=self.other_site).phone_normalized,'01093000003')

    def test_trash_in_same_or_other_site_does_not_block_new_import(self):
        for site,phone in [(self.site,'01093000001'),(self.other_site,'01093000002')]:
            Customer.objects.create(site=site,phone_normalized=phone,deleted_at=timezone.now(),deleted_by=self.admin,notes='가상 보존')
        batch=self.upload_for(self.site,[row('신규1','01093000001'),row('신규2','01093000002'),row('중복','010-9300-0001')])
        self.assertEqual((batch.validation_summary['ready'],batch.validation_summary['duplicate_in_file']), (2,1))
        self.assertEqual(self.commit_for(batch)[0]['success_count'],2)
        self.assertEqual(Customer.objects.filter(deleted_at__isnull=False,notes='가상 보존').count(),2)
        self.assertEqual(Customer.objects.filter(deleted_at=None).count(),2)

    def test_commit_rechecks_new_contact_in_another_site(self):
        batch=self.validate()
        previous=Customer.objects.create(site=self.other_site,phone_normalized='01090000001',notes='다른 현장 보존')
        self.assertEqual(self.commit_for(batch)[0]['success_count'],0)
        self.assertEqual(batch.row_results.get().error_code,'DUPLICATE_PHONE')
        previous.refresh_from_db();self.assertEqual(previous.notes,'다른 현장 보존')

    def test_restored_contact_after_validation_is_excluded_at_commit(self):
        old=Customer.objects.create(site=self.other_site,phone_normalized='01090000001',deleted_at=timezone.now(),deleted_by=self.admin)
        batch=self.validate();self.assertEqual(batch.validation_summary['ready'],1)
        self.restore(old)
        self.assertEqual(self.commit_for(batch)[0]['success_count'],0)
        self.assertEqual(Customer.objects.count(),1)

    def test_restore_conflict_in_other_site_cancels_entire_selection(self):
        old=Customer.objects.create(site=self.site,phone_normalized='01093000001',deleted_at=timezone.now(),deleted_by=self.admin)
        free=Customer.objects.create(site=self.site,phone_normalized='01093000002',deleted_at=timezone.now(),deleted_by=self.admin)
        Customer.objects.create(site=self.other_site,phone_normalized=old.phone_normalized)
        with self.assertRaises(AccessError) as caught:self.restore(free,old)
        self.assertEqual(caught.exception.code,'DUPLICATE_PHONE')
        old.refresh_from_db();free.refresh_from_db()
        self.assertIsNotNone(old.deleted_at);self.assertIsNotNone(free.deleted_at)

    def test_restore_same_phone_in_selection_requires_one_at_a_time(self):
        old=Customer.objects.create(site=self.site,phone_normalized='01093000001',deleted_at=timezone.now(),deleted_by=self.admin)
        another=Customer.objects.create(site=self.other_site,phone_normalized=old.phone_normalized,deleted_at=timezone.now(),deleted_by=self.admin)
        with self.assertRaises(AccessError):self.restore(old,another)
        self.assertEqual(self.restore(old)['affected_count'],1)
        with self.assertRaises(AccessError):self.restore(another)
        self.assertEqual(Customer.objects.filter(deleted_at=None).count(),1)

    def test_legacy_cross_site_duplicate_can_save_notes_and_unchanged_phone(self):
        old=Customer.objects.create(site=self.site,phone_normalized='01093000001')
        Customer.objects.create(site=self.other_site,phone_normalized=old.phone_normalized)
        result=update_row(self.admin,{'customer_id':str(old.pk),'assignment_id':None,'mutation_id':str(uuid4()),
            'expected_version':1,'changes':{'phone_normalized':'010-9300-0001','notes':'기존 자료 상담 유지'}})
        self.assertTrue(result['ok']);self.assertEqual(Customer.objects.count(),2)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class LiveContactConcurrencyTests(ContactFixtures, TransactionTestCase):
    def setUp(self):self.prepare()

    def pair(self, *actions):
        barrier=Barrier(2)
        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:return action()
                except AccessError as exc:return exc.code
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,actions))

    def test_concurrent_uploads_to_different_sites_have_one_winner(self):
        a=self.upload_for(self.site,[row()]);b=self.upload_for(self.other_site,[row()])
        results=self.pair(lambda:self.commit_for(a)[0]['success_count'],lambda:self.commit_for(b)[0]['success_count'])
        self.assertCountEqual(results,[0,1]);self.assertEqual(Customer.objects.filter(deleted_at=None).count(),1)

    def test_upload_and_restore_race_cannot_create_global_duplicate(self):
        old=Customer.objects.create(site=self.other_site,phone_normalized='01090000001',deleted_at=timezone.now(),deleted_by=self.admin,notes='가상 보존')
        batch=self.validate()
        self.pair(lambda:self.commit_for(batch),lambda:self.restore(old))
        self.assertEqual(Customer.objects.filter(phone_normalized=old.phone_normalized,deleted_at=None).count(),1)
        old.refresh_from_db();self.assertEqual(old.notes,'가상 보존')

    def test_upload_and_admin_phone_edit_race_cannot_create_global_duplicate(self):
        other=Customer.objects.create(site=self.other_site,phone_normalized='01093000002')
        batch=self.validate()
        def edit():
            return update_row(self.admin,{'customer_id':str(other.pk),'assignment_id':None,'mutation_id':str(uuid4()),
                'expected_version':1,'changes':{'phone_normalized':'01090000001'}})
        self.pair(lambda:self.commit_for(batch),edit)
        self.assertEqual(Customer.objects.filter(phone_normalized='01090000001',deleted_at=None).count(),1)


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class LiveContactMigrationTests(ContactFixtures, TransactionTestCase):
    def test_upgrade_preserves_legacy_duplicates_and_allows_trash_reuse(self):
        self.prepare();target=[('customers','0003_live_phone_unique')]
        try:
            MigrationExecutor(connection).migrate([('customers','0002_customer_metadata')])
            old=MigrationExecutor(connection).loader.project_state([('customers','0002_customer_metadata')]).apps.get_model('customers','Customer')
            a=old.objects.create(site_id=self.site.pk,phone_normalized='01093000001',notes='가상 A 보존')
            b=old.objects.create(site_id=self.other_site.pk,phone_normalized='01093000001',notes='가상 B 보존')
            trash=old.objects.create(site_id=self.site.pk,phone_normalized='01093000002',deleted_at=timezone.now(),deleted_by_id=self.admin.pk,notes='가상 휴지통 보존')
            MigrationExecutor(connection).migrate(target)
            self.assertEqual(Customer.objects.count(),3)
            for previous in [a,b,trash]:self.assertEqual(Customer.objects.get(pk=previous.pk).notes,previous.notes)
            fresh=Customer.objects.create(site=self.site,phone_normalized=trash.phone_normalized)
            self.assertNotEqual(fresh.pk,trash.pk)
        finally:MigrationExecutor(connection).migrate([("customers","0004_customer_selection_options")])
