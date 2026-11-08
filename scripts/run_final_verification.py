"""Local synthetic verification on an owned, isolated PostgreSQL cluster.

Never reads AI credentials or connects to the development/demo databases.
No package installation, hosting, or external AI requests are performed.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verification_evidence import RunRecord,write_new
DIRECTORY = ROOT / '.local/final-test'
PG = Path('/opt/homebrew/opt/postgresql@17/bin')
PORT = '55435'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'test', 'stop', 'check'])
    parser.add_argument('--label', default='integration')
    parser.add_argument('--database-name', help='Deprecated: each run owns a unique test database')
    parser.add_argument('labels', nargs='*')
    args = parser.parse_args()
    DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = DIRECTORY / 'postgres'
    socket = DIRECTORY / 'socket'
    socket.mkdir(exist_ok=True, mode=0o700)
    state = DIRECTORY / 'state.json'
    if not state.exists():
        state.write_text(json.dumps({'password': secrets.token_urlsafe(32)}))
        state.chmod(0o600)
    password = json.loads(state.read_text())['password']
    if args.action == 'start':
        if not (data / 'PG_VERSION').exists():
            pw = DIRECTORY / 'init-password'
            pw.write_text(password)
            pw.chmod(0o600)
            try:
                subprocess.run([str(PG/'initdb'), '-D', str(data), '--username=tm_final_test',
                    '--encoding=UTF8', '--no-locale', '--auth-local=trust', '--auth-host=scram-sha-256',
                    '--pwfile='+str(pw)], check=True, stdout=subprocess.DEVNULL)
            finally:
                pw.unlink(missing_ok=True)
        status = subprocess.run([str(PG/'pg_ctl'), '-D', str(data), 'status'], capture_output=True)
        if status.returncode == 3:
            subprocess.run([str(PG/'pg_ctl'), '-D', str(data), '-l', str(DIRECTORY/'postgres.log'),
                '-o', f'-p {PORT} -h 127.0.0.1 -k {socket}', '-w', 'start'], check=True)
        elif status.returncode:
            raise RuntimeError('Test cluster status unavailable')
        print('Isolated verification PostgreSQL ready on 127.0.0.1:55435')
        return 0
    if args.action == 'stop':
        return subprocess.run([str(PG/'pg_ctl'), '-D', str(data), '-m', 'fast', '-w', 'stop']).returncode
    env = {k: v for k, v in os.environ.items() if not k.startswith('AI_')}
    if args.database_name:
        raise ValueError('Shared database names are forbidden; omit --database-name')
    env.update(DJANGO_SETTINGS_MODULE='config.test_settings', TM_PROCESS_ROLE='test',
        DATABASE_URL=f'postgresql://tm_final_test:{quote(password,safe="")}@127.0.0.1:{PORT}/postgres',
        DJANGO_SECRET_KEY='synthetic-final-verification-only',
        DJANGO_DEBUG='false', ALLOW_DEMO_SEED='false',
        PLAYWRIGHT_BROWSERS_PATH=str(ROOT/'.cache/ms-playwright'))
    if args.action == 'check':
        record=RunRecord(args.label,['python','scripts/run_final_verification.py','check'])
        code=1;checks={}
        try:
            for name,command in [('system_check',['check']),('migration_drift',['makemigrations','--check','--dry-run'])]:
                result=subprocess.run([sys.executable,'manage.py',*command],cwd=ROOT,env=env,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                checks[name]={'exit_code':result.returncode,'status':'passed' if result.returncode==0 else 'failed'}
            code=0 if all(c['status']=='passed' for c in checks.values()) else 1
            write_new(record.path/'results.json',{'checks':checks})
            return code
        finally:
            record.finish(code)
            print(json.dumps({'run_id':record.run_id,'exit_code':code,'directory':str(record.path)}))
    labels = args.labels or ['tests', *['tests.'+p.stem for pattern in ['browser_*.py', 'performance_*.py']
        for p in sorted((ROOT/'tests').glob(pattern))]]
    import re
    if any(not re.fullmatch(r'tests(?:\.[A-Za-z_]\w*)*',name) for name in labels):
        raise ValueError('Only public tests module/class/method identifiers are allowed')
    command = [sys.executable, 'manage.py', 'test', *labels, '--noinput', '-v', '2',
        '--testrunner=config.acceptance_runner.AcceptanceRunner', '--evidence-label=final']
    record=RunRecord(args.label,['python',*command[1:]])
    env.update(TM_EVIDENCE_RUN_DIR=str(record.path),TEST_DATABASE_NAME='test_tm_final_'+record.run_id[-24:])
    code=1
    try:
        # Raw unittest/Django output may contain assertions, request payloads,
        # cookies or synthetic secrets. Only allowlisted structured logs persist.
        result = subprocess.run(command,cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        code=result.returncode
        return code
    finally:
        record.finish(code)
        print(json.dumps({'run_id':record.run_id,'exit_code':code,'directory':str(record.path)}))


if __name__ == '__main__':
    raise SystemExit(main())
