"""Consultation activity excludes identity and private-note corrections alone."""
from .models import ConsultationRevision

NON_CONSULTATION_FIELDS = ['customer_name', 'phone_normalized', 'admin_notes']


def consultation_saves(query=None):
    query = ConsultationRevision.objects.all() if query is None else query
    return query.filter(source__in=[ConsultationRevision.Source.MANUAL, ConsultationRevision.Source.AI_APPLIED]).exclude(
        changed_fields__contained_by=NON_CONSULTATION_FIELDS)
