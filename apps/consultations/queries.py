"""Consultation activity excludes identity and private-note corrections alone."""
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import F, Q
from apps.accounts.models import User
from .models import ConsultationRevision

NON_CONSULTATION_FIELDS = ['customer_name', 'phone_normalized', 'admin_notes']


def audit_started_at():
    return MigrationRecorder.Migration.objects.filter(app='consultations',name='0001_initial').values_list('applied',flat=True).first()


def consultation_saves(query=None):
    query = ConsultationRevision.objects.all() if query is None else query
    return query.filter(source__in=[ConsultationRevision.Source.MANUAL, ConsultationRevision.Source.AI_APPLIED]).exclude(
        changed_fields__contained_by=NON_CONSULTATION_FIELDS)


def staff_consultation_saves():
    """Include past employee work when assignment history identifies the author."""
    return consultation_saves().filter(
        Q(actor__role=User.Role.EMPLOYEE) | Q(assignment__employee_id=F('actor_id'))
    )
