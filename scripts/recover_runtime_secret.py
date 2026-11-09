"""Restore the existing app secret from a running container, without displaying it.

Only .env is changed. No container is restarted and no database/API is accessed.
Requires the source container to belong to the same Compose configuration.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from uuid import uuid4


class RecoveryError(Exception):
    def __init__(self, code, *, details=None):
        super().__init__(code)
        self.details = details


# Runs in the OLD container. Django settings resolves exactly the key already
# used by that application. Neither settings setup nor dotenv performs I/O to DB/AI.
SOURCE_SCRIPT = r'''
import io, json, os, sys, tempfile
from pathlib import Path
os.environ['TM_PROCESS_ROLE'] = 'management'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.conf import settings
from dotenv import dotenv_values, set_key
key = settings.SECRET_KEY
if not isinstance(key, str) or not key:
    raise RuntimeError('SOURCE_SECRET_UNAVAILABLE')
original = sys.stdin.read()
before = dotenv_values(stream=io.StringIO(original), interpolate=False)
with tempfile.TemporaryDirectory(prefix='tmdb-secret-') as directory:
    path = Path(directory) / 'app.env'
    path.write_text(original, encoding='utf-8')
    path.chmod(0o600)
    # Compose treats backslashes in single quotes literally; python-dotenv's
    # quote writer escapes them for its own parser. Prefer a representation
    # that preserves the key in both parsers, and verify Python's reading too.
    literal = "'" + key.replace("'", "\\'") + "'"
    set_key(str(path), 'DJANGO_SECRET_KEY', literal, quote_mode='never')
    if dotenv_values(path, interpolate=False).get('DJANGO_SECRET_KEY') != key:
        set_key(str(path), 'DJANGO_SECRET_KEY', key, quote_mode='always')
    updated = path.read_text(encoding='utf-8')
after = dotenv_values(stream=io.StringIO(updated), interpolate=False)
if after.get('DJANGO_SECRET_KEY') != key:
    raise RuntimeError('ENV_ENCODING_FAILED')
before.pop('DJANGO_SECRET_KEY', None)
after.pop('DJANGO_SECRET_KEY', None)
if before != after:
    raise RuntimeError('OTHER_SETTINGS_CHANGED')
sys.stdout.write(json.dumps({'secret': key, 'updated': updated}))
'''


def private_command(args, *, root, input=None):
    try:
        result = subprocess.run(args, cwd=root, input=input, text=True,
                                capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError('DOCKER_COMMAND_UNAVAILABLE') from None
    if result.returncode:
        # Never echo Docker output, resolved config, environment or exceptions.
        raise RecoveryError('DOCKER_COMMAND_FAILED')
    return result.stdout


def compose_keys(root, files, run):
    output = run(['docker', 'compose', *sum((['-f', str(p)] for p in files), []),
                  '--profile', 'ai', 'config', '--format', 'json'], root=root)
    try:
        services = json.loads(output)['services']
        values = {name: services[name].get('environment', {}).get('DJANGO_SECRET_KEY')
                  for name in ('web', 'scheduler', 'ai_worker')}
        # Compose serializes literal dollars as $$ so its config can be loaded
        # again. Compare the decoded value, never the serialized representation.
        return {name: value.replace('$$', '$') if isinstance(value, str) else value
                for name, value in values.items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RecoveryError('COMPOSE_CONFIG_INVALID') from None


def replace_private(path, data, owner):
    fd, temporary = tempfile.mkstemp(prefix='.env.recovery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.chown(temporary, owner.st_uid, owner.st_gid)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def recover(root, source, *, run=private_command):
    root = Path(root).resolve()
    files = [root / 'compose.yaml', root / 'compose.server.yaml']
    env = root / '.env'
    if any(not path.is_file() for path in files) or env.is_symlink() or not env.is_file():
        raise RecoveryError('PROJECT_ENV_OR_COMPOSE_FILE_MISSING')
    owner = env.stat()
    if not stat.S_ISREG(owner.st_mode):
        raise RecoveryError('ENV_NOT_REGULAR_FILE')
    local = root / '.local'
    if local.is_symlink():
        raise RecoveryError('UNSAFE_LOCAL_DIRECTORY')
    local.mkdir(mode=0o700, exist_ok=True)
    lock_fd = os.open(local / 'runtime-secret-recovery.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryError('RECOVERY_ALREADY_RUNNING') from None
        label = run(['docker', 'inspect', source, '--format',
                     '{{ index .Config.Labels "com.docker.compose.project.config_files" }}'], root=root).strip()
        if {str(Path(p).resolve()) for p in label.split(',')} != {str(p) for p in files}:
            raise RecoveryError('SOURCE_COMPOSE_PROJECT_MISMATCH')
        original = env.read_bytes()
        try:
            recovered = json.loads(run(['docker', 'exec', '-i', source, 'python', '-c', SOURCE_SCRIPT],
                                       root=root, input=original.decode('utf-8')))
            key, updated = recovered['secret'], recovered['updated'].encode('utf-8')
            if not isinstance(key, str) or not key or not updated:
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
            raise RecoveryError('SOURCE_SECRET_UNAVAILABLE') from None
        current = compose_keys(root, files, run)
        if all(value == key for value in current.values()):
            return {'status': 'already_configured', 'services_verified': list(current)}
        if any(value and value != key for value in current.values()):
            raise RecoveryError('EXISTING_DIFFERENT_SECRET_NOT_REPLACED')
        directory = local / ('runtime-secret-recovery-' + uuid4().hex)
        directory.mkdir(mode=0o700)
        backup = directory / 'app.env.before'
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(original); handle.flush(); os.fsync(handle.fileno())
        if env.read_bytes() != original:
            raise RecoveryError('ENV_CHANGED_DURING_RECOVERY')
        replace_private(env, updated, owner)
        try:
            verified = compose_keys(root, files, run)
            if not all(value == key for value in verified.values()):
                states = {name: 'matches_existing' if value == key else 'missing' if not value else 'different'
                          for name, value in verified.items()}
                raise RecoveryError('COMPOSE_SECRET_OVERRIDE_CHECK_FAILED', details={'services': states})
        except RecoveryError as exc:
            if env.read_bytes() != updated:
                raise RecoveryError('ENV_CHANGED_RESTORE_BACKUP_MANUALLY') from None
            replace_private(env, original, owner)
            env.chmod(stat.S_IMODE(owner.st_mode))
            raise RecoveryError('VERIFY_FAILED_ORIGINAL_ENV_RESTORED',
                                details=exc.details or {'reason': str(exc)}) from None
        return {'status': 'restored_existing_secret', 'services_verified': list(verified),
                'backup': str(backup.relative_to(root)), 'env_permissions': '0600',
                'database_changed': False, 'services_restarted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-container', required=True)
    args = parser.parse_args()
    try:
        result = recover(Path(__file__).resolve().parents[1], args.source_container)
    except RecoveryError as exc:
        print(json.dumps({'status': 'stopped', 'code': str(exc),
                          **({'details': exc.details} if exc.details else {})}))
        return 1
    except Exception:
        print(json.dumps({'status': 'stopped', 'code': 'RECOVERY_FAILED_NO_DETAILS'}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
