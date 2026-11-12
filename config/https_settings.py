"""HTTPS overlay for an existing IP-based server; backend must remain private."""
from ipaddress import IPv4Address

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

HTTPS_IP = os.environ.get("TM_HTTPS_IP", "")
try:
    address = IPv4Address(HTTPS_IP)
except ValueError as exc:
    raise ImproperlyConfigured("TM_HTTPS_IP에는 공개 IPv4 주소가 필요합니다.") from exc
if not address.is_global:
    raise ImproperlyConfigured("TM_HTTPS_IP에는 공개 IPv4 주소가 필요합니다.")
if DEBUG or ALLOW_DEMO_SEED:
    raise ImproperlyConfigured("HTTPS 서버에서는 DEBUG와 ALLOW_DEMO_SEED를 끄세요.")

# Keep the existing database and signing key. This overlay does not change roles
# or provision a new database, unlike deploy/compose.production.yaml.
ALLOWED_HOSTS = [HTTPS_IP]
CSRF_TRUSTED_ORIGINS = ["https://" + HTTPS_IP]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
