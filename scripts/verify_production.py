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
    if len(web_files) != 2 or paths(web_files) != paths(ai_files) or paths(scheduler_files) != paths(web_files[:1]):
        raise ValueError('PRODUCTION_AI_FILE_SCOPE')
    for name in ['web','scheduler','ai_worker']:
        if services[name]['environment'].get('DJANGO_SETTINGS_MODULE') != 'config.production_settings':
            raise ValueError('PRODUCTION_SETTINGS_REQUIRED')
    files = paths(web_files) + [config['secrets']['db_password']['file']]
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
