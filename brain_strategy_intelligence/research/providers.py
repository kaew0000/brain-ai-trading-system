"""LLM providers. All optional; nothing here is imported or contacted unless configured."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping

from ..config import LLMCfg
from ..errors import ProviderTimeout, ProviderUnavailable

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class NullProvider:
    """Used when no provider is configured: offline mode. Always unavailable by design."""

    name = "none"

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        raise ProviderUnavailable("no LLM provider configured")


class CallableProvider:
    """Wraps any callable(system, user) -> str. Used by tests and for custom/local integrations."""

    def __init__(self, fn: Callable[[str, str], str], name: str = "callable") -> None:
        self.fn, self.name = fn, name

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        return self.fn(system, user)


class AnthropicProvider:
    """Minimal Anthropic Messages API client (stdlib only). The API key is held in memory and never logged."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, max_tokens: int = 1500) -> None:
        if not api_key:
            raise ProviderUnavailable("API key is empty")
        if not model:
            raise ProviderUnavailable("llm.model must be set in config when provider=anthropic")
        self._key, self.model, self.max_tokens = api_key, model, max_tokens

    def complete(self, system: str, user: str, *, timeout: float) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        ).encode()
        req = urllib.request.Request(
            ANTHROPIC_URL,
            data=body,
            method="POST",
            headers={
                "x-api-key": self._key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed https URL
                data = json.loads(resp.read().decode())
        except TimeoutError as exc:
            raise ProviderTimeout("LLM request timed out") from exc
        except urllib.error.HTTPError as exc:
            raise ProviderUnavailable(f"LLM HTTP error {exc.code}") from exc  # body deliberately not echoed
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise ProviderUnavailable(f"LLM request failed: {type(exc).__name__}") from exc
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise ProviderUnavailable("unexpected LLM response shape") from exc


def build_provider(cfg: LLMCfg, env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    if cfg.provider == "none":
        return NullProvider()
    key = env.get(cfg.api_key_env, "")
    try:
        return AnthropicProvider(key, cfg.model, cfg.max_tokens)
    except ProviderUnavailable as exc:
        log.warning("LLM provider unavailable (%s); falling back to offline mode", exc)
        return NullProvider()
