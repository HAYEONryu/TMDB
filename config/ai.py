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


def load_ai_config(base_dir, *, role, environment=None):
    """No network. Read the AI file only in web/AI worker; never fail the app."""
    if role not in AI_ROLES:
        return AIConfig(reason="AI_PROCESS_DISABLED")
    environment = os.environ if environment is None else environment
    file_path = Path(environment.get("AI_ENV_FILE") or Path(base_dir) / ".env.ai")
    values = {}
    try:
        if file_path.exists():
            if os.name == "posix" and stat.S_IMODE(file_path.stat().st_mode) != 0o600:
                return AIConfig(reason="AI_CONFIG_PERMISSIONS")
            values = dict(dotenv_values(file_path, interpolate=False))
    except (OSError, ValueError):
        return AIConfig(reason="AI_NOT_CONFIGURED")

    # Process env wins, including explicit empty values; file fills missing only.
    values.update({key: value for key, value in environment.items() if key.startswith("AI_")})
    key = values.get("AI_API_KEY") or ""
    register_secret(key)
    if (values.get("AI_PROVIDER") or "").lower() == "fake":
        # Fake responses are available only via the guarded test adapter.
        return AIConfig(reason="AI_TEST_PROVIDER_FORBIDDEN")
    enabled = (values.get("AI_ENABLED") or "false").lower() == "true"
    provider, model = values.get("AI_PROVIDER") or "", values.get("AI_MODEL") or ""
    try:
        budget = Decimal(values.get("AI_MONTHLY_BUDGET_USD") or "5")
        input_price = Decimal(values.get("AI_INPUT_USD_PER_MILLION") or "NaN")
        output_price = Decimal(values.get("AI_OUTPUT_USD_PER_MILLION") or "NaN")
        prices_valid = all(v.is_finite() and v >= 0 for v in [budget, input_price, output_price])
    except (InvalidOperation, TypeError, ValueError):
        return AIConfig(reason="AI_NOT_CONFIGURED")
    configured = bool(key and provider and model and prices_valid)
    return AIConfig(enabled=enabled, configured=configured, api_key=key,
                    provider=provider, model=model, monthly_budget_usd=budget,
                    input_price=input_price if input_price.is_finite() else None,
                    output_price=output_price if output_price.is_finite() else None,
                    reason="AI_GENERATION_NOT_IMPLEMENTED" if enabled and configured else "AI_NOT_CONFIGURED")
