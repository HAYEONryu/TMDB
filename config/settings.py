import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values
from config.ai import load_ai_config

BASE_DIR = Path(__file__).resolve().parent.parent
for env_name, env_value in dotenv_values(BASE_DIR / ".env", interpolate=False).items():
    if env_value is not None and not env_name.startswith("AI_") and env_name != "TM_PROCESS_ROLE":
        os.environ.setdefault(env_name, env_value)
PROCESS_ROLE = os.environ.get("TM_PROCESS_ROLE", "management")
TESTING = False
AI_CONFIG = load_ai_config(BASE_DIR, role=PROCESS_ROLE)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY 환경변수가 필요합니다.")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [s for s in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if s]
DATABASES = {"default": dj_database_url.parse(os.environ.get("DATABASE_URL", ""), conn_max_age=0)}
if DATABASES["default"].get("ENGINE") != "django.db.backends.postgresql":
    raise ImproperlyConfigured("DATABASE_URL은 PostgreSQL을 가리켜야 합니다.")
DATABASES["default"]["TEST"] = {"NAME": os.environ.get("TEST_DATABASE_NAME", "test_tm_dev")}
INSTALLED_APPS = [
    "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.staticfiles", "apps.accounts", "apps.sites", "apps.customers",
    "apps.assignments", "apps.callbacks", "apps.imports", "apps.operations",
    "apps.consultations", "apps.ai_assistant",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.AccessMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates",
              "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
              "OPTIONS": {"context_processors": [
                  "django.template.context_processors.request",
                  "django.contrib.auth.context_processors.auth",
              ]}}]
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
     "OPTIONS": {"user_attributes": ["name", "phone_normalized"]}},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = os.environ.get("APP_TIMEZONE", "Asia/Seoul")
if TIME_ZONE != "Asia/Seoul":
    raise ImproperlyConfigured("업무 시간대는 Asia/Seoul이어야 합니다.")
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
WHITENOISE_USE_FINDERS = DEBUG
LOGIN_URL = "/auth/login"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 43200
SESSION_COOKIE_SECURE = os.environ.get("SECURE_COOKIES", "false").lower() == "true"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "false").lower() == "true"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
LOGIN_FAILURE_WINDOW_SECONDS = int(os.environ.get("LOGIN_FAILURE_WINDOW_SECONDS", "900"))
LOGIN_ACCOUNT_FAILURE_LIMIT = int(os.environ.get("LOGIN_ACCOUNT_FAILURE_LIMIT", "5"))
LOGIN_REQUEST_FAILURE_LIMIT = int(os.environ.get("LOGIN_REQUEST_FAILURE_LIMIT", "30"))
BUSINESS_LOCK_TIMEOUT_MS = int(os.environ.get("BUSINESS_LOCK_TIMEOUT_MS", "5000"))
ALLOW_DEMO_SEED = os.environ.get("ALLOW_DEMO_SEED", "false").lower() == "true"
# Request bodies, query values and password/phone fields are never added to app logs.
LOGGING = {"version": 1, "disable_existing_loggers": False,
           "formatters": {"safe": {"()": "config.security.RedactingFormatter", "format": "%(levelname)s %(name)s %(message)s"}},
           "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "safe"}},
           "root": {"handlers": ["console"], "level": "INFO"},
           "loggers": {
               "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
               "django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False},
           }}
