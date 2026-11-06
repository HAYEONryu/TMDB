"""Opt-in deployment settings. Backend must only be reachable through our proxy."""
import re
from django.core.exceptions import ImproperlyConfigured
from .settings import *  # noqa: F403

APP_DOMAIN = os.environ.get('APP_DOMAIN', '')
if not re.fullmatch(r'(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', APP_DOMAIN) or '.' not in APP_DOMAIN or '..' in APP_DOMAIN:
    raise ImproperlyConfigured('APP_DOMAIN에는 포트/스킴 없는 도메인이 필요합니다.')
if DEBUG or ALLOW_DEMO_SEED:
    raise ImproperlyConfigured('운영에서는 DEBUG와 ALLOW_DEMO_SEED를 끄세요.')
if len(SECRET_KEY) < 50 or 'fake' in SECRET_KEY.lower() or len(set(SECRET_KEY)) < 20:
    raise ImproperlyConfigured('운영 전용 무작위 DJANGO_SECRET_KEY가 필요합니다.')
if DATABASES['default'].get('PASSWORD') in {'', 'tm-local-only', 'fake'}:
    raise ImproperlyConfigured('운영 전용 DB 자격증명이 필요합니다.')
ALLOWED_HOSTS = [APP_DOMAIN]
CSRF_TRUSTED_ORIGINS = ['https://' + APP_DOMAIN]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
# The isolated backend is essential: Caddy overwrites this header at the edge.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
