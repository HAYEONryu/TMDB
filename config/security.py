import logging
from threading import RLock

_secrets = set()
_lock = RLock()


def register_secret(value):
    if value:
        with _lock:
            _secrets.add(value)


def redact(text):
    with _lock:
        for secret in sorted(_secrets, key=len, reverse=True):
            text = text.replace(secret, "[REDACTED]")
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record):
        # Format first so exception tracebacks and interpolated args are covered.
        return redact(super().format(record))
