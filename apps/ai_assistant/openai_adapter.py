"""One bounded HTTPS Responses request. No SDK retries, redirects or fallback."""
import http.client
import json
from django.conf import settings
from . import openai_policy as policy
from .openai_schema import schema, instructions
from .worker import ProviderResponse, ProviderFailed, OutcomeUnknown, mark_transport_started
from .inputs import STAFF_FEATURES

MAX_RESPONSE_BYTES = 1024 * 1024


def _post(body, key):
    connection = http.client.HTTPSConnection("api.openai.com", timeout=45)
    try:
        connection.request("POST", "/v1/responses", body=body,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        response = connection.getresponse()
        # Explicit client errors reject this request; never persist provider error text.
        if response.status in {400, 401, 403, 404, 413, 422}:
            return response.status, {}, ""
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OutcomeUnknown()
        return response.status, json.loads(raw), response.getheader("x-request-id", "")
    except Exception:
        # Request may already have reached the provider. Never reissue it.
        raise OutcomeUnknown() from None
    finally:
        connection.close()


def number(value):
    if type(value) is not int or not 0 <= value < 2**31:
        raise ValueError()
    return value


def usage_response(data, request_id):
    usage = data["usage"]
    total_input = number(usage["input_tokens"])
    total_output = number(usage["output_tokens"])
    reasoning = number(usage["output_tokens_details"]["reasoning_tokens"])
    details = usage["input_tokens_details"]
    cached = number(details["cached_tokens"])
    writes = number(details["cache_write_tokens"])
    if reasoning > total_output or cached + writes > total_input:
        raise ValueError()
    ttl = details.get("cache_write_tokens_details")
    if ttl is not None and (number(ttl["ttl_12h_tokens"]) != 0 or number(ttl["ttl_30m_tokens"]) != writes):
        raise ValueError()
    # API output_tokens already includes reasoning: split once for our ledger.
    return ProviderResponse({}, total_input, total_output - reasoning, reasoning,
                            request_id, cached, writes)


class OpenAIAdapter:
    def __init__(self, *, transport=None):
        self.transport = transport

    def execute_task(self, task, payload):
        config = settings.AI_CONFIG
        staff = task.feature in STAFF_FEATURES
        # Checks happen before constructing a connection. A rejected task is terminal.
        if (not policy.supported(config) or task.is_test or task.provider != "openai"
            or task.model_version != policy.MODEL or task.reasoning_effort != ("none" if staff else "low")
            or task.input_price != policy.INPUT_PRICE or task.output_price != policy.OUTPUT_PRICE
            or task.schema_version != ("employee-v1" if staff else "admin-v1")
            or (settings.TESTING and self.transport is None)):
            raise ProviderFailed(ProviderResponse({}))
        body = json.dumps({"model": task.model_version,
            "reasoning": {"effort": task.reasoning_effort, "mode": "standard"},
            "service_tier": "default", "store": False, "stream": False,
            "max_output_tokens": task.output_tokens_cap,
            "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
            "instructions": instructions(task),
            "input": [{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            "text": {"format": {"type": "json_schema", "name": "tm_" + task.feature.lower(),
                                 "strict": True, "schema": schema(task)}},
        }, ensure_ascii=False).encode("utf-8")
        # Conservative byte bound includes schema/instructions and framing allowance.
        if len(body) + 1024 > task.input_tokens_cap:
            raise ProviderFailed(ProviderResponse({}))
        if not mark_transport_started(task):
            raise ProviderFailed(ProviderResponse({}))
        try:
            status, data, request_id = (self.transport or _post)(body, config.api_key)
        except Exception:
            raise OutcomeUnknown() from None
        if status in {400, 401, 403, 404, 413, 422}:
            raise ProviderFailed(ProviderResponse({}))
        if status != 200:
            raise OutcomeUnknown()
        try:
            response = usage_response(data, request_id)
        except (KeyError, TypeError, ValueError):
            raise OutcomeUnknown() from None
        try:
            if data["status"] != "completed" or data.get("service_tier", "default") != "default":
                raise ValueError()
            returned_model = data["model"]
            if returned_model != policy.MODEL and not returned_model.startswith(policy.MODEL + "-"):
                raise ValueError()
            messages = [item for item in data["output"] if item["type"] == "message"]
            if len(messages) != 1 or messages[0].get("status") != "completed":
                raise ValueError()
            content = messages[0]["content"]
            if len(content) != 1 or content[0]["type"] != "output_text":
                raise ValueError()
            payload = json.loads(content[0]["text"])
            if not isinstance(payload, dict):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ProviderFailed(response) from None
        return ProviderResponse(payload, response.input_tokens, response.output_tokens,
            response.reasoning_tokens, response.provider_request_id, response.cached_tokens, response.cache_write_tokens)
