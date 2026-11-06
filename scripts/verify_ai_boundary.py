"""Read-only Git/Compose audit; never read or print actual AI key values.

Docker context and image-layer checks require an actual engine run. Static ignore
rules and a successful Compose parse deliberately do not satisfy those checks.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_acceptance import source_digest


def run(*args, **kwargs):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=30, **kwargs)
    return result


def audit(root=ROOT):
    checks = {}
    paths = ['.env.ai', 'secrets/example.key', 'backups/example.dump', 'nested/.env.ai']
    ignored = run('git', 'check-ignore', '--no-index', '--stdin', input='\n'.join(paths) + '\n')
    tracked = run('git', 'ls-files', '-z')
    example = run('git', 'check-ignore', '--no-index', '.env.ai.example')
    assert ignored.returncode == 0 and set(ignored.stdout.splitlines()) == set(paths), 'GIT_SECRET_IGNORE_FAILED'
    assert tracked.returncode == 0 and not any(Path(p).name == '.env.ai' or 'secrets' in Path(p).parts
           for p in tracked.stdout.split('\0') if p), 'GIT_SECRET_TRACKED'
    assert example.returncode == 1, 'GIT_EXAMPLE_IGNORED'
    path = root / '.env.ai'
    assert not path.exists() or stat.S_IMODE(path.stat().st_mode) == 0o600, 'AI_FILE_PERMISSIONS'
    # Read only the distributable empty example, never the real key file.
    values = dict(line.split('=', 1) for line in (root / '.env.ai.example').read_text().splitlines()
                  if line and not line.startswith('#') and '=' in line)
    assert values.get('AI_API_KEY') == '' and values.get('AI_ENABLED') == 'false', 'AI_EXAMPLE_NOT_EMPTY_DISABLED'
    checks['git_secret_boundary'] = {'status': 'passed', 'ignored_paths_checked': len(paths),
                                     'key_file_present': path.exists(), 'real_key_file_read': False}
    rules = (root / '.dockerignore').read_text().splitlines()
    assert all(rule in rules for rule in ['.env', '.env.*', '!.env.ai.example', 'secrets/', 'backups/', '.local', '.git']), 'DOCKER_IGNORE_RULE_MISSING'
    checks['docker_ignore_rules'] = {'status': 'passed', 'scope': 'static rules only; not actual build-context evidence'}
    compose = shutil.which('docker-compose') or str(root / '.local/bin/docker-compose')
    # --no-env-resolution prevents opening .env.ai. Drop inherited AI variables.
    environment = {k: v for k, v in os.environ.items() if not k.startswith('AI_')}
    result = run(compose, '--profile', 'ai', '--profile', 'proxy', 'config', '--no-env-resolution',
                 '--no-interpolate', '--format', 'json', env=environment)
    assert result.returncode == 0, 'COMPOSE_PARSE_FAILED'
    services = json.loads(result.stdout)['services']
    assert set(services) == {'postgres', 'web', 'scheduler', 'proxy', 'ai_worker'}, 'COMPOSE_SERVICE_MISMATCH'
    for name, service in services.items():
        files = [Path(value['path'] if isinstance(value, dict) else value).name for value in service.get('env_file', [])]
        assert ('.env.ai' in files) == (name in {'web', 'ai_worker'}), 'COMPOSE_SECRET_SCOPE'
        assert not any(k.startswith('AI_') for k in service.get('environment', {})), 'COMPOSE_INLINE_AI_SECRET'
    checks['compose_secret_boundary'] = {'status': 'passed', 'services_checked': len(services),
                                         'ai_env_services': ['web', 'ai_worker'], 'ai_env_resolved': False}
    reason = 'Docker 엔진/CLI가 없어 실제 build context·이미지·각 레이어/history 검사를 실행하지 못함.'
    if shutil.which('docker'):
        reason = 'Docker CLI는 있지만 실제 build context·이미지·각 레이어/history 검증 증거는 아직 없음.'
    for name in ['docker_build_context', 'docker_image_layers']:
        checks[name] = {'status': 'not_run', 'reason': reason}
    return {'finished_at': datetime.now(timezone.utc).isoformat(), 'source_digest': source_digest(root), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='.local/p12-boundary.json')
    args = parser.parse_args()
    report = audit()
    path = ROOT / args.output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: row['status'] for name, row in report['checks'].items()}))
    return 0 if all(c['status'] == 'passed' for c in report['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
