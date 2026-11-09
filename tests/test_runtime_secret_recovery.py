"""Synthetic-only recovery checks; no Docker engine or real credentials needed."""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch

from dotenv import dotenv_values
from scripts.recover_runtime_secret import (RecoveryError, SOURCE_SCRIPT, main,
                                           private_command, recover)

KEY = "synthetic-existing-secret-$literal-quote'and\\slash"
ORIGINAL = "DATABASE_URL=postgresql://fake:synthetic@postgres/tm_dev\nDJANGO_DEBUG=false\n"


class RuntimeSecretRecoveryTests(TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        for name in ('compose.yaml','compose.server.yaml'):(self.root/name).write_text('services: {}\n')
        self.env=self.root/'.env';self.env.write_text(ORIGINAL);self.env.chmod(0o640)
        self.calls=[];self.override=False

    def fake_run(self, args, *, root, input=None):
        self.calls.append(args)
        if args[1]=='inspect':
            return ','.join(str(self.root/p) for p in ('compose.yaml','compose.server.yaml'))
        if args[1]=='exec':
            self.assertEqual(input,self.env.read_text())
            return json.dumps({'secret':KEY,'updated':ORIGINAL+"DJANGO_SECRET_KEY='"+KEY.replace('\\','\\\\').replace("'","\\'")+"'\n"})
        if args[1]=='compose':
            key=dotenv_values(self.env,interpolate=False).get('DJANGO_SECRET_KEY')
            serialized=key.replace('$','$$') if key else key
            return json.dumps({'services':{name:{'environment':{'DJANGO_SECRET_KEY':'' if self.override else serialized}}
                                         for name in ('web','scheduler','ai_worker')}})
        self.fail('Unexpected command')

    def test_existing_key_restored_private_backup_and_no_service_or_db_command(self):
        result=recover(self.root,'old-scheduler',run=self.fake_run)
        self.assertEqual(result['status'],'restored_existing_secret')
        self.assertEqual(dotenv_values(self.env,interpolate=False)['DJANGO_SECRET_KEY'],KEY)
        self.assertEqual(dotenv_values(self.env,interpolate=False)['DJANGO_DEBUG'],'false')
        backup=self.root/result['backup']
        self.assertEqual(backup.read_text(),ORIGINAL)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o600)
        self.assertEqual(stat.S_IMODE(backup.parent.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode),0o600)
        self.assertNotIn(KEY,json.dumps(result))
        for args in self.calls:
            self.assertFalse(set(args)&{'up','down','restart','migrate','run_ai_worker','run_scheduler'})
            self.assertNotIn(KEY,' '.join(args))

    def test_rerun_preserves_first_backup_and_is_unchanged(self):
        first=recover(self.root,'old-scheduler',run=self.fake_run)
        before=self.env.read_bytes()
        second=recover(self.root,'old-scheduler',run=self.fake_run)
        self.assertEqual(second['status'],'already_configured')
        self.assertEqual(self.env.read_bytes(),before)
        self.assertEqual(len(list((self.root/'.local').glob('runtime-secret-recovery-*'))),1)
        self.assertEqual((self.root/first['backup']).read_text(),ORIGINAL)

    def test_blank_compose_override_rolls_back_original_content_and_mode(self):
        self.override=True
        with self.assertRaisesRegex(RecoveryError,'VERIFY_FAILED_ORIGINAL_ENV_RESTORED') as caught:
            recover(self.root,'old-scheduler',run=self.fake_run)
        self.assertEqual(self.env.read_text(),ORIGINAL)
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode),0o640)
        self.assertEqual(caught.exception.details,{'services':{name:'missing' for name in ('web','scheduler','ai_worker')}})
        self.assertNotIn(KEY,json.dumps(caught.exception.details))

    def test_different_configured_key_is_never_overwritten(self):
        self.env.write_text(ORIGINAL+'DJANGO_SECRET_KEY=synthetic-different\n')
        before=self.env.read_bytes()
        with self.assertRaisesRegex(RecoveryError,'EXISTING_DIFFERENT_SECRET_NOT_REPLACED'):
            recover(self.root,'old-scheduler',run=self.fake_run)
        self.assertEqual(self.env.read_bytes(),before)

    def test_wrong_source_project_stops_before_secret_or_env_access(self):
        with self.assertRaisesRegex(RecoveryError,'SOURCE_COMPOSE_PROJECT_MISMATCH'):
            recover(self.root,'wrong-container',run=lambda *args,**kw:'/other/compose.yaml')
        self.assertEqual(self.env.read_text(),ORIGINAL)

    def test_changed_env_during_preparation_is_not_overwritten(self):
        def run(args,**kwargs):
            output=self.fake_run(args,**kwargs)
            if args[1]=='compose':self.env.write_text(ORIGINAL+'USER_EDIT=keep\n')
            return output
        with self.assertRaisesRegex(RecoveryError,'ENV_CHANGED_DURING_RECOVERY'):
            recover(self.root,'old-scheduler',run=run)
        self.assertIn('USER_EDIT=keep',self.env.read_text())

    def test_source_writer_keeps_literal_secret_and_other_dotenv_settings(self):
        settings=self.root/'synthetic_settings.py'
        settings.write_text('SECRET_KEY = '+repr(KEY)+'\n')
        original=ORIGINAL+"OTHER='literal $DO_NOT_EXPAND'\nMULTILINE='one\ntwo'\n"
        env={**os.environ,'PYTHONPATH':str(self.root),'DJANGO_SETTINGS_MODULE':'synthetic_settings'}
        result=subprocess.run([sys.executable,'-c',SOURCE_SCRIPT],env=env,input=original,capture_output=True,text=True)
        self.assertEqual(result.returncode,0)
        value=json.loads(result.stdout)
        parsed=dotenv_values(stream=io.StringIO(value['updated']),interpolate=False)
        self.assertEqual((value['secret'],parsed.pop('DJANGO_SECRET_KEY')),(KEY,KEY))
        self.assertEqual(parsed,dotenv_values(stream=io.StringIO(original),interpolate=False))

    def test_docker_errors_and_unexpected_exceptions_are_never_echoed(self):
        with patch('scripts.recover_runtime_secret.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=KEY,stderr=KEY)):
            with self.assertRaisesRegex(RecoveryError,'^DOCKER_COMMAND_FAILED$'):
                private_command(['docker','synthetic'],root=self.root)
        output=io.StringIO()
        with patch.object(sys,'argv',['recover_runtime_secret.py','--source-container','old-scheduler']),patch('scripts.recover_runtime_secret.recover',side_effect=RuntimeError(KEY)),patch('sys.stdout',output):
            self.assertEqual(main(),1)
        self.assertNotIn(KEY,output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['code'],'RECOVERY_FAILED_NO_DETAILS')

    def test_symlink_environment_is_not_followed_or_modified(self):
        self.env.rename(self.root/'actual.env');self.env.symlink_to('actual.env')
        with self.assertRaisesRegex(RecoveryError,'PROJECT_ENV_OR_COMPOSE_FILE_MISSING'):
            recover(self.root,'old-scheduler',run=self.fake_run)
        self.assertEqual((self.root/'actual.env').read_text(),ORIGINAL)


COMPOSE = Path(__file__).resolve().parents[1]/'.local/bin/docker-compose'


@skipUnless(COMPOSE.is_file(),'Standalone Compose CLI not installed; no Docker engine needed')
class RealComposeSecretRecoveryTests(RuntimeSecretRecoveryTests):
    """Use the real CLI dotenv parser and serializer, not a Python approximation."""
    def setUp(self):
        super().setUp()
        (self.root/'compose.yaml').write_text(json.dumps({'services':{
            name:{'image':'synthetic-no-engine-required','env_file':str(self.env)}
            for name in ('web','scheduler','ai_worker')}}))
        (self.root/'compose.server.yaml').write_text('services: {}\n')
        self.settings=self.root/'synthetic_settings.py'
        self.settings.write_text('SECRET_KEY = '+repr(KEY)+'\n')

    def fake_run(self, args, *, root, input=None):
        if args[1]=='compose':
            self.calls.append(args)
            environment={k:v for k,v in os.environ.items() if k!='DJANGO_SECRET_KEY'}
            result=subprocess.run([str(COMPOSE),*args[2:]],cwd=root,env=environment,capture_output=True,text=True)
            if result.returncode:raise RecoveryError('DOCKER_COMMAND_FAILED')
            return result.stdout
        if args[1]=='exec':
            self.calls.append(args)
            environment={**os.environ,'PYTHONPATH':str(self.root),'DJANGO_SETTINGS_MODULE':'synthetic_settings',
                         'PYTHONDONTWRITEBYTECODE':'1'}
            result=subprocess.run([sys.executable,'-c',SOURCE_SCRIPT],cwd=root,env=environment,input=input,capture_output=True,text=True)
            if result.returncode:raise RecoveryError('DOCKER_COMMAND_FAILED')
            return result.stdout
        return super().fake_run(args,root=root,input=input)

    def test_blank_compose_override_rolls_back_original_content_and_mode(self):
        (self.root/'compose.server.yaml').write_text(json.dumps({'services':{
            name:{'environment':{'DJANGO_SECRET_KEY':''}} for name in ('web','scheduler','ai_worker')}}))
        super().test_blank_compose_override_rolls_back_original_content_and_mode()

    def test_different_configured_key_is_never_overwritten(self):
        # Existing unrelated key is tested before any new .env is written.
        super().test_different_configured_key_is_never_overwritten()

    def test_real_compose_preserves_single_paired_and_adjacent_literal_dollars(self):
        for key in ['synthetic-$literal','synthetic-$$pair','synthetic-$$$adjacent',KEY]:
            with self.subTest(kind='synthetic-literal-key'):
                self.env.write_text(ORIGINAL)
                self.settings.write_text('SECRET_KEY = '+repr(key)+'\n')
                result=recover(self.root,'old-scheduler',run=self.fake_run)
                self.assertEqual(result['status'],'restored_existing_secret')
                self.assertEqual(dotenv_values(self.env,interpolate=False)['DJANGO_SECRET_KEY'],key)
