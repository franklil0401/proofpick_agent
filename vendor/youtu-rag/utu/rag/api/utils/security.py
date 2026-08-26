"""Security helpers for API responses."""

from typing import Any


REDACTED_VALUE = "<redacted>"
_SENSITIVE_KEY_NAMES = (
    "access_key",
    "api_key",
    "authorization",
    "password",
    "private_key",
    "secret",
    "token",
)


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized.startswith("authorization_") or any(
        normalized == name or normalized.endswith(f"_{name}")
        for name in _SENSITIVE_KEY_NAMES
    )


def redact_sensitive_config(value: Any) -> Any:
    """Return a copy with populated credential-like fields redacted."""
    if isinstance(value, dict):
        redacted = {}
        for key, child in value.items():
            if _is_sensitive_key(key) and child not in (None, ""):
                redacted[key] = REDACTED_VALUE
            else:
                redacted[key] = redact_sensitive_config(child)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_config(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_config(item) for item in value)
    return value
