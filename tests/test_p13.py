"""Operational backup/restore and deployment checks; all data and keys are synthetic."""
from scripts.verification_evidence import artifact_path

from datetime import datetime, timedelta, timezone as dt_timezone
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.ai_assistant.models import (AIRequest, AIResultSource, AIUsageAttempt, AIQuotaBucket,
    AIBudgetMonth, AIReportSlot, AIReportSnapshot, AINoteClassification, GuidePublication, SiteKnowledge)
from apps.ai_assistant.services import reserve
from apps.ai_assistant.worker import claim, finish, run_once
from apps.common.transactions import business_write
from apps.ai_assistant.privacy import invalidate_results
from apps.consultations.models import ConsultationRevision
from apps.customers.services import update_row
from apps.operations.backups import (BackupError, FileDestination, SSHDestination, backup_lock,
    create_backup, destination, digest, restore_backup, tool_environment)
from tests.helpers import TEST_HASHERS, STRONG_PASSWORD, login
from tests.test_backup import table_snapshot
from tests.restored_login import verify_restored_login
from tests.test_p4 import Fixtures
from tests.test_p9 import TEST_AI


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_CONFIG=TEST_AI, AI_FOUNDATION_TEST_MODE=True)
class P13BackupTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.assertTrue(settings.TESTING and connection.settings_dict['NAME'].startswith('test_tm_'))
        self.prepare()
        directory = tempfile.TemporaryDirectory(prefix='tm-p13-backup-', dir='/private/tmp')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.local = self.root / 'staging'
        self.remote = self.root / 'separate-store'
        self.identity = self.root / 'identity.txt'
        result = subprocess.run([str(settings.BASE_DIR / '.local/bin/age-keygen'), '-o', str(self.identity)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.identity.chmod(0o600)
        self.recipient = subprocess.run([str(settings.BASE_DIR / '.local/bin/age-keygen'), '-y', str(self.identity)], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        source = connection.settings_dict
        self.params = {'host': source['HOST'], 'port': source['PORT'], 'user': source['USER'], 'password': source['PASSWORD']}

    def populated(self):
        customer = self.customers()[0]
        self.assign(customer)
        row = self.mutation(customer, '가격 비교 후 다시 연락 요청')
        row['changes']['callback_due_at'] = (timezone.now() + timedelta(days=1)).isoformat()
        self.assertTrue(update_row(self.employee, row)['ok'])
        customer.refresh_from_db()
        body = {'feature': 'CLEANUP', 'customer_id': str(customer.pk), 'assignment_id': str(customer.current_assignment_id),
                'expected_version': customer.version, 'idempotency_key': str(uuid4())}
        cleanup, _ = reserve(self.employee, body)
        self.assertEqual(run_once()['succeeded'], 1)
        cleanup.refresh_from_db()
        self.assertTrue(update_row(self.employee, {**self.mutation(customer),
            'changes': {'notes': cleanup.result.payload['suggestions']['notes']['value']},
            'source_ai_result_id': str(cleanup.result.pk)})['ok'])
        SiteKnowledge.objects.create(site=self.site, title='가상 검토 자료', body='예약 전 담당자 확인이 필요합니다.',
            reviewed_by=self.admin, reviewed_at=timezone.now(), is_valid=True)
        for feature in ['EMPLOYEE_COACHING', 'TEAM_GUIDE']:
            scope = {'employee_id': str(self.employee.pk)} if feature == 'EMPLOYEE_COACHING' else {'site_id': str(self.site.pk)}
            task, _ = reserve(self.admin, {'feature': feature, **scope, 'idempotency_key': str(uuid4())})
            self.assertEqual(run_once()['succeeded'], 1)
            task.refresh_from_db()
            if feature == 'EMPLOYEE_COACHING':
                coaching = task
            else:
                client = login(self.admin)
                response = client.patch(f'/api/ai/guides/{task.result.pk}', {'expected_version': task.result.guide_version,
                    'reviewed': True, 'body': task.result.guide_body, 'idempotency_key': str(uuid4())}, content_type='application/json')
                self.assertEqual(response.status_code, 200)
                task.result.refresh_from_db()
                self.assertEqual(client.post(f'/api/ai/guides/{task.result.pk}/publish', {'expected_version': task.result.guide_version,
                    'idempotency_key': str(uuid4())}, content_type='application/json').status_code, 200)
                AIResultSource.objects.create(result=task.result, previous_result=coaching.result)
        second = self.customers(site=self.second, offset=2)[0]
        self.assign(second, self.other)
        second.notes = '무효화 검사용 가짜 원문'
        second.save()
        invalid, _ = reserve(self.other, {**body, 'feature': 'SUMMARY', 'customer_id': str(second.pk),
            'assignment_id': str(second.current_assignment_id), 'expected_version': second.version, 'idempotency_key': str(uuid4())})
        self.assertEqual(run_once()['succeeded'], 1)
        with business_write():
            invalidate_results([invalid.result.pk])
        pending, _ = reserve(self.other, {**body, 'feature': 'NEXT_QUESTIONS', 'customer_id': str(second.pk),
            'assignment_id': str(second.current_assignment_id), 'expected_version': second.version, 'idempotency_key': str(uuid4())})
        running = claim()
        self.assertEqual(running.pk, pending.pk)
        finish(running.pk, running.lease_token, outcome='unknown')
        self.assertTrue(AIReportSnapshot.objects.exists())
        self.assertTrue(AINoteClassification.objects.exists())
        self.assertEqual(GuidePublication.objects.count(), 1)
        self.assertTrue(ConsultationRevision.objects.filter(source='AI_APPLIED').exists())
        return invalid

    def test_encrypted_populated_ai_backup_restores_every_table_and_relations(self):
        invalid = self.populated()
        report = create_backup(self.local, self.recipient, self.remote.as_uri())
        archive = self.remote / report['backup_id']
        self.assertEqual(report['status'], 'completed')
        self.assertFalse(report['offsite_verified'])
        self.assertEqual(digest(archive), digest(self.local / archive.name))
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        self.assertTrue(archive.read_bytes().startswith(b'age-encryption.org/v1'))
        target = 'tm_restore_p13_' + uuid4().hex
        started = perf_counter()
        with psycopg.connect(dbname='postgres', autocommit=True, **self.params) as maintenance:
            try:
                result = restore_backup(archive, self.identity, target)
                self.assertEqual(result['status'], 'restored')
                with psycopg.connect(dbname=connection.settings_dict['NAME'], autocommit=True, **self.params) as source, psycopg.connect(dbname=target, autocommit=True, **self.params) as restored:
                    before = table_snapshot(source)
                    self.assertEqual(table_snapshot(restored), before)
                    self.assertEqual(restored.execute('SELECT count(*) FROM ai_assistant_guidepublication').fetchone()[0], 1)
                    self.assertEqual(restored.execute('SELECT valid,payload FROM ai_assistant_airesult WHERE id=%s', (invalid.result.pk,)).fetchone(), (False, {}))
                    self.assertGreater(restored.execute('SELECT reserved_usd FROM ai_assistant_aibudgetmonth').fetchone()[0], 0)
                    self.assertGreater(restored.execute('SELECT charged_usd FROM ai_assistant_aibudgetmonth').fetchone()[0], 0)
                    self.assertEqual(restored.execute("SELECT count(*) FROM ai_assistant_airequest WHERE status='UNKNOWN'").fetchone()[0], 1)
                    self.assertGreater(restored.execute('SELECT count(*) FROM ai_assistant_airesultsource WHERE previous_result_id IS NOT NULL').fetchone()[0], 0)
                    restored.execute('DELETE FROM django_session')
                    self.assertTrue(verify_restored_login(target,self.employee,self.admin))
                    self.assertEqual(table_snapshot(source), before)
            finally:
                maintenance.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(target)))
        evidence = {'encryption': 'age 1.3.2', 'ciphertext_bytes': report['ciphertext_bytes'], 'all_tables_match': True,
                    'tables': before, 'populated_ai_tables': [name for name, value in before.items() if name.startswith('ai_assistant_') and value['rows']],
                    'restore_seconds': round(perf_counter() - started, 3),
                    'restored_login_and_role_routes': True,
                    'source_unchanged_after_replica_write': True, 'offsite_verified': False, 'temporary_database_removed': True}
        (artifact_path('p13-encrypted-restore.json')).write_text(json.dumps(evidence, ensure_ascii=False, indent=2))

    def test_tampered_or_wrong_key_never_creates_restore_database(self):
        self.customers()
        report = create_backup(self.local, self.recipient, self.remote.as_uri())
        archive = self.remote / report['backup_id']
        corrupted = self.root / 'corrupt.age'
        data = bytearray(archive.read_bytes())
        data[-1] ^= 1
        corrupted.write_bytes(data)
        wrong = self.root / 'wrong.txt'
        subprocess.run([str(settings.BASE_DIR / '.local/bin/age-keygen'), '-o', str(wrong)], capture_output=True, check=True)
        wrong.chmod(0o600)
        for source, identity in [(corrupted, self.identity), (archive, wrong)]:
            target = 'tm_restore_bad_' + uuid4().hex
            with self.assertRaisesRegex(BackupError, 'RESTORE_DECRYPT_FAILED'):
                restore_backup(source, identity, target)
            with psycopg.connect(dbname='postgres', autocommit=True, **self.params) as maintenance:
                self.assertIsNone(maintenance.execute('SELECT 1 FROM pg_database WHERE datname=%s', (target,)).fetchone())

    def test_restore_refuses_existing_target_and_unsafe_name(self):
        report = create_backup(self.local, self.recipient, self.remote.as_uri())
        archive = self.remote / report['backup_id']
        with self.assertRaisesRegex(BackupError, 'RESTORE_TARGET_INVALID'):
            restore_backup(archive, self.identity, connection.settings_dict['NAME'])
        target = 'tm_restore_existing_' + uuid4().hex
        with psycopg.connect(dbname='postgres', autocommit=True, **self.params) as maintenance:
            maintenance.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(target)))
            try:
                with self.assertRaisesRegex(BackupError, 'RESTORE_TARGET_EXISTS'):
                    restore_backup(archive, self.identity, target)
                self.assertIsNotNone(maintenance.execute('SELECT 1 FROM pg_database WHERE datname=%s', (target,)).fetchone())
            finally:
                maintenance.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))

    def test_delivery_failure_never_reports_success_or_prunes_old_backup(self):
        self.local.mkdir(mode=0o700)
        old = self.local / ('tmdb-20200101T000000Z-' + uuid4().hex + '.dump.age')
        old.write_bytes(b'test-only prior encrypted backup')
        output = io.StringIO()
        with patch.object(FileDestination, 'deliver', side_effect=BackupError('BACKUP_DELIVERY_FAILED')):
            with self.assertRaises(CommandError):
                call_command('backup_database', directory=str(self.local), recipient=self.recipient,
                             destination=self.remote.as_uri(), stdout=output)
        self.assertTrue(old.exists())
        self.assertEqual(output.getvalue(), '')
        self.assertFalse(list(self.local.glob('.backup-*')))

    def test_retention_only_prunes_completed_named_backups_after_delivery(self):
        self.local.mkdir(mode=0o700)
        self.remote.mkdir(mode=0o700)
        for directory in [self.local, self.remote]:
            (directory / ('tmdb-20200101T000000Z-' + 'a'*32 + '.dump.age')).write_bytes(b'old encrypted fixture')
            (directory / 'operator-notes.txt').write_text('keep')
            (directory / '.partial').write_text('keep')
        report = create_backup(self.local, self.recipient, self.remote.as_uri())
        for directory in [self.local, self.remote]:
            self.assertEqual([p.name for p in directory.glob('*.dump.age')], [report['backup_id']])
            self.assertTrue((directory / 'operator-notes.txt').exists())
            self.assertTrue((directory / '.partial').exists())

    def test_concurrent_backup_and_insecure_directories_are_rejected(self):
        self.local.mkdir(mode=0o700)
        with backup_lock(self.local):
            with self.assertRaisesRegex(BackupError, 'BACKUP_BUSY'):
                create_backup(self.local, self.recipient, self.remote.as_uri())
        self.local.chmod(0o755)
        with self.assertRaisesRegex(BackupError, 'BACKUP_DIRECTORY_PERMISSIONS'):
            create_backup(self.local, self.recipient, self.remote.as_uri())

    def test_dump_failure_never_publishes_archive(self):
        with patch('apps.operations.backups.tool', side_effect=lambda name: '/usr/bin/false' if name == 'pg_dump' else str(settings.BASE_DIR / '.local/bin/age')):
            with self.assertRaisesRegex(BackupError, 'BACKUP_ENCRYPT_OR_DUMP_FAILED'):
                create_backup(self.local, self.recipient, self.remote.as_uri())
        self.assertFalse(list(self.local.glob('*.age')))
        self.assertFalse(list(self.remote.glob('*.age')))

    def test_invalid_dump_restore_removes_only_its_new_database(self):
        archive=self.root/'invalid-dump.age'
        with archive.open('wb') as output:
            subprocess.run([str(settings.BASE_DIR/'.local/bin/age'),'--encrypt','--recipient',self.recipient],
                input=b'synthetic authenticated data that is not a PostgreSQL dump',stdout=output,stderr=subprocess.PIPE,check=True,timeout=10)
        target='tm_restore_invalid_'+uuid4().hex
        with self.assertRaisesRegex(BackupError,'RESTORE_DATABASE_FAILED'):
            restore_backup(archive,self.identity,target)
        with psycopg.connect(dbname='postgres',autocommit=True,**self.params) as maintenance:
            self.assertIsNone(maintenance.execute('SELECT 1 FROM pg_database WHERE datname=%s',(target,)).fetchone())


class P13DeploymentTests(SimpleTestCase):
    def production(self, **values):
        env = {k: v for k, v in os.environ.items() if not k.startswith('AI_')}
        env.update(DJANGO_SETTINGS_MODULE='config.production_settings', APP_DOMAIN='tm.example.com',
                   DJANGO_SECRET_KEY=secrets.token_urlsafe(64), DJANGO_DEBUG='false', ALLOW_DEMO_SEED='false',
                   DATABASE_URL='postgresql://synthetic:synthetic-only-database-password@127.0.0.1:55432/not_accessed')
        env.update(values)
        return subprocess.run([sys.executable, 'manage.py', 'check', '--deploy', '--fail-level', 'ERROR'], cwd=settings.BASE_DIR,
                              env=env, capture_output=True, text=True, timeout=15)

    def test_production_passes_django_deployment_checks(self):
        result = self.production()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        # Domain-only one-hour HSTS is deliberate; broad preload requires domain review.
        self.assertIn('security.W005', result.stderr)
        self.assertIn('security.W021', result.stderr)

    def test_production_rejects_demo_debug_weak_key_and_invalid_domain(self):
        for values in [{'DJANGO_DEBUG': 'true'}, {'ALLOW_DEMO_SEED': 'true'}, {'DJANGO_SECRET_KEY': 'fake'},
                {'APP_DOMAIN': 'https://tm.example.com'}, {'DATABASE_URL': 'postgresql://tm:tm-local-only@localhost/tm'}]:
            self.assertNotEqual(self.production(**values).returncode, 0)

    def test_production_rejects_bootstrap_database_account_with_strong_password(self):
        self.assertNotEqual(self.production(DATABASE_URL='postgresql://tm:synthetic-strong-database-password@127.0.0.1:55432/not_accessed').returncode,0)

    def test_production_compose_has_only_proxy_public_ports_and_ai_file_scope(self):
        env = {**os.environ, 'APP_DOMAIN': 'tm.example.com', 'TM_APP_IMAGE': 'example/tmdb@sha256:' + 'a'*64,
               'TM_APP_ENV_FILE': '/private/tmp/p13-app.env', 'TM_AI_ENV_FILE': '/private/tmp/p13-ai.env',
               'TM_DB_PASSWORD_FILE': '/private/tmp/p13-db-password',
               'TM_APP_DB_PASSWORD_FILE':'/private/tmp/p13-app-db-password'}
        result = subprocess.run([str(settings.BASE_DIR / '.local/bin/docker-compose'), '-f', 'deploy/compose.production.yaml',
            '--profile', 'ai', 'config', '--no-env-resolution', '--format', 'json'], cwd=settings.BASE_DIR, env=env,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, 'production Compose parse failed')
        services = json.loads(result.stdout)['services']
        self.assertEqual({name for name, value in services.items() if value.get('ports')}, {'proxy'})
        for name, value in services.items():
            files = [Path(row['path']).name for row in value.get('env_file', [])]
            self.assertNotIn('p13-ai.env', files)
            mounts=[v for v in value.get('volumes',[]) if v.get('target')=='/run/ai/.env.ai']
            self.assertEqual(bool(mounts),name in ['web','ai_worker'])
            if mounts:self.assertTrue(mounts[0]['read_only'])
        self.assertNotIn('POSTGRES_PASSWORD', services['postgres']['environment'])

    def test_production_caddy_adapts_https_and_overwrites_forwarded_protocol(self):
        result=subprocess.run([str(settings.BASE_DIR/'.local/bin/caddy'),'adapt','--config','deploy/Caddyfile','--adapter','caddyfile'],
            cwd=settings.BASE_DIR,env={**os.environ,'APP_DOMAIN':'tm.example.com'},capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0)
        config=json.loads(result.stdout)
        server=next(iter(config['apps']['http']['servers'].values()))
        self.assertIn(':443',server['listen'])
        self.assertIn('X-Forwarded-Proto',result.stdout)
        self.assertIn('{http.request.scheme}',result.stdout)

    def test_ssh_destination_rejects_password_injection_and_missing_host_keys(self):
        for uri in ['ssh://user:password@host/backup', 'ssh://user@host/../root', 'ssh://user@host/a;touch', 'ssh://user@host/backup']:
            with self.assertRaises(BackupError):
                destination(uri)
        with patch.dict(os.environ, {'AI_API_KEY': 'SYNTHETIC_ONLY', 'PGPASSWORD': 'SYNTHETIC_DB'}):
            self.assertNotIn('AI_API_KEY', tool_environment())
            self.assertNotIn('PGPASSWORD', tool_environment())

    def test_ssh_delivery_requires_strict_host_key_and_remote_checksum(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            root = Path(directory)
            identity = root / 'ssh-key'; identity.write_text('synthetic-key'); identity.chmod(0o600)
            hosts = root / 'known_hosts'; hosts.write_text('synthetic-host')
            archive = root / ('tmdb-20261106T000000Z-' + 'a'*32 + '.dump.age'); archive.write_bytes(b'encrypted fixture')
            with patch.dict(os.environ, {'BACKUP_SSH_IDENTITY_FILE': str(identity), 'BACKUP_SSH_KNOWN_HOSTS_FILE': str(hosts)}):
                delivery = SSHDestination('ssh://backup@host.example.com/store')
                self.assertIn('-oStrictHostKeyChecking=yes', delivery.options)
                def remote(*args):
                    if args[0] == 'stat': return b'700\n'
                    if args[0] == 'sha256sum': return b'wrong-checksum  file\n'
                    return b''
                with patch.object(delivery, 'remote', side_effect=remote) as calls, patch('apps.operations.backups.checked'):
                    with self.assertRaisesRegex(BackupError, 'BACKUP_DELIVERY_CHECKSUM'):
                        delivery.deliver(archive, datetime.now(dt_timezone.utc), 7)
                    self.assertNotIn('ln', [call.args[0] for call in calls.call_args_list])

    def test_preflight_rejects_mutable_images_and_public_backend_ports(self):
        from scripts.verify_production import validate
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            root=Path(directory)
            files=[]
            for name in ['app.env','ai.env','db-password','app-db-password']:
                path=root/name;path.write_text('synthetic only');path.chmod(0o600);files.append(str(path))
            env={'DJANGO_SETTINGS_MODULE':'config.production_settings'}
            pinned='example/tmdb@sha256:'+'a'*64
            config={'services':{name:{'image':pinned} for name in ['postgres','web','scheduler','ai_worker','proxy']},
                    'secrets':{'db_password':{'file':files[2]},'app_db_password':{'file':files[3]}}}
            for name in ['web','ai_worker','scheduler']:
                config['services'][name].update(environment=env,env_file=[{'path':files[0]}])
                if name!='scheduler':
                    config['services'][name]['environment']={**env,'AI_ENV_FILE':'/run/ai/.env.ai'}
                    config['services'][name]['volumes']=[{'type':'bind','source':files[1],'target':'/run/ai/.env.ai','read_only':True}]
            config['services']['proxy']['ports']=[{'published':'443'}]
            self.assertTrue(validate(config)['backend_ports_private'])
            config['secrets']['app_db_password']['file']=files[2]
            with self.assertRaisesRegex(ValueError,'SECRET_SEPARATION'):validate(config)
            config['secrets']['app_db_password']['file']=files[3]
            config['services']['web']['image']='example/tmdb:latest'
            with self.assertRaisesRegex(ValueError,'DIGEST_REQUIRED'):validate(config)
            config['services']['web']['image']=pinned
            config['services']['web']['ports']=[{'published':'8000'}]
            with self.assertRaisesRegex(ValueError,'BACKEND_PUBLIC_PORT'):validate(config)

    def test_ssh_success_prunes_only_its_old_completed_names_after_checksum(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as directory:
            root=Path(directory); identity=root/'identity';identity.write_text('synthetic');identity.chmod(0o600)
            hosts=root/'known_hosts';hosts.write_text('synthetic')
            archive=root/('tmdb-20261106T000000Z-'+'a'*32+'.dump.age');archive.write_bytes(b'age ciphertext fixture')
            old='tmdb-20200101T000000Z-'+'b'*32+'.dump.age'
            with patch.dict(os.environ,{'BACKUP_SSH_IDENTITY_FILE':str(identity),'BACKUP_SSH_KNOWN_HOSTS_FILE':str(hosts)}):
                delivery=SSHDestination('ssh://backup@host.example.com/store')
                def remote(*args):
                    if args[0]=='stat':return b'700\n'
                    if args[0]=='sha256sum':return (digest(archive)+'  file\n').encode()
                    if args[0]=='find':return (old+'\noperator.data\n../outside\n').encode()
                    return b''
                with patch.object(delivery,'remote',side_effect=remote) as calls,patch('apps.operations.backups.checked') as upload:
                    delivery.deliver(archive,datetime.now(dt_timezone.utc),7)
                    args=upload.call_args.args[0]
                    self.assertIn('-oStrictHostKeyChecking=yes',args)
                    self.assertNotIn('PGPASSWORD',upload.call_args.kwargs['env'])
                    operations=[call.args[0] for call in calls.call_args_list]
                    self.assertLess(operations.index('sha256sum'),operations.index('ln'))
                    removed=[call.args[-1] for call in calls.call_args_list if call.args[0]=='rm']
                    self.assertIn('/store/'+old,removed)
                    self.assertFalse(any('operator.data' in name or '../' in name for name in removed))
