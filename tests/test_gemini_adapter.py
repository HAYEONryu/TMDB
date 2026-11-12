"""Native Gemini wire/queue checks with fake responses and a blocked network."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from uuid import uuid4

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from config.ai import AIConfig, load_ai_config
from config.process import prepare_process
from config.security import redact
from apps.accounts.access import AccessError
from apps.accounts.models import User
from apps.ai_assistant import gemini_policy as policy
from apps.ai_assistant.adapters import FoundationFakeAdapter
from apps.ai_assistant.gemini_adapter import GeminiAdapter, _post
from apps.ai_assistant.models import AIRequest, AIBudgetMonth, AIQuotaBucket
from apps.ai_assistant.services import reserve, reservation_cost
from apps.ai_assistant.worker import run_once, reap, OutcomeUnknown
from apps.customers.models import Customer
from apps.customers.queries import KST
from tests.helpers import TEST_HASHERS, login, user
from tests.test_openai_adapter import payload_for
from tests.test_p4 import Fixtures

CONFIG = AIConfig(enabled=True, configured=True, api_key="SYNTHETIC_GEMINI_TEST_KEY",
    provider="gemini", model=policy.MODEL, input_price=policy.INPUT_PRICE,
    output_price=policy.OUTPUT_PRICE, staff_reasoning="low")


def wire(payload):
    return {"modelVersion": policy.MODEL, "responseId": "gemini_mock_1",
        "candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": [
            {"text": json.dumps(payload, ensure_ascii=False)}]}}],
        "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 80,
            "thoughtsTokenCount": 40, "cachedContentTokenCount": 200, "totalTokenCount": 1120}}


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_FOUNDATION_TEST_MODE=False, AI_CONFIG=CONFIG)
class GeminiQueueTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()
        self.customer = self.customers()[0]
        self.assign(self.customer)
        self.customer.notes = "가짜 상담 관심"
        self.customer.save()
        guard = patch("http.client.HTTPSConnection", side_effect=AssertionError("NO_NETWORK"))
        guard.start(); self.addCleanup(guard.stop)

    def body(self, feature="SUMMARY", customer=None):
        if feature in {"CLEANUP", "SUMMARY", "NEXT_QUESTIONS"}:
            customer = customer or self.customer
            customer.refresh_from_db()
            extra = {"customer_id": str(customer.pk), "assignment_id": str(customer.current_assignment_id),
                     "expected_version": customer.version}
        else:
            extra = {"site_id": str(self.site.pk)} if feature == "TEAM_GUIDE" else {"employee_id": str(self.employee.pk)} if feature == "EMPLOYEE_COACHING" else {}
        return {"feature": feature, "idempotency_key": str(uuid4()), **extra}

    def task(self, feature="SUMMARY"):
        actor = self.employee if feature in {"CLEANUP", "SUMMARY", "NEXT_QUESTIONS"} else self.admin
        return reserve(actor, self.body(feature))[0]

    def process(self, task, *, data=None, status=200, error=None, tier="standard"):
        calls = []
        def transport(body, key):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(key, CONFIG.api_key)
            calls.append(json.loads(body))
            if error: raise error
            return status, data if data is not None else wire(payload_for(task)), tier
        with patch("apps.ai_assistant.gemini_adapter.GeminiAdapter", return_value=GeminiAdapter(transport=transport)):
            result = run_once()
        task.refresh_from_db()
        return result, calls

    def test_six_features_use_gemini_low_json_and_never_write_customer(self):
        for feature in ["CLEANUP", "SUMMARY", "NEXT_QUESTIONS", "TEAM_GUIDE", "EMPLOYEE_COACHING", "WEEKLY_BRIEFING"]:
            with self.subTest(feature=feature), patch("django.utils.timezone.now", return_value=datetime(2026, 11, 8, 15, tzinfo=KST)):
                task = self.task(feature)
                result, calls = self.process(task)
                self.assertEqual(result, {"processed": 1, "succeeded": 1})
                self.assertEqual((task.provider, task.model_version, task.reasoning_effort), ("gemini", policy.MODEL, "low"))
                self.assertEqual(len(calls), 1)
                body = calls[0]
                cfg = body["generationConfig"]
                self.assertEqual(cfg["thinkingConfig"], {"thinkingLevel": "LOW", "includeThoughts": False})
                self.assertEqual(cfg["maxOutputTokens"], 2048 if task.customer_id else 4096)
                self.assertEqual(cfg["responseFormat"]["text"]["mimeType"], "APPLICATION_JSON")
                self.assertFalse(cfg["responseFormat"]["text"]["schema"]["additionalProperties"])
                self.assertEqual(set(body), {"contents", "systemInstruction", "generationConfig"})
                for forbidden in [CONFIG.api_key, self.customer.customer_name, "tools", "cachedContent", "candidateCount", "temperature"]:
                    self.assertNotIn(forbidden, json.dumps(body, ensure_ascii=False))
                self.assertFalse(task.is_test)
                self.assertEqual(task.input_payload, {})
                self.assertEqual(task.attempt_count, 1)
        self.customer.refresh_from_db()
        self.assertEqual((self.customer.version, self.customer.notes), (1, "가짜 상담 관심"))

    def test_usage_thinking_once_implicit_cache_and_frozen_price(self):
        task = self.task()
        self.process(task)
        attempt = task.attempts.get()
        self.assertEqual((attempt.input_tokens, attempt.output_tokens, attempt.reasoning_tokens), (1000, 80, 40))
        self.assertEqual((attempt.cached_tokens, attempt.cache_write_tokens), (200, 0))
        self.assertEqual(task.charged_cost, (Decimal(800)*Decimal('.30')+Decimal(200)*Decimal('.03')+Decimal(120)*Decimal('2.50'))/1000000)
        self.assertEqual(task.reserved_cost, Decimal('.009920'))
        self.assertLess(task.charged_cost, task.reserved_cost)

    def test_none_wrong_model_prices_or_missing_key_rejected_before_reservation(self):
        for config in [replace(CONFIG, staff_reasoning="none"), replace(CONFIG, staff_reasoning="high"),
                       replace(CONFIG, model="gemini-other"), replace(CONFIG, input_price=Decimal('.10')),
                       replace(CONFIG, api_key=""), replace(CONFIG, enabled=False)]:
            with self.subTest(config=config), override_settings(AI_CONFIG=config):
                with self.assertRaises(AccessError): self.task()
                self.assertFalse(login(self.employee).get('/api/ai/availability').json()['generation_available'])
        self.assertFalse(AIRequest.objects.exists())

    def test_tampered_task_or_no_test_transport_never_connects(self):
        for change in ['effort', 'model', 'cap', 'price', 'transport']:
            task = self.task()
            if change == 'effort': task.reasoning_effort = 'none'
            elif change == 'model': task.model_version = 'gpt-6-luna'
            elif change == 'cap': task.output_tokens_cap += 1
            elif change == 'price': task.input_price = Decimal('.10')
            task.save()
            if change == 'transport':
                self.assertEqual(run_once()['succeeded'], 0); task.refresh_from_db()
            else:
                _, calls = self.process(task); self.assertEqual(calls, [])
            self.assertEqual((task.status, task.charged_cost), ('FAILED', 0))

    def test_failures_never_fake_fallback_retry_or_change_paid_model(self):
        # Historical paid wire compatibility is tested only in the test runtime.
        # The deployed runtime rejects paid tasks before dispatch (final suite).
        for status in [400, 401, 403, 404, 422, 302, 429, 503, 'timeout']:
            task = self.task()
            with patch.object(FoundationFakeAdapter, 'execute_task', side_effect=AssertionError('NO_FAKE')) as fake, \
                 patch('apps.ai_assistant.openai_adapter.OpenAIAdapter', side_effect=AssertionError('NO_FALLBACK')) as other:
                _, calls = self.process(task, status=status, error=TimeoutError(CONFIG.api_key) if status == 'timeout' else None)
                self.assertEqual(len(calls), 1)
                self.assertIn(task.status, ['FAILED', 'UNKNOWN'])
                self.assertFalse(task.result.valid)
                self.assertEqual(run_once()['processed'], 0)
                fake.assert_not_called(); other.assert_not_called()
            if task.status == 'UNKNOWN':
                reap(now=task.unknown_until); task.refresh_from_db()
                self.assertEqual(task.charged_cost, task.reserved_cost)
            else: self.assertEqual(task.charged_cost, 0)
            self.assertEqual(task.attempt_count, 1)

    def test_invalid_success_rejected_but_known_usage_is_charged(self):
        for change in ['model', 'blocked', 'incomplete', 'json', 'function', 'thought', 'tokens', 'tier', 'is_test', 'source']:
            task = self.task()
            payload = payload_for(task)
            if change == 'is_test': payload['is_test'] = True
            if change == 'source': payload['source_ids'] = [str(uuid4())]
            data = wire(payload)
            if change == 'model': data['modelVersion'] = 'gemini-3.7-flash'
            elif change == 'blocked': data['promptFeedback'] = {'blockReason': 'SAFETY'}
            elif change == 'incomplete': data['candidates'][0]['finishReason'] = 'MAX_TOKENS'
            elif change == 'json': data['candidates'][0]['content']['parts'][0]['text'] = 'bad'
            elif change == 'function': data['candidates'][0]['content']['parts'] = [{'functionCall': {}}]
            elif change == 'thought': data['candidates'][0]['content']['parts'][0]['thought'] = True
            elif change == 'tokens': data['usageMetadata'].update(candidatesTokenCount=2048, totalTokenCount=3088)
            self.process(task, data=data, tier='priority' if change == 'tier' else 'standard')
            self.assertEqual(task.status, 'FAILED')
            self.assertGreater(task.charged_cost, 0)
            self.assertFalse(task.result.valid)

    def test_bad_usage_unknown_conservative_no_retry(self):
        for change in ['missing', 'negative', 'bool', 'cache', 'total', 'tools']:
            task = self.task(); data = wire(payload_for(task)); usage = data['usageMetadata']
            if change == 'missing': del usage['promptTokenCount']
            elif change == 'negative': usage['thoughtsTokenCount'] = -1
            elif change == 'bool': usage['cachedContentTokenCount'] = True
            elif change == 'cache': usage['cachedContentTokenCount'] = 1001
            elif change == 'total': usage['totalTokenCount'] += 1
            else: usage['toolUsePromptTokenCount'] = 1
            self.process(task, data=data)
            self.assertEqual(task.status, 'UNKNOWN')
            self.assertEqual(run_once()['processed'], 0)
            reap(now=task.unknown_until); task.refresh_from_db()
            self.assertEqual(task.charged_cost, task.reserved_cost)

    def test_three_features_share_thirty_and_duplicate_request_reserves_once(self):
        for feature in ['CLEANUP', 'SUMMARY', 'NEXT_QUESTIONS']:
            body = self.body(feature)
            task, _ = reserve(self.employee, body)
            same, created = reserve(self.employee, body)
            self.assertFalse(created); self.assertEqual(task.pk, same.pk)
            self.assertEqual(AIQuotaBucket.objects.get().reserved_count, 1)
            self.assertEqual(self.process(task)[0]['succeeded'], 1)
            same, created = reserve(self.employee, self.body(feature))
            self.assertFalse(created); self.assertEqual(task.pk, same.pk)
        bucket = AIQuotaBucket.objects.get(); bucket.successful_count = 39; bucket.save()
        Customer.objects.filter(pk=self.customer.pk).update(version=2)
        task = self.task('CLEANUP'); self.process(task)
        for feature in ['SUMMARY', 'NEXT_QUESTIONS']:
            with self.assertRaises(AccessError) as error: self.task(feature)
            self.assertEqual(error.exception.code, 'AI_DAILY_LIMIT')
        bucket.refresh_from_db(); self.assertEqual((bucket.successful_count, bucket.reserved_count), (40, 0))

    def test_usd5_budget_includes_pending_and_releases_rejection(self):
        amount = reservation_cost(True, CONFIG)
        month = AIBudgetMonth.objects.create(month=datetime.now(KST).date().replace(day=1), charged_usd=Decimal('5')-amount)
        task = self.task()
        second = self.customers(offset=20)[0]; self.assign(second, self.other)
        second.notes='가상 상담 기록';second.save(update_fields=['notes'])
        with self.assertRaises(AccessError) as error: reserve(self.other, self.body(customer=second))
        self.assertEqual(error.exception.code, 'AI_BUDGET_LIMIT')
        month.refresh_from_db(); self.assertEqual(month.charged_usd+month.reserved_usd, 5)
        self.process(task, status=400)
        month.refresh_from_db(); self.assertEqual(month.reserved_usd, 0)
        self.assertTrue(reserve(self.other, self.body(customer=second))[1])

    def test_manager_weekly_shared_and_daily_per_employee_site_unchanged(self):
        sunday = datetime(2026, 11, 8, 15, tzinfo=KST)
        second_admin = user('01000000004', role=User.Role.ADMIN, initial=False)
        with patch('django.utils.timezone.now', return_value=sunday):
            for feature in ['WEEKLY_BRIEFING', 'EMPLOYEE_COACHING', 'TEAM_GUIDE']:
                task = self.task(feature)
                shared, created = reserve(second_admin, self.body(feature))
                self.assertFalse(created); self.assertEqual(shared.pk, task.pk)
                self.assertEqual(task.reserved_cost, Decimal('.019840'))
                self.assertEqual(self.process(task)[0]['succeeded'], 1)
                self.assertFalse(reserve(second_admin, self.body(feature))[1])
        with patch('django.utils.timezone.now', return_value=sunday+timedelta(days=1)):
            with self.assertRaises(AccessError) as error: self.task('WEEKLY_BRIEFING')
            self.assertEqual(error.exception.code, 'AI_SUNDAY_ONLY')
            for feature in ['EMPLOYEE_COACHING', 'TEAM_GUIDE']:
                task = self.task(feature); self.assertEqual(self.process(task)[0]['succeeded'], 1)


class GeminiTransportConfigTests(SimpleTestCase):
    def test_fixed_https_header_one_post_standard_default(self):
        response = Mock(status=200); response.read.return_value = b'{}'; response.getheader.return_value = 'standard'
        with patch('http.client.HTTPSConnection') as factory:
            factory.return_value.getresponse.return_value = response
            self.assertEqual(_post(b'{}', 'synthetic'), (200, {}, 'standard'))
            factory.assert_called_once_with('generativelanguage.googleapis.com', timeout=45)
            factory.return_value.request.assert_called_once_with('POST', '/v1beta/models/gemini-3.5-flash-lite:generateContent',
                body=b'{}', headers={'x-goog-api-key': 'synthetic', 'Content-Type': 'application/json'})
            factory.return_value.close.assert_called_once()

    def test_invalid_and_oversized_body_cannot_expose_secret_or_retry(self):
        for raw in [b'synthetic-secret', b'x'*(1024*1024+1)]:
            response = Mock(status=200); response.read.return_value = raw
            with patch('http.client.HTTPSConnection') as factory:
                factory.return_value.getresponse.return_value = response
                with self.assertRaises(OutcomeUnknown) as error: _post(b'{}', 'synthetic-secret')
                self.assertEqual(str(error.exception), '')
                factory.return_value.request.assert_called_once()
                factory.return_value.close.assert_called_once()

    def test_keys_separate_redacted_server_roles_only_and_example_disabled(self):
        with TemporaryDirectory() as temp:
            p = Path(temp)/'.env.ai'
            p.write_text('AI_ENABLED=true\nAI_PROVIDER=gemini\nAI_MODEL=gemini-3.5-flash-lite\nAI_API_KEY=old-synthetic\nAI_GEMINI_API_KEY=new-synthetic\nAI_STAFF_REASONING=low\nAI_INPUT_USD_PER_MILLION=.30\nAI_OUTPUT_USD_PER_MILLION=2.50\n')
            p.chmod(0o600)
            for role in ['web', 'ai_worker']:
                cfg = load_ai_config(temp, role=role, environment={})
                self.assertEqual(cfg.api_key, 'new-synthetic'); self.assertTrue(cfg.configured)
                self.assertEqual(cfg.staff_reasoning, 'low')
                self.assertNotIn(cfg.api_key, repr(cfg))
            for role in ['management', 'scheduler', 'test']:
                self.assertEqual(load_ai_config(temp, role=role, environment={}).api_key, '')
            self.assertEqual(redact('old-synthetic new-synthetic'), '[REDACTED] [REDACTED]')
            cfg = load_ai_config(temp, role='web', environment={'AI_GEMINI_API_KEY': ''})
            self.assertTrue(cfg.configured); self.assertEqual(cfg.api_key, 'new-synthetic')
            import os
            with patch.dict(os.environ, {'AI_GEMINI_API_KEY': 'synthetic'}, clear=True):
                prepare_process('scheduler'); self.assertNotIn('AI_GEMINI_API_KEY', os.environ)
        from dotenv import dotenv_values
        values = dict(dotenv_values(Path(__file__).resolve().parents[1]/'.env.ai.example'))
        cfg = load_ai_config('/private/tmp/no-ai-file', role='web', environment=values)
        self.assertEqual((cfg.enabled, cfg.configured, cfg.api_key, cfg.model), (False, False, '', ''))

    def test_only_lite_model_and_reviewed_prices_are_accepted(self):
        self.assertEqual(policy.MODELS, {'gemini-3.5-flash-lite'})
        self.assertEqual(policy.prices(), (Decimal('.30'), Decimal('2.50')))
        self.assertTrue(policy.supported(CONFIG))
        self.assertIsNone(policy.prices('gemini-3.8-flash'))
        self.assertFalse(policy.supported(replace(CONFIG, model='gemini-3.8-flash')))
        self.assertFalse(policy.supported(replace(CONFIG, input_price=Decimal('.75'), output_price=Decimal('3.75'))))
