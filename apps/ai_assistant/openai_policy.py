"""Reviewed Standard policy, 2026-11-07. No provider/model fallback."""
from decimal import Decimal

MODEL = "gpt-6-luna"
INPUT_PRICE = Decimal("0.10")
OUTPUT_PRICE = Decimal("0.50")
CACHED_PRICE = Decimal("0.01")
CACHE_WRITE_PRICE = Decimal("0.125")  # Explicit 30m retention, never 12h.
POLICY_VERSION = "openai-luna-standard-20261107-v1"


def supported(config):
    return (config.enabled and config.configured and bool(config.api_key)
            and config.provider == "openai" and config.model == MODEL
            and config.usage_tier == "paid"
            and config.input_price == INPUT_PRICE and config.output_price == OUTPUT_PRICE)


def limits(staff):
    # Payload remains bounded separately. Allow schema, instructions and framing.
    return (16000, 800, 0) if staff else (32000, 2000, 2000)


def estimate(staff):
    from .ledger import cost
    input_cap, output_cap, _ = limits(staff)
    # Worst case: all input written to the 30m cache; output includes reasoning.
    return cost(input_cap, output_cap, 0, CACHE_WRITE_PRICE, OUTPUT_PRICE)
