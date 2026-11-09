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
from urllib.parse import urlsplit, unquote


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
desired = {'DJANGO_SECRET_KEY': key}
if reference:
    desired[reference] = key
if reference and before.get(reference) not in (None, '', key):
    sys.stdout.write(json.dumps({'error': 'REFERENCE_VARIABLE_HAS_DIFFERENT_VALUE'}))
    sys.exit(0)
db_reference = os.environ.get('TM_RECOVERY_DB_PASSWORD_VARIABLE', '')
database = None
if db_reference:
    if not re.fullmatch(r'(?:[A-Z][A-Z0-9_]*_)?PASSWORD', db_reference):
        raise RuntimeError('DATABASE_PASSWORD_VARIABLE_INVALID')
    db = settings.DATABASES['default']
    password = db.get('PASSWORD') or os.environ.get('PGPASSWORD')
    if db.get('ENGINE') != 'django.db.backends.postgresql' or not isinstance(password, str) or not password:
        sys.stdout.write(json.dumps({'error': 'SOURCE_DATABASE_PASSWORD_UNAVAILABLE'}))
        sys.exit(0)
    if before.get(db_reference) not in (None, '', password):
        sys.stdout.write(json.dumps({'error': 'DATABASE_PASSWORD_VARIABLE_HAS_DIFFERENT_VALUE'}))
        sys.exit(0)
    desired[db_reference] = password
    database = {'host': str(db.get('HOST') or '').lower(), 'port': str(db.get('PORT') or '5432'),
                'name': str(db.get('NAME') or ''), 'user': str(db.get('USER') or ''), 'password': password}
with tempfile.TemporaryDirectory(prefix='tmdb-secret-') as directory:
    path = Path(directory) / 'app.env'
    path.write_text(original, encoding='utf-8')
    path.chmod(0o600)
    # Compose treats backslashes in single quotes literally; python-dotenv's
    # quote writer escapes them for its own parser. Prefer a representation
    # that preserves the key in both parsers, and verify Python's reading too.
    for field, value in desired.items():
        literal = "'" + value.replace("'", "\\'") + "'"
        set_key(str(path), field, literal, quote_mode='never')
        if dotenv_values(path, interpolate=False).get(field) != value:
            set_key(str(path), field, value, quote_mode='always')
    updated = path.read_text(encoding='utf-8')
after = dotenv_values(stream=io.StringIO(updated), interpolate=False)
if any(after.get(field) != value for field, value in desired.items()):
    raise RuntimeError('ENV_ENCODING_FAILED')
for field in desired:
    before.pop(field, None)
    after.pop(field, None)
if before != after:
    raise RuntimeError('OTHER_SETTINGS_CHANGED')
sys.stdout.write(json.dumps({'secret': key, 'updated': updated, 'database': database}))
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


def compose_environments(root, files, run):
    output = run(['docker', 'compose', *sum((['-f', str(p)] for p in files), []),
                  '--profile', 'ai', 'config', '--format', 'json'], root=root)
    try:
        services = json.loads(output)['services']
        values = {name: environment_values(services[name].get('environment'))
                  for name in ('web', 'scheduler', 'ai_worker')}
        # Compose serializes literal dollars as $$ so its config can be loaded
        # again. Compare the decoded value, never the serialized representation.
        return {name: {field: value.replace('$$', '$') if isinstance(value, str) else value
                       for field, value in env.items()} for name, env in values.items()}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise RecoveryError('COMPOSE_CONFIG_INVALID') from None


def compose_keys(root, files, run):
    return {name: env.get('DJANGO_SECRET_KEY') for name, env in compose_environments(root, files, run).items()}


def database_signature(value):
    try:
        url = urlsplit(value or '')
        if url.scheme not in {'postgres', 'postgresql'}:
            raise ValueError()
        return {'host': (url.hostname or '').lower(), 'port': str(url.port or 5432),
                'name': unquote(url.path.removeprefix('/')), 'user': unquote(url.username or ''),
                'password': unquote(url.password or '')}
    except (ValueError, TypeError, AttributeError):
        raise RecoveryError('DATABASE_URL_FORMAT_UNSUPPORTED') from None


def verify_databases(environments, expected, *, allow_missing_password=False):
    matching = True
    for env in environments.values():
        actual = database_signature(env.get('DATABASE_URL'))
        if any(actual[field] != expected[field] for field in ('host', 'port', 'name', 'user')):
            raise RecoveryError('DATABASE_TARGET_MISMATCH')
        if actual['password'] != expected['password']:
            if allow_missing_password and not actual['password']:
                matching = False
            else:
                raise RecoveryError('DATABASE_PASSWORD_MISMATCH')
    return matching


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
            try:
                password = urlsplit(str(values.get('DATABASE_URL') or '')).password or ''
            except ValueError:
                password = ''
            safe[name] = {'key_setting': state, 'reference_variable': reference_variable(value),
                          'database_password_variable': reference_variable(password), 'env_files': env_files}
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


def recover(root, source, *, run=private_command, reference=None, database_password_variable=None):
    if reference and not re.fullmatch(r'(?:[A-Z][A-Z0-9_]*_)?(?:SECRET|SECRET_KEY)', reference):
        raise RecoveryError('REFERENCE_VARIABLE_INVALID')
    if database_password_variable and not re.fullmatch(r'(?:[A-Z][A-Z0-9_]*_)?PASSWORD', database_password_variable):
        raise RecoveryError('DATABASE_PASSWORD_VARIABLE_INVALID')
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
        if reference or database_password_variable:
            config = diagnose(root, run=run)
            if reference and any(service['reference_variable'] != reference for service in config['services'].values()):
                raise RecoveryError('REFERENCE_VARIABLE_DOES_NOT_MATCH_COMPOSE')
            if database_password_variable and any(service['database_password_variable'] != database_password_variable for service in config['services'].values()):
                raise RecoveryError('DATABASE_PASSWORD_VARIABLE_DOES_NOT_MATCH_COMPOSE')
        original = env.read_bytes()
        try:
            recovered = json.loads(run(['docker', 'exec', '-i', '-e',
                                       'TM_RECOVERY_REFERENCE_VARIABLE=' + (reference or ''),
                                       '-e', 'TM_RECOVERY_DB_PASSWORD_VARIABLE=' + (database_password_variable or ''),
                                       source, 'python', '-c', SOURCE_SCRIPT],
                                       root=root, input=original.decode('utf-8')))
            error = recovered.get('error')
            if error in {'REFERENCE_VARIABLE_HAS_DIFFERENT_VALUE','SOURCE_DATABASE_PASSWORD_UNAVAILABLE','DATABASE_PASSWORD_VARIABLE_HAS_DIFFERENT_VALUE'}:
                raise RecoveryError(error)
            key, updated = recovered['secret'], recovered['updated'].encode('utf-8')
            if not isinstance(key, str) or not key or not updated:
                raise ValueError()
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
            raise RecoveryError('SOURCE_SECRET_UNAVAILABLE') from None
        environments = compose_environments(root, files, run)
        current = {name: values.get('DJANGO_SECRET_KEY') for name, values in environments.items()}
        database = recovered.get('database') if database_password_variable else None
        if database_password_variable and (not isinstance(database, dict) or not database.get('password')):
            raise RecoveryError('SOURCE_DATABASE_PASSWORD_UNAVAILABLE')
        database_matches = verify_databases(environments, database, allow_missing_password=True) if database else True
        if all(value == key for value in current.values()) and database_matches:
            return {'status': 'already_configured', 'services_verified': list(current),
                    **({'database_password_variable': database_password_variable, 'database_settings_match_source': True}
                       if database_password_variable else {})}
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
            verified_environments = compose_environments(root, files, run)
            verified = {name: values.get('DJANGO_SECRET_KEY') for name, values in verified_environments.items()}
            if not all(value == key for value in verified.values()):
                states = {name: 'matches_existing' if value == key else 'missing' if not value else 'different'
                          for name, value in verified.items()}
                raise RecoveryError('COMPOSE_SECRET_OVERRIDE_CHECK_FAILED', details={'services': states})
            if database:
                verify_databases(verified_environments, database)
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
                **({'database_password_variable': database_password_variable, 'database_settings_match_source': True}
                   if database_password_variable else {}),
                'database_changed': False, 'services_restarted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-container')
    parser.add_argument('--diagnose', action='store_true', help='Read-only, value-free Compose diagnostics')
    parser.add_argument('--reference-variable', help='Explicit secret variable referenced by all three services')
    parser.add_argument('--database-password-variable', help='Explicit URL password variable referenced by all three services')
    args = parser.parse_args()
    if not args.diagnose and not args.source_container:
        parser.error('--source-container is required for recovery')
    try:
        root = Path(__file__).resolve().parents[1]
        result = diagnose(root) if args.diagnose else recover(root, args.source_container, reference=args.reference_variable,
                                                            database_password_variable=args.database_password_variable)
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
