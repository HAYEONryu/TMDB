import os
from django.core.wsgi import get_wsgi_application
from config.process import prepare_process

prepare_process("web")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
