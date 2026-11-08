"""Explicit provider selection only; never substitute another paid model."""
from decimal import Decimal
from . import gemini_policy, openai_policy


def selected(provider):
    return {"gemini": gemini_policy, "openai": openai_policy}.get(provider)


def reasoning(config, staff):
    if config.provider == "gemini":
        return gemini_policy.effort(config, staff)
    return "none" if staff else "low"


def reasoning_supported(config, staff):
    return config.provider != "gemini" or reasoning(config, staff) == "low"


def cache_prices(request):
    if request.provider == "gemini":
        # Implicit cache reads only, frozen against this request's input price.
        return request.input_price / 10, Decimal("0")
    if request.provider == "openai":
        return openai_policy.CACHED_PRICE, openai_policy.CACHE_WRITE_PRICE
    raise ValueError("Unknown AI provider")
