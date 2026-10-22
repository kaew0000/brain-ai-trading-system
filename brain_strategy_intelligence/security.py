"""Secret detection and redaction helpers.

Secrets are never stored in strategy records and never written to logs/reports.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping

REDACTED = "[REDACTED]"

# Patterns that indicate a credential is being assigned or embedded in text.
_ASSIGN = re.compile(r"(?i)\b(api[_-]?key|api[_-]?secret|secret(?:[_-]?key)?|token|passphrase|password)\b\s*[:=]\s*\S+")
_SK = re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")
_LONG_ALNUM = re.compile(r"\b[A-Za-z0-9]{64}\b")  # Binance-style key length

DEFAULT_SECRET_ENV_NAMES = ("ANTHROPIC_API_KEY", "BSI_POSTGRES_DSN", "BINANCE_API_KEY", "BINANCE_API_SECRET")


def contains_secret(text: str) -> bool:
    """True if text looks like it embeds a credential (used to reject strategy records)."""
    return bool(_ASSIGN.search(text) or _SK.search(text) or _LONG_ALNUM.search(text))


def known_secret_values(
    env: Mapping[str, str] | None = None, names: Iterable[str] = DEFAULT_SECRET_ENV_NAMES
) -> list[str]:
    env = os.environ if env is None else env
    return [v for n in names if (v := env.get(n)) and len(v) >= 8]


def redact(text: str, env: Mapping[str, str] | None = None) -> str:
    """Remove credential-looking assignments and any literal secret values found in the environment."""
    out = _ASSIGN.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    out = _SK.sub(REDACTED, out)
    for value in known_secret_values(env):
        out = out.replace(value, REDACTED)
    return out


def redact_obj(obj, env: Mapping[str, str] | None = None):
    """Recursively redact strings inside dict/list structures."""
    if isinstance(obj, str):
        return redact(obj, env)
    if isinstance(obj, dict):
        return {k: redact_obj(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, env) for v in obj]
    return obj
