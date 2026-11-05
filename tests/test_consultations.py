from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, connection
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.assignments.models import Assignment
from apps.consultations.models import ConsultationRevision
from apps.customers.models import Customer
from apps.sites.models import Site
from tests.helpers import TEST_HASHERS, user


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class ConsultationSchemaTests(TestCase):
    def setUp(self):
        self.actor = user()
        self.site = Site.objects.create(name="가상현장", created_by=self.actor)
        self.customer = Customer.objects.create(site=self.site, customer_name="가상고객", phone_normalized="01000000002")

    def values(self):
        return {"customer": self.customer, "actor": self.actor, "customer_version": 2,
                "source": "MANUAL", "changed_fields": ["notes"], "before_values": {"notes": "가상 원문"},
                "after_values": {"notes": "가상 새 메모"}, "notes": "가상 새 메모"}

    def test_revision_stores_real_actor_before_after_and_server_timestamp(self):
        revision = ConsultationRevision.objects.create(**self.values())
        revision.refresh_from_db()
        self.assertEqual(revision.actor_id, self.actor.pk)
        self.assertEqual(revision.before_values["notes"], "가상 원문")
        self.assertEqual(revision.after_values["notes"], "가상 새 메모")
        self.assertTrue(timezone.is_aware(revision.saved_at))
        with connection.cursor() as cursor:
            cursor.execute("SELECT data_type FROM information_schema.columns WHERE table_name='consultations_consultationrevision' AND column_name='saved_at'")
            self.assertEqual(cursor.fetchone()[0], "timestamp with time zone")

    def test_customer_version_is_unique(self):
        ConsultationRevision.objects.create(**self.values())
        with self.assertRaises(IntegrityError), transaction.atomic():
            ConsultationRevision.objects.create(**self.values())

    def test_source_version_and_actor_constraints_are_database_enforced(self):
        for changes in [{"source": "INVALID"}, {"customer_version": 0}, {"actor": None}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                ConsultationRevision.objects.create(**{**self.values(), **changes})

    def test_baseline_can_mark_unknown_actor_without_inventing_past(self):
        before = timezone.now()
        revision = ConsultationRevision.objects.create(**{**self.values(), "source": "BASELINE", "actor": None})
        self.assertIsNone(revision.actor_id)
        self.assertGreaterEqual(revision.saved_at, before)

    def test_historical_assignment_must_belong_to_same_customer(self):
        other = Customer.objects.create(site=self.site, customer_name="가상다른고객", phone_normalized="01000000003")
        assignment = Assignment.objects.create(customer=other, employee=self.actor, assigned_by=self.actor, assigned_at=timezone.now())
        revision = ConsultationRevision(**self.values(), assignment=assignment)
        with self.assertRaises(ValidationError):
            revision.full_clean()

    def test_customer_delete_removes_revision(self):
        revision = ConsultationRevision.objects.create(**self.values())
        self.customer.delete()
        self.assertFalse(ConsultationRevision.objects.filter(pk=revision.pk).exists())
