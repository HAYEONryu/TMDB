"""Gemini Developer API Standard, reviewed 2026-11-07. No model fallback."""
from decimal import Decimal

MODEL = "gemini-3.5-flash-lite"
INPUT_PRICE = Decimal("0.30")
OUTPUT_PRICE = Decimal("2.50")
MODELS = {MODEL}
POLICY_VERSION = "gemini-lite-only-20261107-v3"


def prices(model=MODEL):
    # Reviewed paid rates only; free mode requires explicit zero prices below.
    if model == MODEL:
        return INPUT_PRICE, OUTPUT_PRICE
    return None


def supported(config):
    if config.usage_tier == "free":
        return (config.enabled and config.configured and bool(config.api_key)
                and config.provider == "gemini" and config.model in MODELS
                and config.input_price == 0 and config.output_price == 0
                and config.free_tier_confirmed and bool(config.free_project_id.strip())
                and config.free_limits_model == config.model
                and all(type(v) is int and v > 0 for v in [config.free_rpm, config.free_tpm, config.free_rpd]))
    return (config.enabled and config.configured and bool(config.api_key)
            and config.provider == "gemini" and config.model in MODELS
            and config.usage_tier == "paid"
            and (config.input_price, config.output_price) == prices(config.model))


def effort(config, staff):
    # none is deliberately rejected, never silently promoted to paid thinking.
    return config.staff_reasoning if staff else "low"


def limits(staff):
    # maxOutputTokens includes candidate + thinking tokens, one shared ceiling.
    return (16000, 2048, 2048) if staff else (32000, 4096, 4096)


def estimate(staff, config=None):
    from .ledger import cost
    input_cap, output_cap, _ = limits(staff)
    input_price, output_price = prices(config.model if config else MODEL)
    return cost(input_cap, output_cap, 0, input_price, output_price)
