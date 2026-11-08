"""Exercise real Django login routes against an independently restored database."""
import os
import subprocess
import sys
from urllib.parse import quote

from django.conf import settings
from django.db import connection


def verify_restored_login(target, employee, admin):
    if not target.startswith(('test_tm_', 'tm_restore_')) or target == connection.settings_dict['NAME']:
        raise ValueError('Separate disposable restore database required')
    source=connection.settings_dict
    env={k:v for k,v in os.environ.items() if not k.startswith('AI_')}
    env.update(DJANGO_SETTINGS_MODULE='config.test_settings', TM_PROCESS_ROLE='test', DJANGO_DEBUG='false',
        DATABASE_URL=f"postgresql://{quote(source['USER'],safe='')}:{quote(source['PASSWORD'],safe='')}@{source['HOST']}:{source['PORT']}/{target}")
    code='''
import django,sys
django.setup()
from django.test import Client,override_settings
from django.conf import settings
from tests.helpers import STRONG_PASSWORD,TEST_HASHERS
from django.db import connection
assert connection.settings_dict['NAME']==sys.argv[1]
with override_settings(PASSWORD_HASHERS=[*settings.PASSWORD_HASHERS,*TEST_HASHERS]):
    for phone,role in [(sys.argv[2],'employee'),(sys.argv[3],'admin')]:
        client=Client()
        assert client.post('/auth/login',{'phone':phone,'password':STRONG_PASSWORD},content_type='application/json').status_code==200
        assert client.get('/api/access/'+role).status_code==200
        assert client.get('/api/access/'+('admin' if role=='employee' else 'employee')).status_code==403
        assert client.get('/api/me').status_code==200
connection.close()
'''
    result=subprocess.run([sys.executable,'-c',code,target,employee.phone_normalized,admin.phone_normalized],
        cwd=settings.BASE_DIR,env=env,capture_output=True,timeout=30)
    if result.returncode:
        raise AssertionError('Restored database login/role verification failed; raw output suppressed')
    return True
