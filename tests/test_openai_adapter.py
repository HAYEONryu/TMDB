"""No paid calls: synthetic Responses transport + disposable PostgreSQL only."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
import json
from unittest.mock import Mock, patch
from uuid import uuid4

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from config.ai import AIConfig, load_ai_config
from apps.accounts.access import AccessError
from apps.ai_assistant import openai_policy as policy
from apps.ai_assistant.admin_schema import fake
from apps.ai_assistant.employee_schema import FIELDS
from apps.ai_assistant.models import AIRequest, AIUsageAttempt, AIQuotaBucket
from apps.ai_assistant.openai_adapter import OpenAIAdapter, _post
from apps.ai_assistant.openai_schema import schema
from apps.ai_assistant.services import reserve, validate_config
from apps.ai_assistant.worker import run_once, reap, NotPerformed, OutcomeUnknown
from apps.customers.queries import KST
from tests.helpers import TEST_HASHERS, login
from tests.test_p4 import Fixtures

CONFIG = AIConfig(enabled=True, configured=True, api_key="SYNTHETIC_OPENAI_KEY_NO_VALUE",
                  provider="openai", model=policy.MODEL,
                  input_price=policy.INPUT_PRICE, output_price=policy.OUTPUT_PRICE)


def payload_for(task):
    if task.schema_version == "admin-v1":
        return {**fake(task), "is_test": False}
    payload = {"feature": task.feature, "is_test": False, "source_ids": [], "limitations": []}
    if task.feature == "CLEANUP":
        payload["suggestions"] = {field: {"status": "NO_SUGGESTION", "value": None,
            "source_ids": [], "evidence": "", "reason": "근거 확인 필요"} for field in FIELDS}
    elif task.feature == "SUMMARY":
        payload.update({key: [] for key in ["key_points", "concerns", "promises", "checks"]})
    else:
        payload["questions"] = [{"question": "어떤 조건을 확인할까요?", "purpose": "관심 조건 확인",
            "source_ids": [str(task.customer_id)], "evidence": "가짜 상담 관심"} for _ in range(3)]
    return payload


def wire(payload, *, reasoning=0):
    return {"model": policy.MODEL, "status": "completed", "service_tier": "default",
        "output": [{"type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(payload, ensure_ascii=False)}]}],
        "usage": {"input_tokens": 1000, "output_tokens": 120,
            "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300,
                "cache_write_tokens_details": {"ttl_30m_tokens": 300, "ttl_12h_tokens": 0}},
            "output_tokens_details": {"reasoning_tokens": reasoning}}}


@override_settings(PASSWORD_HASHERS=TEST_HASHERS, AI_FOUNDATION_TEST_MODE=False, AI_CONFIG=CONFIG)
class OpenAIQueueTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()
        self.customer = self.customers()[0]
        self.assign(self.customer)
        self.customer.notes = "가짜 상담 관심"
        self.customer.save()
        self.network = patch("http.client.HTTPSConnection", side_effect=AssertionError("NO_NETWORK_TEST"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def task(self, feature="SUMMARY"):
        if feature in {"CLEANUP", "SUMMARY", "NEXT_QUESTIONS"}:
            actor = self.employee
            body = {"customer_id": str(self.customer.pk), "assignment_id": str(self.customer.current_assignment_id),
                    "expected_version": self.customer.version}
        else:
            actor = self.admin
            body = {"site_id": str(self.site.pk)} if feature == "TEAM_GUIDE" else {"employee_id": str(self.employee.pk)} if feature == "EMPLOYEE_COACHING" else {}
        return reserve(actor, {"feature": feature, "idempotency_key": str(uuid4()), **body})[0]

    def process(self, task, *, data=None, status=200, error=None):
        calls = []
        def transport(body, key):
            self.assertFalse(connection.in_atomic_block)
            self.assertEqual(key, CONFIG.api_key)
            calls.append(json.loads(body))
            if error:
                raise error
            return status, data if data is not None else wire(payload_for(task)), "req_mock_1"
        adapter = OpenAIAdapter(transport=transport)
        # Exercise default worker routing as well as queue, validators and ledger.
        with patch("apps.ai_assistant.openai_adapter.OpenAIAdapter", return_value=adapter):
            result = run_once()
        task.refresh_from_db()
        return result, calls

    def test_all_six_features_fixed_model_role_options_strict_schema_and_no_customer_write(self):
        for feature in ["CLEANUP", "SUMMARY", "NEXT_QUESTIONS", "TEAM_GUIDE", "EMPLOYEE_COACHING", "WEEKLY_BRIEFING"]:
            with self.subTest(feature=feature), patch("django.utils.timezone.now", return_value=datetime(2026, 11, 8, 15, tzinfo=KST)):
                task = self.task(feature)
                staff = task.actor_id == self.employee.pk
                result, calls = self.process(task, data=wire(payload_for(task), reasoning=0 if staff else 40))
                self.assertEqual(result, {"processed": 1, "succeeded": 1})
                self.assertEqual(task.reasoning_effort, "none" if staff else "low")
                self.assertFalse(task.is_test)
                body = calls[0]
                self.assertEqual(body["model"], "gpt-6-luna")
                self.assertEqual(body["reasoning"], {"effort": task.reasoning_effort, "mode": "standard"})
                self.assertEqual(body["service_tier"], "default")
                self.assertFalse(body["store"])
                self.assertFalse(body["stream"])
                self.assertEqual(body["prompt_cache_options"], {"mode": "explicit", "ttl": "30m"})
                self.assertEqual(body["max_output_tokens"], 800 if staff else 2000)
                self.assertTrue(body["text"]["format"]["strict"])
                self.assertEqual(len(calls), 1)
                for forbidden in ["tools", "temperature", "top_p", "top_logprobs", "previous_response_id", "background"]:
                    self.assertNotIn(forbidden, body)
                self.assertNotIn(CONFIG.api_key, json.dumps(body))
                self.assertNotIn(self.customer.customer_name, json.dumps(body, ensure_ascii=False))
                self.assertEqual(task.status, "SUCCEEDED")
                self.assertFalse(task.result.payload["is_test"])
                self.assertEqual(task.input_payload, {})
                self.assertEqual(task.attempt_count, 1)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.version, 1)
        self.assertEqual(self.customer.notes, "가짜 상담 관심")

    def test_reasoning_counted_once_and_cached_input_write_rates_recorded(self):
        task = self.task("EMPLOYEE_COACHING")
        self.process(task, data=wire(payload_for(task), reasoning=40))
        attempt = task.attempts.get()
        self.assertEqual((attempt.input_tokens, attempt.output_tokens, attempt.reasoning_tokens), (1000, 80, 40))
        self.assertEqual((attempt.cached_tokens, attempt.cache_write_tokens), (200, 300))
        expected = (Decimal(500)*Decimal(".10") + Decimal(200)*Decimal(".01")
                    + Decimal(300)*Decimal(".125") + Decimal(120)*Decimal(".50"))/1000000
        self.assertEqual(task.charged_cost, expected)
        self.assertLess(task.charged_cost, task.reserved_cost)
        self.assertEqual(attempt.provider_request_id, "req_mock_1")

    def test_unsupported_model_provider_prices_and_disabled_fail_before_reservation(self):
        for config in [replace(CONFIG, model="another-paid-model"), replace(CONFIG, provider="other"),
                       replace(CONFIG, enabled=False), replace(CONFIG, api_key=""),
                       replace(CONFIG, input_price=Decimal(".01")), replace(CONFIG, output_price=Decimal(".1"))]:
            with self.subTest(config=config), override_settings(AI_CONFIG=config):
                with self.assertRaises(AccessError):
                    self.task()
                self.assertEqual(run_once()["processed"], 0)
        self.assertFalse(AIRequest.objects.exists())

    def test_rejected_model_option_or_key_errors_are_terminal_zero_cost_no_retry(self):
        for status in [400, 401, 403, 404, 413, 422]:
            task = self.task()
            _, calls = self.process(task, status=status, data={"error": {"message": CONFIG.api_key}})
            self.assertEqual(task.status, "FAILED")
            self.assertEqual(task.charged_cost, 0)
            self.assertEqual(task.attempt_count, 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(run_once()["processed"], 0)
        self.assertEqual(AIQuotaBucket.objects.get().successful_count, 0)

    def test_timeout_and_reset_unknown_never_reissued_conservative_settlement(self):
        for error in [TimeoutError(CONFIG.api_key), ConnectionResetError(CONFIG.api_key)]:
            task = self.task()
            _, calls = self.process(task, error=error)
            self.assertEqual(task.status, "UNKNOWN")
            self.assertEqual(run_once()["processed"], 0)
            self.assertEqual(len(calls), 1)
            reap(now=task.unknown_until)
            task.refresh_from_db()
            self.assertEqual(task.status, "FAILED")
            self.assertEqual(task.charged_cost, task.reserved_cost)
            self.assertEqual(task.attempt_count, 1)

    def test_redirect_rate_limit_and_server_errors_never_retry(self):
        for status in [302, 409, 429, 500, 503]:
            task = self.task()
            self.process(task, status=status, data={})
            self.assertEqual(task.status, "UNKNOWN")
            self.assertEqual(run_once()["processed"], 0)
            reap(now=task.unknown_until)
            self.assertEqual(task.attempts.count(), 1)

    def test_refusal_incomplete_bad_json_wrong_model_and_tier_fail_but_bill_known_usage(self):
        for change in ["refusal", "incomplete", "bad_json", "model", "tier", "foreign_source", "test_marker", "too_many_tokens", "unexpected_reasoning"]:
            task = self.task()
            data = wire(payload_for(task))
            if change == "refusal": data["output"][0]["content"] = [{"type": "refusal", "refusal": "안내 불가"}]
            elif change == "incomplete": data["status"] = "incomplete"
            elif change == "bad_json": data["output"][0]["content"][0]["text"] = "invalid"
            elif change == "model": data["model"] = "different-paid-model"
            elif change == "tier": data["service_tier"] = "priority"
            elif change == "too_many_tokens": data["usage"]["output_tokens"] = 801
            elif change == "unexpected_reasoning": data["usage"]["output_tokens_details"]["reasoning_tokens"] = 10
            else:
                payload = payload_for(task)
                payload["source_ids"] = [str(uuid4())] if change == "foreign_source" else []
                if change == "test_marker": payload["is_test"] = True
                data = wire(payload)
            self.process(task, data=data)
            self.assertEqual(task.status, "FAILED", change)
            self.assertGreater(task.charged_cost, 0)
            self.assertFalse(task.result.valid)
            self.assertEqual(run_once()["processed"], 0)

    def test_missing_corrupt_or_12h_usage_is_unknown_and_does_not_undercharge(self):
        for change in ["missing", "negative", "bool", "overlap", "reasoning", "12h"]:
            task = self.task()
            data = wire(payload_for(task))
            if change == "missing": del data["usage"]["input_tokens_details"]["cache_write_tokens"]
            elif change == "negative": data["usage"]["input_tokens"] = -1
            elif change == "bool": data["usage"]["output_tokens"] = True
            elif change == "overlap": data["usage"]["input_tokens"] = 400
            elif change == "reasoning": data["usage"]["output_tokens_details"]["reasoning_tokens"] = 121
            else: data["usage"]["input_tokens_details"]["cache_write_tokens_details"]["ttl_12h_tokens"] = 300
            self.process(task, data=data)
            self.assertEqual(task.status, "UNKNOWN")
            reap(now=task.unknown_until)
            task.refresh_from_db()
            self.assertEqual(task.charged_cost, task.reserved_cost)

    def test_task_configuration_is_frozen_and_tampered_effort_never_sent(self):
        task = self.task()
        task.reasoning_effort = "high"
        task.save()
        result, calls = self.process(task)
        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(calls, [])
        self.assertEqual(task.status, "FAILED")
        self.assertEqual(task.charged_cost, 0)

    def test_default_transport_is_blocked_under_test_settings(self):
        task = self.task()
        self.assertEqual(run_once(), {"processed": 1, "succeeded": 0})
        task.refresh_from_db()
        self.assertEqual(task.status, "FAILED")
        self.assertEqual(task.charged_cost, 0)

    def test_large_wire_request_rejected_before_io(self):
        task = self.task()
        task.input_tokens_cap = 1
        task.save()
        _, calls = self.process(task)
        self.assertEqual(calls, [])
        self.assertEqual(task.status, "FAILED")

    def test_no_real_retry_even_if_adapter_says_not_performed(self):
        task = self.task()
        adapter = Mock()
        adapter.execute_task.side_effect = NotPerformed()
        run_once(adapter)
        task.refresh_from_db()
        self.assertEqual((task.status, task.attempt_count), ("FAILED", 1))
        self.assertEqual(run_once()["processed"], 0)

    def test_revoked_assignment_cancels_before_provider_call(self):
        task = self.task()
        self.customer.current_assignment = None
        self.customer.save()
        result, calls = self.process(task)
        self.assertEqual(calls, [])
        self.assertEqual(task.status, "CANCELLED")
        self.assertEqual(result["processed"], 0)

    def test_api_availability_distinguishes_real_configuration_without_network(self):
        response = login(self.employee).get("/api/ai/availability")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "AI_READY")
        self.assertFalse(response.json()["is_test"])
        self.assertNotIn(CONFIG.api_key, response.content.decode())


class OpenAITransportTests(SimpleTestCase):
    def test_fixed_tls_host_endpoint_authorization_and_one_post(self):
        response = Mock(status=200)
        response.read.return_value = b'{"status":"completed"}'
        response.getheader.return_value = "req_mock"
        with patch("http.client.HTTPSConnection") as factory:
            conn = factory.return_value
            conn.getresponse.return_value = response
            self.assertEqual(_post(b"{}", "synthetic"), (200, {"status": "completed"}, "req_mock"))
            factory.assert_called_once_with("api.openai.com", timeout=45)
            conn.request.assert_called_once_with("POST", "/v1/responses", body=b"{}",
                headers={"Authorization": "Bearer synthetic", "Content-Type": "application/json"})
            conn.close.assert_called_once()

    def test_raw_errors_invalid_json_and_oversized_response_never_escape(self):
        for raw in [b"synthetic-secret-not-json", b"x" * (1024 * 1024 + 1)]:
            response = Mock(status=200)
            response.read.return_value = raw
            with patch("http.client.HTTPSConnection") as factory:
                factory.return_value.getresponse.return_value = response
                with self.assertRaises(OutcomeUnknown) as error:
                    _post(b"{}", "synthetic-secret")
                self.assertEqual(str(error.exception), "")
                factory.return_value.request.assert_called_once()
                factory.return_value.close.assert_called_once()

    def test_schemas_are_closed_all_properties_required(self):
        def check(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertFalse(value["additionalProperties"])
                    self.assertEqual(set(value["required"]), set(value["properties"]))
                for nested in value.values(): check(nested)
            elif isinstance(value, list):
                for nested in value: check(nested)
        for feature in ["CLEANUP", "SUMMARY", "NEXT_QUESTIONS", "TEAM_GUIDE", "WEEKLY_BRIEFING", "EMPLOYEE_COACHING"]:
            task = Mock(feature=feature, schema_version="employee-v1" if feature in {"CLEANUP", "SUMMARY", "NEXT_QUESTIONS"} else "admin-v1")
            check(schema(task))

    def test_example_config_loads_but_remains_disabled_and_key_empty(self):
        from dotenv import dotenv_values
        from pathlib import Path
        values = dict(dotenv_values(Path(__file__).resolve().parents[1]/".env.ai.example"))
        config = load_ai_config("/private/tmp/no-ai-file", role="web", environment=values)
        self.assertFalse(config.enabled)
        self.assertFalse(config.configured)
        self.assertEqual(config.api_key, "")
        self.assertEqual(config.model, policy.MODEL)
        with override_settings(AI_CONFIG=CONFIG, AI_FOUNDATION_TEST_MODE=False):
            self.assertEqual(validate_config(), CONFIG)
