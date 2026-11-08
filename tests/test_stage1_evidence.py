"""Small focused checks; all credentials/records are synthetic."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from unittest import TestCase
from unittest.mock import patch
import zipfile

from django.test import SimpleTestCase,TransactionTestCase
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import psycopg
from psycopg import sql

from scripts.verification_evidence import RunRecord,write_new,artifact_path
from scripts.verify_docker_release import stage_context,scan_archive
from tests.browser_observation import project_trace,route_category,net_error

VERSION={'git_head':'synthetic','worktree_dirty':True,'source_digest':'synthetic-digest'}


class EvidencePreservationTests(SimpleTestCase):
    def test_same_label_parallel_and_failed_runs_never_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            def execute(index):
                run=RunRecord('same-label',['python','synthetic-check'],root=directory,version=VERSION)
                write_new(run.path/'results.json',{'index':index})
                run.finish(0 if index%2 else 1)
                return run
            with ThreadPoolExecutor(max_workers=8) as pool:runs=list(pool.map(execute,range(20)))
            self.assertEqual(len({r.run_id for r in runs}),20)
            self.assertEqual(len(list(Path(directory).iterdir())),20)
            for index,run in enumerate(runs):
                self.assertEqual(json.loads((run.path/'results.json').read_text())['index'],index)
                before=(run.path/'results.json').read_bytes()
                with self.assertRaises(FileExistsError):write_new(run.path/'results.json',{})
                self.assertEqual((run.path/'results.json').read_bytes(),before)
                started=json.loads((run.path/'started.json').read_text())
                self.assertEqual(started['label'],'same-label');self.assertTrue(started['code_version']['worktree_dirty'])
            interrupted=RunRecord('same-label',['python','synthetic-check'],root=directory,version=VERSION)
            self.assertTrue((interrupted.path/'started.json').exists())
            self.assertFalse((interrupted.path/'finished.json').exists())

    def test_process_failure_before_results_has_no_stale_result_or_raw_output(self):
        with tempfile.TemporaryDirectory() as directory:
            run=RunRecord('setup-failure',['python','synthetic-check'],root=directory,version=VERSION)
            child=subprocess.run([__import__('sys').executable,'-c',"print('COOKIE_PRIVATE_MARKER');raise SystemExit(7)"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            run.finish(child.returncode)
            self.assertIsNone(json.loads((run.path/'finished.json').read_text())['result_file'])
            self.assertNotIn('COOKIE_PRIVATE_MARKER',''.join(p.read_text() for p in run.path.iterdir()))

    def test_command_rejects_credential_urls_and_artifacts_are_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):RunRecord('unsafe',['postgresql://user:password@host/db'],root=directory,version=VERSION)
            a=RunRecord('a',['test'],root=directory,version=VERSION);b=RunRecord('a',['test'],root=directory,version=VERSION)
            outputs=[]
            for run in [a,b]:
                with patch.dict(os.environ,{'TM_EVIDENCE_RUN_DIR':str(run.path),'TM_EVIDENCE_TEST_ID':'tests.synthetic.case'}):
                    outputs.append(artifact_path('evidence.json'))
                    with self.assertRaises(ValueError):artifact_path('../outside')
            self.assertNotEqual(outputs[0],outputs[1])

    def test_raw_assertion_payload_is_removed_from_failure_diagnostic(self):
        from config.acceptance_runner import EvidenceResult
        from unittest import FunctionTestCase
        import sys
        stream=io.StringIO();result=EvidenceResult(stream,descriptions=False,verbosity=0)
        try:raise AssertionError('PASSWORD_AND_CUSTOMER_PRIVATE_MARKER')
        except AssertionError:result.addFailure(FunctionTestCase(lambda:None),sys.exc_info())
        self.assertNotIn('PASSWORD_AND_CUSTOMER_PRIVATE_MARKER',result.failures[0][1]+stream.getvalue())


class TracePrivacyTests(SimpleTestCase):
    def test_trace_allowlist_strips_password_cookie_body_dom_and_urls(self):
        private='SENSITIVE_SYNTHETIC_CUSTOMER_AND_AUTH'
        events=[{'type':'before','callId':'call@1','apiName':'locator.fill','method':'fill','startTime':1,
            'params':{'value':private,'url':'http://localhost/auth/login?token='+private},'stack':[private]},
            {'type':'after','callId':'call@1','endTime':2,'error':{'message':private}},
            {'type':'frame-snapshot','snapshot':private}]
        with tempfile.TemporaryDirectory() as directory:
            raw=Path(directory)/'raw.zip';target=Path(directory)/'safe.json'
            with zipfile.ZipFile(raw,'w') as z:
                z.writestr('trace.trace','\n'.join(json.dumps(e) for e in events))
                z.writestr('trace.network',private);z.writestr('resources/private.txt',private)
            project_trace(raw,target)
            content=target.read_text()
            self.assertNotIn(private,content)
            self.assertEqual(len(json.loads(content)['events']),2)
            self.assertEqual(route_category('http://localhost/api/customers/private-name?phone=01000000000'),'/api/customers<redacted>')
            self.assertEqual(route_category('chrome-error://chromewebdata/'),'chrome-error://chromewebdata/')
            self.assertEqual(net_error(private+' net::ERR_CONNECTION_RESET'), 'net::ERR_CONNECTION_RESET')


class DockerEvidenceUnitTests(SimpleTestCase):
    def test_staging_never_copies_actual_secret_files_and_markers_are_synthetic(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'context';markers=stage_context(root)
            self.assertEqual(len(markers),9)
            self.assertTrue((root/'.env.ai').read_bytes().startswith(b'TM_EXCLUDE_SENTINEL_'))
            self.assertFalse((root/'.git').exists());self.assertFalse((root/'.local').exists())

    def test_every_layer_is_scanned_even_when_a_later_layer_removes_secret(self):
        marker=b'SYNTHETIC_SECRET_MARKER'
        with tempfile.TemporaryDirectory() as directory:
            archive=Path(directory)/'image.tar'
            with tarfile.open(archive,'w') as outer:
                for index,name in enumerate(['app/.env.ai','app/.wh..env.ai']):
                    buffer=io.BytesIO()
                    with tarfile.open(fileobj=buffer,mode='w') as layer:
                        info=tarfile.TarInfo(name);info.size=len(marker) if index==0 else 0
                        layer.addfile(info,io.BytesIO(marker if index==0 else b''))
                    raw=buffer.getvalue();info=tarfile.TarInfo(f'{index}/layer.tar');info.size=len(raw);outer.addfile(info,io.BytesIO(raw))
            result=scan_archive(archive,[marker])
            self.assertEqual(result['layers_scanned'],2);self.assertEqual(result['marker_matches'],1)
            self.assertEqual(result['forbidden_paths'],1)


class FreshMigrationAndRoleTests(TransactionTestCase):
    def test_fresh_database_all_migration_leaves_applied(self):
        executor=MigrationExecutor(connection)
        self.assertEqual(executor.migration_plan(executor.loader.graph.leaf_nodes()),[])

    def test_initializer_gives_app_migration_rights_without_cluster_admin(self):
        # Verify the same init script against ONLY the disposable test cluster.
        source=connection.settings_dict
        self.assertTrue(str(source['NAME']).startswith('test_tm_'))
        role='tm_app_'+__import__('uuid').uuid4().hex[:16]
        params={'host':source['HOST'],'port':source['PORT'],'dbname':source['NAME'],'user':source['USER'],'password':source['PASSWORD']}
        script=Path(__file__).resolve().parents[1]/'deploy/postgres-init.sh'
        with tempfile.TemporaryDirectory() as directory:
            pw=Path(directory)/'app-password';pw.write_text('SYNTHETIC_DB_PASSWORD_ONLY');pw.chmod(0o600)
            init=Path(directory)/'init.sh';init.write_text(script.read_text().replace('tm_app',role))
            env={k:v for k,v in os.environ.items() if not k.startswith('AI_')}
            env.update(PGHOST=str(source['HOST']),PGPORT=str(source['PORT']),PGPASSWORD=source['PASSWORD'],
                POSTGRES_USER=source['USER'],POSTGRES_DB=source['NAME'],TM_APP_DB_PASSWORD_FILE=str(pw),
                PATH='/opt/homebrew/opt/postgresql@17/bin:'+os.environ['PATH'])
            try:
                result=subprocess.run(['sh',str(init)],env=env,capture_output=True)
                self.assertEqual(result.returncode,0,'Initializer failed; raw stderr suppressed')
                with psycopg.connect(**{**params,'user':role,'password':'SYNTHETIC_DB_PASSWORD_ONLY'},autocommit=True) as db:
                    self.assertEqual(db.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication FROM pg_roles WHERE rolname=current_user').fetchone(),(False,False,False,False))
                    db.execute('CREATE TABLE stage1_private_probe (id integer)')
                    db.execute('INSERT INTO stage1_private_probe VALUES (1)')
                    self.assertEqual(db.execute('SELECT count(*) FROM stage1_private_probe').fetchone()[0],1)
                    db.execute('DROP TABLE stage1_private_probe')
            finally:
                with psycopg.connect(**params,autocommit=True) as db:
                    db.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
                    db.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(role)))
