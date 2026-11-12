"""Compact new audit snapshots without removing actual changed values."""
LARGE_TEXT_FIELDS = {'notes', 'memo', 'admin_notes', 'residence', 'route'}


def audit_snapshot(values, changed_fields):
    return {key: value for key, value in values.items()
            if key not in LARGE_TEXT_FIELDS or key in changed_fields}
