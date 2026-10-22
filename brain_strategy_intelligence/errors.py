"""Exception hierarchy. Every failure the bundle raises deliberately derives from BSIError."""

from __future__ import annotations


class BSIError(Exception):
    """Base class for all bundle errors."""


class ConfigError(BSIError):
    """Invalid or unsafe configuration (e.g. a non-research_only mode)."""


class StorageError(BSIError):
    """Persistence failure."""


class DuplicateVersionError(StorageError):
    """A (strategy_id, version) pair already exists; versions are immutable."""


class BackendUnavailable(StorageError):
    """An optional backend (PostgreSQL/pgvector) is not installed or not configured."""


class ProviderUnavailable(BSIError):
    """No LLM provider is configured or reachable."""


class ProviderTimeout(ProviderUnavailable):
    """The LLM provider did not answer within the configured timeout."""


class InvalidLLMOutput(BSIError):
    """The LLM returned output that failed schema or safety validation."""


class ValidationRefused(BSIError):
    """A strategy cannot be marked validated (missing/incomplete evidence)."""


class DataError(BSIError):
    """Historical data is malformed, unordered, or otherwise unusable."""
