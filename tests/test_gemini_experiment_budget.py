"""Offline tests; no credentials, database or external network."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from scripts.gemini_experiment_budget import ExperimentBudget,ExperimentStopped,ExperimentWait


class GeminiExperimentBudgetTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.now=datetime(2026,11,7,14,50,tzinfo=timezone.utc)
        self.confirmation={'provider':'gemini','model':'gemini-3.5-flash-lite','project_id':'synthetic-project',
            'free_tier':True,'billing_linked':False,'credential_replaced':True,'other_apps_paused':True,
            'rpm':15,'tpm':250000,'rpd':500,'remaining_rpd':500,'observed_at':self.now.isoformat()}
        self.budget=ExperimentBudget(self.tmp.name,self.confirmation,clock=lambda:self.now)

    def send(self,transport=None):
        return self.budget.send('SUMMARY',1000,b'synthetic-data','synthetic-test-only',transport or (lambda *args:(200,{'usageMetadata':{'promptTokenCount':100,'candidatesTokenCount':20,'thoughtsTokenCount':5,'totalTokenCount':125}},'standard')))

    def test_ten_requests_persist_across_new_instances_and_block_eleventh(self):
        for _ in range(10):self.send()
        self.budget=ExperimentBudget(self.tmp.name,self.confirmation,clock=lambda:self.now)
        transport=Mock()
        with self.assertRaisesRegex(ExperimentStopped,'TEN_REQUEST'):self.send(transport)
        transport.assert_not_called();self.assertEqual(len(self.budget.read()['calls']),10)

    def test_reserves_before_io_and_unknown_never_refunds_or_retries(self):
        def transport(*args):
            self.assertEqual(self.budget.read()['calls'][0]['status'],'STARTED')
            raise TimeoutError('synthetic-private-error')
        with self.assertRaisesRegex(ExperimentStopped,'TRANSPORT_OUTCOME_UNKNOWN'):self.send(transport)
        self.assertEqual(self.budget.read()['calls'][0]['status'],'UNKNOWN')
        self.assertEqual(len(self.budget.read()['calls']),1)

    def test_confirmation_is_required_and_paid_tier_blocks_before_transport(self):
        for name,value in [('free_tier',False),('billing_linked',True),('credential_replaced',False),('other_apps_paused',False),('remaining_rpd',0),('model','gemini-flash-latest')]:
            with self.subTest(name=name):
                transport=Mock();original=self.confirmation[name];self.confirmation[name]=value
                with self.assertRaises(ExperimentStopped):self.send(transport)
                transport.assert_not_called();self.confirmation[name]=original

    def test_daily_remaining_and_minute_input_reservations(self):
        self.confirmation['rpm']=1
        self.send()
        with self.assertRaises(ExperimentWait):self.send()
        self.now+=timedelta(seconds=61);self.send()
        self.confirmation['remaining_rpd']=2
        with self.assertRaisesRegex(ExperimentStopped,'FREE_DAILY'):self.send()

    def test_confirmation_expires_and_invalid_ledger_is_not_reset(self):
        self.send();self.now+=timedelta(hours=3)
        with self.assertRaisesRegex(ExperimentStopped,'CONFIRMATION_EXPIRED'):self.send()
        path=Path(self.tmp.name)/'state.json';path.write_text('corrupt')
        with self.assertRaisesRegex(ExperimentStopped,'LEDGER_INVALID'):self.budget.read()
        self.assertEqual(path.read_text(),'corrupt')

    def test_no_key_or_body_is_written_and_tokens_are_recorded(self):
        self.send();raw=(Path(self.tmp.name)/'state.json').read_text()
        self.assertNotIn('synthetic-test-only',raw);self.assertNotIn('synthetic-data',raw)
        row=self.budget.read()['calls'][0]
        self.assertEqual((row['prompt_tokens'],row['output_tokens'],row['thinking_tokens'],row['total_tokens']),(100,20,5,125))

    def test_completed_experiment_cannot_send_after_restart(self):
        self.send()
        state=self.budget.read();state['closed']=True;self.budget.save(state)
        self.budget=ExperimentBudget(self.tmp.name,self.confirmation,clock=lambda:self.now)
        transport=Mock()
        with self.assertRaisesRegex(ExperimentStopped,'EXPERIMENT_COMPLETED'):self.send(transport)
        transport.assert_not_called();self.assertEqual(len(self.budget.read()['calls']),1)

    def test_error_without_usage_keeps_input_reservation(self):
        self.confirmation['tpm']=1500
        self.send(lambda *args:(429,{'error':{'status':'RESOURCE_EXHAUSTED'}},'standard'))
        row=self.budget.read()['calls'][0]
        self.assertEqual(row['error_code'],'RESOURCE_EXHAUSTED')
        self.assertNotIn('prompt_tokens',row)
        transport=Mock()
        with self.assertRaises(ExperimentWait):self.send(transport)
        transport.assert_not_called();self.assertEqual(len(self.budget.read()['calls']),1)
