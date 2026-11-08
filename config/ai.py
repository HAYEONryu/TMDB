from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import stat

from dotenv import dotenv_values
from config.process import AI_ROLES
from config.security import register_secret


@dataclass(frozen=True, slots=True)
class AIConfig:
    enabled: bool = False
    configured: bool = False
    api_key: str = field(default="", repr=False)
    provider: str = ""
    model: str = ""
    monthly_budget_usd: Decimal = Decimal("5")
    input_price: Decimal | None = None
    output_price: Decimal | None = None
    reason: str = "AI_NOT_CONFIGURED"
    staff_reasoning: str = "none"
    usage_tier: str = "paid"
    free_tier_confirmed: bool = False
    free_project_id: str = ""
    free_rpm: int = 0
    free_tpm: int = 0
    free_rpd: int = 0
    free_limits_model: str = ""
    test_budget_usd: Decimal | None = None
    test_budget_scope: str = ""


def load_ai_config(base_dir, *, role, environment=None):
    """No network. Read the AI file only in web/AI worker; never fail the app."""
    if role not in AI_ROLES:
        return AIConfig(reason="AI_PROCESS_DISABLED")
    environment = os.environ if environment is None else environment
    file_path = Path(environment.get("AI_ENV_FILE") or Path(base_dir) / ".env.ai")
    if file_path.name != ".env.ai":
        return AIConfig(reason="AI_CONFIG_FILE_REQUIRED")
    values = {}
    try:
        if file_path.exists():
            if os.name == "posix" and stat.S_IMODE(file_path.stat().st_mode) != 0o600:
                return AIConfig(reason="AI_CONFIG_PERMISSIONS")
            values = dict(dotenv_values(file_path, interpolate=False))
    except (OSError, ValueError):
        return AIConfig(reason="AI_NOT_CONFIGURED")

    # Nonsecret settings may be overridden; credentials come only from .env.ai.
    values.update({key: value for key, value in environment.items() if key.startswith("AI_")
                   and key not in {"AI_API_KEY", "AI_GEMINI_API_KEY"}})
    # Preserve the old OpenAI key; never send it to Google's endpoint.
    register_secret(values.get("AI_API_KEY") or "")
    register_secret(values.get("AI_GEMINI_API_KEY") or "")
    key = values.get("AI_GEMINI_API_KEY" if values.get("AI_PROVIDER") == "gemini" else "AI_API_KEY") or ""
    register_secret(key)
    if (values.get("AI_PROVIDER") or "").lower() == "fake":
        # Fake responses are available only via the guarded test adapter.
        return AIConfig(reason="AI_TEST_PROVIDER_FORBIDDEN")
    enabled = (values.get("AI_ENABLED") or "false").lower() == "true"
    provider, model = values.get("AI_PROVIDER") or "", values.get("AI_MODEL") or ""
    try:
        free_limits = [int(values.get(name) or "0") for name in ["AI_FREE_RPM", "AI_FREE_TPM", "AI_FREE_RPD"]]
        if any(value < 0 or value > 2**31-1 for value in free_limits):
            raise ValueError()
        budget = Decimal(values.get("AI_MONTHLY_BUDGET_USD") or "5")
        test_budget = Decimal(values["AI_TEST_BUDGET_USD"]) if values.get("AI_TEST_BUDGET_USD") else None
        if test_budget is not None and (not test_budget.is_finite() or test_budget < 0 or not values.get("AI_TEST_BUDGET_SCOPE")):
            raise ValueError()
        # Confirmed free mode has a known zero price; paid mode requires prices.
        default_price = "0" if provider == "gemini" and values.get("AI_USAGE_TIER") == "free" else "NaN"
        input_price = Decimal(values.get("AI_INPUT_USD_PER_MILLION") or default_price)
        output_price = Decimal(values.get("AI_OUTPUT_USD_PER_MILLION") or default_price)
        prices_valid = all(v.is_finite() and v >= 0 for v in [budget, input_price, output_price])
    except (InvalidOperation, TypeError, ValueError):
        return AIConfig(reason="AI_NOT_CONFIGURED")
    configured = bool(key and provider and model and prices_valid)
    return AIConfig(enabled=enabled, configured=configured, api_key=key,
                    provider=provider, model=model, monthly_budget_usd=budget,
                    input_price=input_price if input_price.is_finite() else None,
                    output_price=output_price if output_price.is_finite() else None,
                    reason="AI_CONFIGURATION_LOADED" if enabled and configured else "AI_NOT_CONFIGURED",
                    staff_reasoning=values.get("AI_STAFF_REASONING") or ("low" if provider == "gemini" else "none"),
                    usage_tier=values.get("AI_USAGE_TIER") or "paid",
                    free_tier_confirmed=(values.get("AI_FREE_TIER_CONFIRMED") or "false").lower() == "true",
                    free_project_id=values.get("AI_FREE_PROJECT_ID") or "",
                    free_rpm=free_limits[0], free_tpm=free_limits[1], free_rpd=free_limits[2],
                    free_limits_model=values.get("AI_FREE_LIMITS_MODEL") or model,
                    test_budget_usd=test_budget, test_budget_scope=values.get("AI_TEST_BUDGET_SCOPE") or "")
