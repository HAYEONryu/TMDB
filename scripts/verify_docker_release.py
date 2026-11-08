"""Actual local Docker checks, or explicit not_run. Never deploys remotely.

The build context is a separate allowlist copy; real .env/.env.ai are never read.
Only generated synthetic credentials are mounted. The test network is internal.
"""
import argparse
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verification_evidence import RunRecord,write_new
from scripts.verify_acceptance import source_digest

CHECKS=['docker_build_context','docker_image_layers','docker_history','compose_runtime','fresh_migrations',
        'static_files','permissions','restart_persistence','ai_disabled_no_external_io','logs_no_markers']
ALLOWED_DIRS=['apps','config','scripts','static','templates','tests','deploy']
ALLOWED_FILES=['Dockerfile','.dockerignore','.env.example','.env.ai.example','manage.py','gunicorn.conf.py',
               'requirements.lock','pyproject.toml','uv.lock']


def stage_context(destination):
    destination=Path(destination);destination.mkdir(mode=0o700)
    for name in ALLOWED_FILES:shutil.copy2(ROOT/name,destination/name)
    for name in ALLOWED_DIRS:
        shutil.copytree(ROOT/name,destination/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.pem','*.key'),symlinks=True)
    if any(p.is_symlink() for p in destination.rglob('*')):
        raise RuntimeError('BUILD_CONTEXT_SYMLINK_FORBIDDEN')
    markers=[]
    for name in ['.env','.env.ai','nested/.env.ai','secrets/sentinel.key','backups/sentinel.dump',
                 '.aws/credentials','.codex/credentials','outputs/customer.csv','customer-private.pem']:
        marker='TM_EXCLUDE_SENTINEL_'+secrets.token_hex(24);markers.append(marker.encode())
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(marker);path.chmod(0o600)
    return markers


def scan_archive(path,markers):
    """Inspect every saved layer, including files removed by a later layer."""
    matched=False;forbidden=[];layers=0
    def scan(stream):
        tail=b''
        while chunk:=stream.read(1024*1024):
            data=tail+chunk
            if any(value in data for value in markers):return True
            tail=data[-256:]
        return False
    with tarfile.open(path,'r:*') as archive:
        try:layer_names={name for item in json.load(archive.extractfile('manifest.json')) for name in item['Layers']}
        except (KeyError,ValueError,TypeError):layer_names=set()
        for member in archive:
            if not member.isfile():continue
            if member.name.endswith('layer.tar') or member.name in layer_names:
                layers+=1
                with tarfile.open(fileobj=archive.extractfile(member),mode='r|*') as layer:
                    for entry in layer:
                        clean=entry.name.removeprefix('./')
                        if clean.startswith('app/'):
                            relative=Path(clean).relative_to('app')
                            if relative.name in {'.env','.env.ai','credentials'} or any(p in {'secrets','backups','.aws','.codex'} for p in relative.parts):forbidden.append(clean)
                        if entry.isfile():matched=scan(layer.extractfile(entry)) or matched
            else:matched=scan(archive.extractfile(member)) or matched
    return {'marker_matches':int(matched),'forbidden_paths':len(forbidden),'layers_scanned':layers}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label',default='docker-stage1')
    args=parser.parse_args()
    record=RunRecord(args.label,['python','scripts/verify_docker_release.py','--label',args.label])
    report={'run_id':record.run_id,'source_digest':source_digest(ROOT),'checks':{k:{'status':'not_run'} for k in CHECKS},
        'actual_docker_executed':False,'public_https_verified':False,'real_secrets_read':False}
    docker=shutil.which('docker')
    # A remote Docker context would deploy containers on another server.
    if not docker:
        report['reason']='LOCAL_DOCKER_CLI_AND_ENGINE_UNAVAILABLE'
        write_new(record.path/'results.json',report);record.finish(2,status='not_run',reason=report['reason'])
        print(json.dumps({'run_id':record.run_id,'status':'not_run','reason':report['reason'],'directory':str(record.path)}));return 2
    env={k:v for k,v in os.environ.items() if not k.startswith('AI_')}
    code=1;compose=None;work=None;project='tmverify'+record.run_id[-16:];runtime_markers=[]
    def command(*args,input=None,timeout=180):
        result=subprocess.run([docker,*args],env=env,cwd=ROOT,input=input,capture_output=True,timeout=timeout)
        # Never persist stdout/stderr: docker inspect/config/logs can contain env.
        record.event('docker_command',operation=args[0],exit_code=result.returncode)
        if result.returncode:raise RuntimeError('DOCKER_COMMAND_FAILED')
        return result.stdout
    def compose_command(*args,**kwargs):return command(*compose,*args,**kwargs)
    def passed(key):report['checks'][key]={'status':'passed'}
    try:
        if env.get('DOCKER_HOST') and not env['DOCKER_HOST'].startswith('unix://'):raise RuntimeError('REMOTE_DOCKER_FORBIDDEN')
        context=json.loads(command('context','inspect'))[0]
        if not context['Endpoints']['docker']['Host'].startswith('unix://'):raise RuntimeError('REMOTE_DOCKER_FORBIDDEN')
        command('info','--format','{{json .ServerVersion}}')
        report['actual_docker_executed']=True
        temp=tempfile.mkdtemp(prefix='tm-docker-stage1-',dir=ROOT/'.local')
        work=Path(temp);context_dir=work/'context';markers=stage_context(context_dir)
        runtime_markers=[secrets.token_urlsafe(42) for _ in range(3)]
        bootstrap,app_password,ai_marker=runtime_markers
        app_secret=secrets.token_urlsafe(64);runtime_markers.append(app_secret)
        marker_bytes=markers+[v.encode() for v in runtime_markers]
        tag='tmdb-stage1:'+record.run_id[-24:]
        # COPY . in a scratch stage proves Docker's filtered context, rather
        # than merely inspecting .dockerignore text.
        probe=work/'Context.Dockerfile';probe.write_text('FROM scratch\nCOPY . /app/\n')
        command('build','-f',str(probe),'-t',tag+'-context',str(context_dir),timeout=900)
        probe_archive=work/'context.tar';command('save','-o',str(probe_archive),tag+'-context',timeout=300)
        check=scan_archive(probe_archive,markers)
        if check['marker_matches'] or check['forbidden_paths'] or not check['layers_scanned']:raise RuntimeError('BUILD_CONTEXT_SECRET_PRESENT')
        passed('docker_build_context')
        command('build','--label','io.tm.source.sha256='+report['source_digest'],'--label',
            'org.opencontainers.image.revision='+json.loads((record.path/'started.json').read_text())['code_version']['git_head'],
            '-t',tag,str(context_dir),timeout=1200)
        image=json.loads(command('image','inspect',tag))[0];image_id=image['Id']
        report.update(image_id=image_id,image_repo_digests=image.get('RepoDigests',[]),image_platform=image.get('Architecture'))
        archive=record.path/'application-image.tar'
        command('save','-o',str(archive),image_id,timeout=300);archive.chmod(0o600)
        check=scan_archive(archive,marker_bytes)
        if check['marker_matches'] or check['forbidden_paths'] or not check['layers_scanned']:raise RuntimeError('IMAGE_LAYER_SECRET_PRESENT')
        with archive.open('rb') as handle:report['image_archive_sha256']=hashlib.file_digest(handle,'sha256').hexdigest()
        passed('docker_image_layers')
        history=command('history','--no-trunc',image_id)
        if any(m in history for m in marker_bytes):raise RuntimeError('IMAGE_HISTORY_SECRET_PRESENT')
        passed('docker_history')
        # Runtime secrets live on private named volumes with correct Linux
        # UIDs, never in the build context/image or docker command arguments.
        volume=project+'-secrets';command('volume','create',volume)
        payload={'ai':f'AI_ENABLED=false\nAI_PROVIDER=gemini\nAI_MODEL=gemini-3.5-flash-lite\nAI_USAGE_TIER=free\nAI_FREE_TIER_CONFIRMED=false\nAI_GEMINI_API_KEY={ai_marker}\n',
            'db':bootstrap,'app_db':app_password}
        provision="import json,sys,os;from pathlib import Path;d=json.load(sys.stdin);p=Path('/runtime');[(p/n).mkdir(exist_ok=True) for n in ['ai','db']];[( (p/f).write_text(d[k]),os.chmod(p/f,0o600),os.chown(p/f,u,u)) for f,k,u in [('ai/.env.ai','ai',10001),('db/db_password','db',999),('db/app_db_password','app_db',999)]]"
        command('run','--rm','--network','none','--user','0','--mount',f'type=volume,source={volume},target=/runtime','-i',image_id,
            'python','-c',provision,input=json.dumps(payload).encode())
        app_env=work/'app.env';app_env.write_text(f'DJANGO_SECRET_KEY={app_secret}\nDJANGO_DEBUG=false\nALLOW_DEMO_SEED=false\nDATABASE_URL=postgresql://tm_app:{app_password}@postgres:5432/tm\nAPP_TIMEZONE=Asia/Seoul\n');app_env.chmod(0o600)
        dummy=work/'unused';dummy.write_text('unused');dummy.chmod(0o600)
        from tests.runtime_helpers import free_port
        port=free_port()
        caddy=work/'Caddyfile';caddy.write_text('{\n admin off\n}\nhttp://tm-verify.local {\n reverse_proxy web:8000 {\n header_up X-Forwarded-Proto https\n }\n}\n')
        override=work/'override.yaml'
        override.write_text(f'''services:
  postgres:
secrets: !reset []
volumes:
  - {volume}:/run/secrets:ro
  web:
volumes: !override [{volume}:/run/verification-secrets:ro]
environment:
  AI_ENV_FILE: /run/verification-secrets/ai/.env.ai
  ai_worker:
volumes: !override [{volume}:/run/verification-secrets:ro]
environment:
  AI_ENV_FILE: /run/verification-secrets/ai/.env.ai
  proxy:
ports: !override ["127.0.0.1:{port}:80"]
volumes: !override ["{caddy}:/etc/caddy/Caddyfile:ro"]
volumes:
  {volume}:
external: true
networks:
  default:
internal: true
'''.replace(f'{volume}:/run/secrets:ro',f'{volume}:/run/verification-secrets:ro'))
        # DB files are in a /db subdirectory of this volume.
        text=override.read_text().replace('    secrets: !reset []','    secrets: !reset []\n    environment:\n      POSTGRES_PASSWORD_FILE: /run/verification-secrets/db/db_password\n      TM_APP_DB_PASSWORD_FILE: /run/verification-secrets/db/app_db_password')
        override.write_text(text)
        env.update(APP_DOMAIN='tm-verify.local',TM_APP_IMAGE=image_id,TM_APP_ENV_FILE=str(app_env),
            TM_AI_ENV_FILE=str(dummy),TM_DB_PASSWORD_FILE=str(dummy),TM_APP_DB_PASSWORD_FILE=str(dummy))
        compose=['compose','-p',project,'-f',str(ROOT/'deploy/compose.production.yaml'),'-f',str(override),'--profile','ai']
        # Use an explicit init password path for the verification volume.
        compose_command('up','-d','--wait','postgres',timeout=180)
        compose_command('run','--rm','--no-deps','web','python','manage.py','migrate','--noinput')
        compose_command('run','--rm','--no-deps','web','python','manage.py','migrate','--check');passed('fresh_migrations')
        seed="from apps.accounts.models import User;from apps.sites.services import create_site;from apps.customers.models import Customer;u=User.objects.create_user('01099770001','가상 Docker 관리자','Synthetic!Only2026',role='ADMIN',must_change_password=False);s=create_site(u,'가상 Docker 현장')[0];Customer.objects.create(site=s,customer_name='가상고객',phone_normalized='01099779999',notes='SYNTHETIC_PERSISTENCE')"
        compose_command('run','--rm','--no-deps','web','python','manage.py','shell','-c',seed)
        compose_command('up','-d','--wait',timeout=180);passed('compose_runtime')
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=10)
        for path in ['/healthz','/static/app.css']:
            conn.request('GET',path,headers={'Host':'tm-verify.local'});response=conn.getresponse();response.read()
            if response.status!=200:raise RuntimeError('WEB_STATIC_HEALTH_FAILED')
        conn.close();passed('static_files')
        verify="from django.db import connection;from apps.customers.models import Customer;from apps.ai_assistant.models import AIRequest,AIUsageAttempt;from django.conf import settings;import os,stat;from pathlib import Path;assert Customer.objects.get().notes=='SYNTHETIC_PERSISTENCE';assert not AIRequest.objects.exists() and not AIUsageAttempt.objects.exists();assert os.getuid()==10001;assert not settings.DEBUG;assert not settings.AI_CONFIG.enabled;assert not settings.AI_CONFIG.free_tier_confirmed;f=Path('/run/verification-secrets/ai/.env.ai');assert stat.S_IMODE(f.stat().st_mode)==0o600;assert f.stat().st_uid==10001;assert f.read_text();c=connection.cursor();c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user');assert c.fetchone()==(False,False,False,False)"
        # manage.py shell has the management role; key loading is checked
        # independently in the worker role by its --once invocation.
        compose_command('exec','-T','web','python','manage.py','shell','-c',verify);passed('permissions')
        compose_command('exec','-T','ai_worker','python','manage.py','run_ai_worker','--once');passed('ai_disabled_no_external_io')
        compose_command('restart',timeout=180)
        compose_command('up','-d','--wait',timeout=180)
        compose_command('exec','-T','web','python','manage.py','shell','-c',verify)
        compose_command('stop',timeout=120);compose_command('up','-d','--wait',timeout=180)
        compose_command('exec','-T','web','python','manage.py','shell','-c',verify);passed('restart_persistence')
        logs=compose_command('logs','--no-color')
        if any(m in logs for m in marker_bytes):raise RuntimeError('RUNTIME_LOG_SECRET_PRESENT')
        passed('logs_no_markers')
        report['source_unchanged']=report['source_digest']==source_digest(ROOT)
        if not report['source_unchanged']:raise RuntimeError('SOURCE_CHANGED_DURING_DOCKER_RUN')
        code=0
    except Exception as error:
        report['reason']=str(error) if type(error) is RuntimeError and re.fullmatch('[A-Z_]+',str(error)) else type(error).__name__
    finally:
        if compose:
            try:compose_command('down','--volumes','--remove-orphans',timeout=180)
            except Exception:report['cleanup_failed']=True;code=1
        if docker and report['actual_docker_executed']:
            subprocess.run([docker,'volume','rm',project+'-secrets'],env=env,capture_output=True)
        if work:shutil.rmtree(work)
        write_new(record.path/'results.json',report);record.finish(code)
        print(json.dumps({'run_id':record.run_id,'exit_code':code,'directory':str(record.path)}))
    return code


if __name__=='__main__':raise SystemExit(main())
