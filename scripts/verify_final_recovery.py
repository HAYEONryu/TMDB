"""Crash/restart only the owned final verification cluster and a synthetic app.

Run after run_final_verification.py test completes. Never targets an existing app.
"""
import json
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import quote
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_final_verification import DIRECTORY,PG,PORT
from tests.runtime_helpers import free_port,wait_http
from scripts.verification_evidence import RunRecord,write_new


def main(record):
    import psycopg
    from psycopg import sql
    password=json.loads((DIRECTORY/'state.json').read_text())['password']
    params={'host':'127.0.0.1','port':PORT,'user':'tm_final_test','password':password}
    name='test_tm_final_restart'
    # The cluster must be idle, owned by this task, and have no user databases.
    with psycopg.connect(dbname='postgres',autocommit=True,**params) as db:
        names={r[0] for r in db.execute('SELECT datname FROM pg_database')}
        if names-{'postgres','template0','template1'}:
            raise RuntimeError('Verification cluster is not idle; refusing to restart')
        db.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    env={k:v for k,v in os.environ.items() if not k.startswith('AI_')}
    env.update(DJANGO_SETTINGS_MODULE='config.test_settings',TM_PROCESS_ROLE='test',DJANGO_DEBUG='false',
        DJANGO_SECRET_KEY='synthetic-final-recovery-only',ALLOW_DEMO_SEED='false',
        DATABASE_URL=f'postgresql://tm_final_test:{quote(password,safe="")}@127.0.0.1:{PORT}/{name}')
    os.environ.update(env)
    import django
    django.setup()
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections
    from apps.customers.services import update_row
    from tests.test_p4 import Fixtures
    from tests.helpers import login
    from apps.ai_assistant.models import AIRequest,AIUsageAttempt
    server=None;db_up=True
    log=open(os.devnull,'w')
    report={}
    try:
        call_command('migrate',interactive=False,verbosity=0)
        fixture=Fixtures();fixture.prepare()
        customer=fixture.customers()[0];fixture.assign(customer)
        self_note='가상 장애 복구 확인'
        assert update_row(fixture.employee,fixture.mutation(customer,self_note))['ok']
        client=login(fixture.employee)
        cookie='sessionid='+client.cookies['sessionid'].value
        port=free_port();origin=f'http://127.0.0.1:{port}'
        def start():
            process=subprocess.Popen([str(ROOT/'.venv/bin/gunicorn'),'config.wsgi:application','--bind',f'127.0.0.1:{port}',
                '--workers','2','--worker-class','gthread','--threads','4'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            wait_http(origin+'/healthz',process)
            return process
        def check():
            request=urllib.request.Request(origin+'/api/customers?view=mine&site_id='+str(fixture.site.pk),headers={'Cookie':cookie})
            with urllib.request.urlopen(request,timeout=5) as response:
                data=json.loads(response.read())
            assert data['total']==1 and data['data'][0]['notes']==self_note
        server=start();check()
        connections.close_all()
        started=time.perf_counter()
        subprocess.run([str(PG/'pg_ctl'),'-D',str(DIRECTORY/'postgres'),'-m','immediate','-w','stop'],check=True,capture_output=True)
        db_up=False
        try:
            urllib.request.urlopen(origin+'/healthz',timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code==503
        else:
            raise AssertionError('Database interruption was not reported')
        subprocess.run([str(PG/'pg_ctl'),'-D',str(DIRECTORY/'postgres'),'-l',str(DIRECTORY/'postgres.log'),
            '-o',f'-p {PORT} -h 127.0.0.1 -k {DIRECTORY/"socket"}','-w','start'],check=True,capture_output=True)
        db_up=True
        wait_http(origin+'/healthz',server);check()
        report['database_crash_recovery_seconds']=round(time.perf_counter()-started,3)
        report['health_during_database_stop']=503
        report['database_wal_recovery_and_session_data_preserved']=True
        os.killpg(server.pid,signal.SIGKILL);server.wait(timeout=15)
        server=None
        started=time.perf_counter();server=start();check()
        report['app_restart_seconds']=round(time.perf_counter()-started,3)
        report['app_group_sigkill_and_restart_preserves_session_data']=True
        assert AIRequest.objects.count()==AIUsageAttempt.objects.count()==0
        report.update(synthetic_data_only=True,external_ai_requests=0,original_databases_accessed=False,
            scope='owned local cluster crash and short recovery; production HA/SLA not certified')
    finally:
        if server and server.poll() is None:
            os.killpg(server.pid,signal.SIGTERM);server.wait(timeout=15)
        log.close();connections.close_all()
        if not db_up:
            subprocess.run([str(PG/'pg_ctl'),'-D',str(DIRECTORY/'postgres'),'-l',str(DIRECTORY/'postgres.log'),
                '-o',f'-p {PORT} -h 127.0.0.1 -k {DIRECTORY/"socket"}','-w','start'],check=True,capture_output=True)
        with psycopg.connect(dbname='postgres',autocommit=True,**params) as db:
            db.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
    report['temporary_database_removed']=True
    write_new(record.path/'results.json',report)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',default='recovery')
    args=parser.parse_args()
    record=RunRecord(args.label,['python','scripts/verify_final_recovery.py'])
    code=1
    try:
        main(record);code=0
    except Exception as error:
        record.event('recovery_failed',exception_type=type(error).__name__)
    finally:
        record.finish(code)
        print(json.dumps({'run_id':record.run_id,'exit_code':code,'directory':str(record.path)}))
    raise SystemExit(code)
