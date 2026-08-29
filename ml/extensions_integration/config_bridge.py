"""
ConfigBridge — translates config/settings.py's real Settings singleton
into ml.extensions.orchestrator.ExtensionsConfig.

Scope note: the original task brief for this integration layer
(PROMPT_FOR_CLAUDE.md, drafted before this repo was inspected)
described this bridge as syncing config with an "Auto-Config Engine"
that has a config-change audit log. A repo-wide, case-insensitive grep
for auto_config / autoconfig / auto-config found zero matches anywhere
in this codebase as of this phase — no such engine exists. That part
of the brief was written without inspecting the real repo, so it is
dropped here rather than built against nothing. This bridge is scoped
to what actually exists: config/settings.py's Settings singleton and
ExtensionsConfig's own dataclass. If an Auto-Config Engine is built in
a future phase, this is the natural place to wire it in.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from config.settings import settings as _settings

if TYPE_CHECKING:
    from ml.extensions.orchestrator import ExtensionsConfig


class ConfigBridge:
    """Thin, read-only translator: Settings -> ExtensionsConfig."""

    @staticmethod
    def is_enabled() -> bool:
        return bool(getattr(_settings, "ML_EXTENSIONS_ENABLED", False))

    @staticmethod
    def default_symbols() -> list[str]:
        # Reuses the ONE canonical symbol-list fallback
        # (settings.symbol_list) rather than re-deriving the
        # SYMBOL/SYMBOLS fallback rule locally — see that property's
        # own docstring for why it must stay the single source of truth.
        try:
            return list(_settings.symbol_list)
        except Exception:
            return ["BTCUSDT"]

    @classmethod
    def build_extensions_config(cls, mode: str = "paper", **overrides) -> "ExtensionsConfig":
        """
        Builds an ExtensionsConfig using this project's real
        symbol_list for `symbols`, and ExtensionsConfig's own dataclass
        defaults otherwise (rl_algorithm, hpo_n_trials, ...) — those
        have no equivalent in config/settings.py today, so they are not
        duplicated here as new Settings fields. Pass overrides
        explicitly per-call instead (e.g.
        build_extensions_config(rl_algorithm="SAC")).

        Imports ExtensionsConfig lazily so importing this module (and
        the rest of ml.extensions_integration) never requires
        ml/extensions/'s optional heavy dependencies (gymnasium,
        stable-baselines3, torch, river, optuna) — those are only
        pulled in when this method actually runs.
        """
        from ml.extensions.orchestrator import ExtensionsConfig

        kwargs = {"mode": mode, "symbols": cls.default_symbols()}
        kwargs.update(overrides)
        return ExtensionsConfig(**kwargs)
