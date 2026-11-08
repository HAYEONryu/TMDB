"""Preflight production Compose without reading app/AI/password file contents."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def validate(config):
    services = config['services']
    if set(services) != {'postgres','web','scheduler','ai_worker','proxy'}:
        raise ValueError('PRODUCTION_SERVICES_INVALID')
    if {name for name, value in services.items() if value.get('ports')} != {'proxy'}:
        raise ValueError('PRODUCTION_BACKEND_PUBLIC_PORT')
    for service in services.values():
        if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', service['image']):
            raise ValueError('PRODUCTION_IMAGE_DIGEST_REQUIRED')
    web_files = services['web']['env_file']
    ai_files = services['ai_worker']['env_file']
    scheduler_files = services['scheduler']['env_file']
    paths = lambda rows: [row['path'] for row in rows]
    if len(web_files) != 1 or paths(web_files) != paths(ai_files) or paths(scheduler_files) != paths(web_files):
        raise ValueError('PRODUCTION_AI_FILE_SCOPE')
    ai_paths=[]
    for name, service in services.items():
        mounts=[v for v in service.get('volumes',[]) if v.get('target')=='/run/ai/.env.ai']
        if name in {'web','ai_worker'}:
            if len(mounts)!=1 or not mounts[0].get('read_only') or service['environment'].get('AI_ENV_FILE')!='/run/ai/.env.ai':
                raise ValueError('PRODUCTION_AI_FILE_SCOPE')
            ai_paths.append(mounts[0]['source'])
        elif mounts:raise ValueError('PRODUCTION_AI_FILE_SCOPE')
        if any(k in service.get('environment',{}) for k in ['AI_API_KEY','AI_GEMINI_API_KEY']):
            raise ValueError('PRODUCTION_INLINE_AI_SECRET')
    if len(set(ai_paths))!=1:raise ValueError('PRODUCTION_AI_FILE_SCOPE')
    for name in ['web','scheduler','ai_worker']:
        if services[name]['environment'].get('DJANGO_SETTINGS_MODULE') != 'config.production_settings':
            raise ValueError('PRODUCTION_SETTINGS_REQUIRED')
    database_files=[config['secrets'][name]['file'] for name in ['db_password','app_db_password']]
    if Path(database_files[0]).resolve()==Path(database_files[1]).resolve():
        raise ValueError('PRODUCTION_DATABASE_SECRET_SEPARATION')
    files = paths(web_files) + ai_paths[:1] + database_files
    for value in files:
        path = Path(value)
        if (not path.is_absolute() or path.is_symlink() or not path.is_file() or
                stat.S_IMODE(path.stat().st_mode) != 0o600 or path.resolve().is_relative_to(ROOT)):
            raise ValueError('PRODUCTION_SECRET_FILE_INVALID')
    return {'immutable_image_digests':True,'backend_ports_private':True,'secret_files_0600_outside_checkout':True,
            'ai_env_web_worker_only':True,'runtime_verified':False,'public_https_verified':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    args = parser.parse_args()
    if not args.env_file.is_file() or stat.S_IMODE(args.env_file.stat().st_mode) != 0o600:
        raise SystemExit('PRODUCTION_ENV_FILE_PERMISSIONS')
    compose = shutil.which('docker-compose') or str(ROOT/'.local/bin/docker-compose')
    env = {k:v for k,v in os.environ.items() if not k.startswith('AI_')}
    result = subprocess.run([compose,'--env-file',str(args.env_file),'-f','deploy/compose.production.yaml',
        '--profile','ai','config','--no-env-resolution','--format','json'],cwd=ROOT,env=env,capture_output=True,text=True,timeout=30)
    if result.returncode:
        raise SystemExit('PRODUCTION_COMPOSE_INVALID')
    try:
        report = validate(json.loads(result.stdout))
    except (ValueError, KeyError, OSError, TypeError):
        raise SystemExit('PRODUCTION_PREFLIGHT_FAILED') from None
    print(json.dumps(report))


if __name__ == '__main__':
    main()
