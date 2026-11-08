"""One bounded native Gemini HTTPS request; no retry, redirects or fallback."""
import http.client
import json
import re
from django.conf import settings
from . import gemini_policy as policy
from .inputs import STAFF_FEATURES
from .gemini_payload import encode
from .worker import ProviderResponse, ProviderFailed, OutcomeUnknown, ProviderRateLimited, mark_transport_started

MAX_RESPONSE_BYTES = 1024 * 1024
REJECTED = {400, 401, 403, 404, 413, 422}


def _post(body, key, *, model=policy.MODEL):
    if model not in policy.MODELS:
        raise ProviderFailed(ProviderResponse({}))
    connection = http.client.HTTPSConnection("generativelanguage.googleapis.com", timeout=45)
    try:
        connection.request("POST", f"/v1beta/models/{model}:generateContent", body=body,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        response = connection.getresponse()
        if response.status in REJECTED:
            return response.status, {}, "standard"
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise OutcomeUnknown()
        try: data = json.loads(raw)
        except (ValueError, UnicodeError):
            if response.status != 429: raise
            data = {}
        if response.status == 429 and isinstance(data, dict):
            retry = response.getheader("Retry-After", "")
            if isinstance(retry, str) and retry.isdigit(): data["_retry_after_seconds"] = min(int(retry), 86400)
        return response.status, data, response.getheader("x-gemini-service-tier", "standard")
    except Exception:
        # No raw provider text, URL credentials or transport exceptions escape.
        raise OutcomeUnknown() from None
    finally:
        connection.close()


def number(value):
    if type(value) is not int or not 0 <= value < 2**31:
        raise ValueError()
    return value


def usage_response(data):
    usage = data["usageMetadata"]
    prompt = number(usage["promptTokenCount"])
    # Protobuf JSON omits scalar zero fields. Total still verifies consistency.
    output = number(usage.get("candidatesTokenCount", 0))
    thoughts = number(usage.get("thoughtsTokenCount", 0))
    cached = number(usage.get("cachedContentTokenCount", 0))
    total = number(usage["totalTokenCount"])
    if cached > prompt or total != prompt + output + thoughts or usage.get("toolUsePromptTokenCount", 0) != 0:
        raise ValueError()
    return ProviderResponse({}, prompt, output, thoughts, data.get("responseId", ""), cached, 0)


class GeminiAdapter:
    def __init__(self, *, transport=None):
        self.transport = transport

    def execute_task(self, task, payload):
        config = settings.AI_CONFIG
        staff = task.feature in STAFF_FEATURES
        input_cap, output_cap, reasoning_cap = policy.limits(staff)
        free = config.usage_tier == "free"
        if (not policy.supported(config) or task.is_test or task.provider != "gemini"
            or task.model_version != config.model or task.reasoning_effort != "low"
            or task.reasoning_effort != policy.effort(config, staff)
            or task.input_price != config.input_price or task.output_price != config.output_price
            or task.usage_tier != config.usage_tier
            or (free and not task.provider_day_id)
            or not 0 < task.input_tokens_cap <= input_cap
            or (not free and task.input_tokens_cap != input_cap)
            or (task.output_tokens_cap, task.reasoning_tokens_cap) != (output_cap, reasoning_cap)
            or task.schema_version != ("employee-v1" if staff else "admin-v1")
            or (settings.TESTING and self.transport is None)):
            raise ProviderFailed(ProviderResponse({}))
        body = encode(task, payload)
        # A conservative UTF-8 byte ceiling covers tokens plus protocol framing.
        if len(body) + 1024 > task.input_tokens_cap:
            raise ProviderFailed(ProviderResponse({}))
        if not mark_transport_started(task):
            raise ProviderFailed(ProviderResponse({}))
        try:
            status, data, tier = self.transport(body, config.api_key) if self.transport else _post(body, config.api_key, model=task.model_version)
        except Exception:
            raise OutcomeUnknown() from None
        if status in REJECTED:
            raise ProviderFailed(ProviderResponse({}))
        if status == 429 and free:
            seconds, daily = rate_limit(data)
            raise ProviderRateLimited(seconds, daily)
        if status != 200:
            raise OutcomeUnknown()
        try:
            response = usage_response(data)
        except (KeyError, TypeError, ValueError):
            raise OutcomeUnknown() from None
        try:
            model = data["modelVersion"]
            if (tier != "standard" or not isinstance(model, str)
                    or (model != task.model_version and not model.startswith(task.model_version + "-"))
                    or data.get("promptFeedback", {}).get("blockReason")):
                raise ValueError()
            candidates = data["candidates"]
            if len(candidates) != 1 or candidates[0]["finishReason"] != "STOP":
                raise ValueError()
            content = candidates[0]["content"]
            parts = content["parts"]
            if (content.get("role") != "model" or len(parts) != 1
                    or set(parts[0]) - {"text", "thoughtSignature", "thought"}
                    or parts[0].get("thought", False) is not False):
                raise ValueError()
            payload = json.loads(parts[0]["text"])
            if not isinstance(payload, dict):
                raise ValueError()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ProviderFailed(response) from None
        return ProviderResponse(payload, response.input_tokens, response.output_tokens,
            response.reasoning_tokens, response.provider_request_id, response.cached_tokens, 0)


def rate_limit(data):
    """Read only bounded retry timing/quota IDs; never save raw provider errors."""
    seconds, daily = 60, False
    if not isinstance(data, dict): return seconds, daily
    retry = data.get("_retry_after_seconds")
    if type(retry) is int and retry > 0: seconds = min(retry, 86400)
    details = data.get("error", {}).get("details", []) if isinstance(data.get("error", {}), dict) else []
    for item in details[:32] if isinstance(details, list) else []:
        if not isinstance(item, dict): continue
        delay = item.get("retryDelay", "")
        if isinstance(delay, str) and re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,9})?s", delay):
            seconds = max(seconds, min(int(float(delay[:-1]))+1, 86400))
        violations = item.get("violations", [])
        for violation in violations[:32] if isinstance(violations, list) else []:
            if isinstance(violation, dict):
                name = str(violation.get("quotaId", "")).lower()
                daily |= "perday" in name or "per_day" in name
    return seconds, daily
