"""Restore the existing app secret from a running container, without displaying it.

Only .env is changed. No container is restarted and no database/API is accessed.
Requires the source container to belong to the same Compose configuration.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
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
import io, json, os, re, sys, tempfile
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
reference = os.environ.get('TM_RECOVERY_REFERENCE_VARIABLE', '')
if reference and not re.fullmatch(r'(?:[A-Z][A-Z0-9_]*_)?(?:SECRET|SECRET_KEY)', reference):
    raise RuntimeError('REFERENCE_VARIABLE_INVALID')
fields = list(dict.fromkeys(['DJANGO_SECRET_KEY'] + ([reference] if reference else [])))
if reference and before.get(reference) not in (None, '', key):
    sys.stdout.write(json.dumps({'error': 'REFERENCE_VARIABLE_HAS_DIFFERENT_VALUE'}))
    sys.exit(0)
with tempfile.TemporaryDirectory(prefix='tmdb-secret-') as directory:
    path = Path(directory) / 'app.env'
    path.write_text(original, encoding='utf-8')
    path.chmod(0o600)
    # Compose treats backslashes in single quotes literally; python-dotenv's
    # quote writer escapes them for its own parser. Prefer a representation
    # that preserves the key in both parsers, and verify Python's reading too.
    literal = "'" + key.replace("'", "\\'") + "'"
    for field in fields:
        set_key(str(path), field, literal, quote_mode='never')
        if dotenv_values(path, interpolate=False).get(field) != key:
            set_key(str(path), field, key, quote_mode='always')
    updated = path.read_text(encoding='utf-8')
after = dotenv_values(stream=io.StringIO(updated), interpolate=False)
if any(after.get(field) != key for field in fields):
    raise RuntimeError('ENV_ENCODING_FAILED')
for field in fields:
    before.pop(field, None)
    after.pop(field, None)
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


def environment_values(raw):
    """Compose preserves KEY=value lists when interpolation is disabled."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        result = {}
        for item in raw:
            name, separator, value = item.partition('=')
            result[name] = value if separator else None
        return result
    raise RecoveryError('COMPOSE_ENVIRONMENT_FORMAT_INVALID')


def reference_variable(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\$\{([A-Za-z_][A-Za-z0-9_]*)(?:[-:+?].*)?\}|\$([A-Za-z_][A-Za-z0-9_]*)', value, re.S)
    return next((name for name in match.groups() if name), None) if match else None


def compose_keys(root, files, run):
    output = run(['docker', 'compose', *sum((['-f', str(p)] for p in files), []),
                  '--profile', 'ai', 'config', '--format', 'json'], root=root)
    try:
        services = json.loads(output)['services']
        values = {name: environment_values(services[name].get('environment')).get('DJANGO_SECRET_KEY')
                  for name in ('web', 'scheduler', 'ai_worker')}
        # Compose serializes literal dollars as $$ so its config can be loaded
        # again. Compare the decoded value, never the serialized representation.
        return {name: value.replace('$$', '$') if isinstance(value, str) else value
                for name, value in values.items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RecoveryError('COMPOSE_CONFIG_INVALID') from None


def diagnose(root, *, run=private_command):
    """Read config shape only; never extract a key or change any file."""
    root = Path(root).resolve()
    files = [root / 'compose.yaml', root / 'compose.server.yaml']
    if any(not path.is_file() for path in files):
        raise RecoveryError('PROJECT_COMPOSE_FILE_MISSING')
    output = run(['docker', 'compose', *sum((['-f', str(p)] for p in files), []),
                  '--profile', 'ai', 'config', '--format', 'json',
                  '--no-env-resolution', '--no-interpolate'], root=root)
    try:
        services = json.loads(output)['services']
        safe = {}
        for name in ('web', 'scheduler', 'ai_worker'):
            service = services[name]
            values = environment_values(service.get('environment'))
            key = 'DJANGO_SECRET_KEY'
            value = values.get(key)
            state = ('absent' if key not in values else 'empty_or_inherited' if not value
                     else 'variable_expression' if '$' in str(value) else 'value_hidden')
            paths = service.get('env_file') or []
            paths = paths if isinstance(paths, list) else [paths]
            env_files = []
            for item in paths:
                path = item if isinstance(item, str) else item['path']
                path = Path(path)
                resolved = (root / path).resolve()
                env_files.append({'name': path.name, 'project_env': resolved == root / '.env'})
            safe[name] = {'key_setting': state, 'reference_variable': reference_variable(value), 'env_files': env_files}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RecoveryError('COMPOSE_CONFIG_INVALID') from None
    key = 'DJANGO_SECRET_KEY'
    shell = 'unset' if key not in os.environ else 'empty' if not os.environ[key] else 'set_hidden'
    return {'status': 'diagnostic_only', 'shell_key': shell,
            'custom_compose_env_files': bool(os.environ.get('COMPOSE_ENV_FILES')),
            'default_env_disabled': os.environ.get('COMPOSE_DISABLE_ENV_FILE', '').lower() in {'1', 'true'},
            'services': safe, 'writes_performed': False}


def replace_private(path, data, owner):
    fd, temporary = tempfile.mkstemp(prefix='.env.recovery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.chown(temporary, owner.st_uid, owner.st_gid)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def recover(root, source, *, run=private_command, reference=None):
    if reference and not re.fullmatch(r'(?:[A-Z][A-Z0-9_]*_)?(?:SECRET|SECRET_KEY)', reference):
        raise RecoveryError('REFERENCE_VARIABLE_INVALID')
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
        if reference:
            config = diagnose(root, run=run)
            if any(service['reference_variable'] != reference for service in config['services'].values()):
                raise RecoveryError('REFERENCE_VARIABLE_DOES_NOT_MATCH_COMPOSE')
        original = env.read_bytes()
        try:
            recovered = json.loads(run(['docker', 'exec', '-i', '-e',
                                       'TM_RECOVERY_REFERENCE_VARIABLE=' + (reference or ''),
                                       source, 'python', '-c', SOURCE_SCRIPT],
                                       root=root, input=original.decode('utf-8')))
            if recovered.get('error') == 'REFERENCE_VARIABLE_HAS_DIFFERENT_VALUE':
                raise RecoveryError('REFERENCE_VARIABLE_HAS_DIFFERENT_VALUE')
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
                **({'reference_variable': reference} if reference else {}),
                'database_changed': False, 'services_restarted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-container')
    parser.add_argument('--diagnose', action='store_true', help='Read-only, value-free Compose diagnostics')
    parser.add_argument('--reference-variable', help='Explicit secret variable referenced by all three services')
    args = parser.parse_args()
    if not args.diagnose and not args.source_container:
        parser.error('--source-container is required for recovery')
    try:
        root = Path(__file__).resolve().parents[1]
        result = diagnose(root) if args.diagnose else recover(root, args.source_container, reference=args.reference_variable)
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
