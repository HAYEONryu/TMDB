from contextlib import contextmanager
from functools import wraps
import time
from django.conf import settings
from django.db import OperationalError, connection, transaction

BUSINESS_LOCK_KEY = 7420192701


@contextmanager
def business_write():
    """All domain writes share this transaction lock; callers re-read inside it."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [f"{settings.BUSINESS_LOCK_TIMEOUT_MS}ms"])
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [BUSINESS_LOCK_KEY])
        yield


def retry_transient_write(function):
    """One bounded retry, always after the failed atomic block has rolled back."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        for attempt in range(2):
            try:
                return function(*args, **kwargs)
            except OperationalError as exc:
                code = getattr(exc.__cause__, "sqlstate", None)
                if attempt or code not in {"55P03", "40P01", "40001"}:
                    raise
                time.sleep(0.05)
    return wrapped
