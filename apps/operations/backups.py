"""Encrypted pg_dump backups, verified delivery and isolated restore.

Only public age recipients are needed on the backup host. Decryption identities
belong on the recovery host. Raw dumps stream to age; restore authenticates the
entire file before a new database is created.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from psycopg import sql
from django.conf import settings
from django.db import connection

NAME = re.compile(r'tmdb-(\d{8}T\d{6}Z)-[0-9a-f]{32}\.dump\.age\Z')


class BackupError(Exception):
    """Only a stable error code is safe for terminal/log output."""


def tool(name):
    variable = 'TM_AGE_BIN' if name == 'age' else 'TM_PG_BIN'
    configured = os.environ.get(variable)
    if configured:
        path = Path(configured) if name == 'age' else Path(configured) / name
    else:
        preferred = settings.BASE_DIR / '.local/bin' / name if name == 'age' else Path('/opt/homebrew/opt/postgresql@17/bin') / name
        path = preferred if preferred.is_file() else Path(shutil.which(name) or preferred)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise BackupError('BACKUP_TOOL_UNAVAILABLE')
    return str(path)


def tool_environment():
    return {name: os.environ[name] for name in ['PATH', 'LANG', 'SYSTEMROOT'] if name in os.environ}


def database_environment():
    source = connection.settings_dict
    env = tool_environment()
    env.update(PGHOST=str(source['HOST']), PGPORT=str(source['PORT']), PGUSER=source['USER'],
               PGPASSWORD=source['PASSWORD'], PGCONNECT_TIMEOUT='10')
    options = source.get('OPTIONS', {})
    for option in ['sslmode', 'sslrootcert', 'sslcert', 'sslkey']:
        if option in options:
            env['PG' + option.upper()] = str(options[option])
    return env


def private_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise BackupError('BACKUP_DIRECTORY_INVALID')
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise BackupError('BACKUP_DIRECTORY_PERMISSIONS')
    return path


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def old_names(names, now, days):
    cutoff = now - timedelta(days=days)
    old = []
    for name in names:
        match = NAME.fullmatch(name)
        if match:
            try:
                at = datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if at < cutoff:
                old.append(name)
    return old


def checked(args, **kwargs):
    try:
        result = subprocess.run(args, capture_output=True, timeout=300, **kwargs)
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError('BACKUP_DELIVERY_FAILED') from None
    if result.returncode:
        raise BackupError('BACKUP_DELIVERY_FAILED')
    return result.stdout


class FileDestination:
    kind = 'filesystem'
    offsite_verified = False

    def __init__(self, path):
        self.path = private_directory(path)

    def deliver(self, archive, now, days):
        if self.path.resolve() == archive.parent.resolve():
            raise BackupError('BACKUP_DESTINATION_SAME_DIRECTORY')
        partial = self.path / ('.' + archive.name + '.partial')
        target = self.path / archive.name
        if target.exists():
            raise BackupError('BACKUP_DESTINATION_EXISTS')
        try:
            with partial.open('xb') as output:
                partial.chmod(0o600)
                with archive.open('rb') as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            if digest(partial) != digest(archive):
                raise BackupError('BACKUP_DELIVERY_CHECKSUM')
            # A hard link gives atomic no-overwrite publication on this filesystem.
            os.link(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        for name in old_names([p.name for p in self.path.iterdir() if p.is_file() and not p.is_symlink()], now, days):
            if name != archive.name:
                (self.path / name).unlink()


class SSHDestination:
    kind = 'ssh'
    offsite_verified = False  # Delivery is checked; physical failure domains are not inferred.

    def __init__(self, uri):
        parts = urlsplit(uri)
        try:
            port = parts.port or 22
        except ValueError:
            raise BackupError('BACKUP_DESTINATION_INVALID') from None
        if (parts.password or parts.query or parts.fragment or not parts.username or
                not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', parts.username) or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', parts.hostname or '') or
                not re.fullmatch(r'/[A-Za-z0-9_./-]+', parts.path) or parts.path == '/' or '..' in parts.path.split('/') or
                not 1 <= port <= 65535):
            raise BackupError('BACKUP_DESTINATION_INVALID')
        identity = Path(os.environ.get('BACKUP_SSH_IDENTITY_FILE', ''))
        hosts = Path(os.environ.get('BACKUP_SSH_KNOWN_HOSTS_FILE', ''))
        if not identity.is_file() or identity.is_symlink() or stat.S_IMODE(identity.stat().st_mode) != 0o600 or not hosts.is_file():
            raise BackupError('BACKUP_SSH_CREDENTIALS_INVALID')
        self.host = parts.username + '@' + parts.hostname
        self.path = parts.path.rstrip('/')
        self.port = str(port)
        self.options = ['-oBatchMode=yes', '-oStrictHostKeyChecking=yes', '-oIdentitiesOnly=yes',
                        '-oUserKnownHostsFile=' + str(hosts), '-i', str(identity)]

    def remote(self, *arguments):
        return checked(['ssh', *self.options, '-p', self.port, self.host, shlex.join(arguments)], env=tool_environment())

    def deliver(self, archive, now, days):
        self.remote('mkdir', '-m', '700', '-p', '--', self.path)
        # Do not silently loosen a shared destination's permissions.
        if self.remote('stat', '-c', '%a', '--', self.path).strip() != b'700':
            raise BackupError('BACKUP_DIRECTORY_PERMISSIONS')
        temporary = self.path + '/.' + archive.name + '.partial'
        final = self.path + '/' + archive.name
        checked(['scp', *self.options, '-P', self.port, str(archive), self.host + ':' + temporary], env=tool_environment())
        if self.remote('sha256sum', '--', temporary).split()[0].decode('ascii') != digest(archive):
            raise BackupError('BACKUP_DELIVERY_CHECKSUM')
        self.remote('ln', '--', temporary, final)
        self.remote('rm', '--', temporary)
        names = self.remote('find', self.path, '-maxdepth', '1', '-type', 'f', '-name', 'tmdb-*.dump.age', '-printf', '%f\n').decode().splitlines()
        for name in old_names(names, now, days):
            if name != archive.name:
                self.remote('rm', '--', self.path + '/' + name)


def destination(uri):
    if uri.startswith('file:///'):
        parts = urlsplit(uri)
        if parts.query or parts.fragment or parts.netloc:
            raise BackupError('BACKUP_DESTINATION_INVALID')
        return FileDestination(parts.path)
    if uri.startswith('ssh://'):
        return SSHDestination(uri)
    raise BackupError('BACKUP_DESTINATION_INVALID')


@contextmanager
def backup_lock(directory):
    path = directory / '.backup.lock'
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError('BACKUP_BUSY') from None
        yield


def create_backup(directory, recipient, destination_uri, retention_days=7, *, now=None):
    if not re.fullmatch(r'age1[a-z0-9]{20,200}', recipient or '') or not 1 <= retention_days <= 3650:
        raise BackupError('BACKUP_CONFIG_INVALID')
    directory = private_directory(directory)
    delivery = destination(destination_uri)
    if isinstance(delivery, FileDestination) and delivery.path.resolve() == directory.resolve():
        raise BackupError('BACKUP_DESTINATION_SAME_DIRECTORY')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise BackupError('BACKUP_CONFIG_INVALID')
    now = now.astimezone(timezone.utc)
    name = f'tmdb-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex}.dump.age'
    archive = directory / name
    with backup_lock(directory):
        with tempfile.TemporaryDirectory(prefix='.backup-', dir=directory) as temporary:
            partial = Path(temporary) / 'ciphertext.partial'
            processes = []
            try:
                with partial.open('xb') as output:
                    partial.chmod(0o600)
                    dump = subprocess.Popen([tool('pg_dump'), '--format=custom', '--no-owner', '--no-acl',
                        '--dbname', connection.settings_dict['NAME']], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=database_environment())
                    processes.append(dump)
                    encrypt = subprocess.Popen([tool('age'), '--encrypt', '--recipient', recipient], stdin=dump.stdout,
                        stdout=output, stderr=subprocess.DEVNULL, env=tool_environment())
                    processes.append(encrypt)
                    dump.stdout.close()
                    if encrypt.wait(timeout=1800) != 0 or dump.wait(timeout=30) != 0:
                        raise BackupError('BACKUP_ENCRYPT_OR_DUMP_FAILED')
                    output.flush()
                    os.fsync(output.fileno())
                os.link(partial, archive)
            except (OSError, subprocess.TimeoutExpired):
                raise BackupError('BACKUP_ENCRYPT_OR_DUMP_FAILED') from None
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
        try:
            delivery.deliver(archive, now, retention_days)
        except (OSError, ValueError, UnicodeError, IndexError):
            raise BackupError('BACKUP_DELIVERY_FAILED') from None
        for old in old_names([p.name for p in directory.iterdir() if p.is_file() and not p.is_symlink()], now, retention_days):
            if old != name:
                (directory / old).unlink()
        return {'status': 'completed', 'backup_id': name, 'ciphertext_bytes': archive.stat().st_size,
                'sha256': digest(archive), 'completed_at': datetime.now(timezone.utc).isoformat(),
                'destination_kind': delivery.kind, 'delivery_verified': True,
                'offsite_verified': delivery.offsite_verified, 'retention_days': retention_days}


def restore_backup(archive, identity, target):
    identity = Path(identity)
    if not re.fullmatch(r'tm_restore_[a-z0-9_]{1,48}', target) or target == connection.settings_dict['NAME']:
        raise BackupError('RESTORE_TARGET_INVALID')
    if not identity.is_file() or identity.is_symlink() or stat.S_IMODE(identity.stat().st_mode) != 0o600:
        raise BackupError('RESTORE_IDENTITY_PERMISSIONS')
    source = connection.get_connection_params()
    source.pop('dbname', None)
    source.pop('database', None)
    created = False
    with tempfile.TemporaryDirectory(prefix='tm-restore-') as temporary:
        dump = Path(temporary) / 'verified.dump'
        with dump.open('xb') as output:
            dump.chmod(0o600)
            try:
                result = subprocess.run([tool('age'), '--decrypt', '--identity', str(identity), '--', str(archive)],
                    stdout=output, stderr=subprocess.DEVNULL, env=tool_environment(), timeout=1800)
            except (OSError, subprocess.TimeoutExpired):
                raise BackupError('RESTORE_DECRYPT_FAILED') from None
        if result.returncode:
            raise BackupError('RESTORE_DECRYPT_FAILED')
        with psycopg.connect(dbname='postgres', autocommit=True, **source) as maintenance:
            try:
                if maintenance.execute('SELECT 1 FROM pg_database WHERE datname=%s', (target,)).fetchone():
                    raise BackupError('RESTORE_TARGET_EXISTS')
                maintenance.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
                created = True
                result = subprocess.run([tool('pg_restore'), '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                    '--dbname', target, str(dump)], env=database_environment(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800)
                if result.returncode:
                    raise BackupError('RESTORE_DATABASE_FAILED')
            except BaseException:
                if created:
                    maintenance.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(target)))
                raise
    return {'status': 'restored', 'database': target, 'workers_started': False}
