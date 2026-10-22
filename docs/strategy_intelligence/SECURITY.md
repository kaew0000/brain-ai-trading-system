# Security and trading safety

| Requirement | Control | Verified by test |
|---|---|---|
| Analytical only, default `research_only` | `bundle.mode` accepts only `research_only` (any other value -> `ConfigError`); `Recommendation` has no order fields and `may_execute` is `Literal[False]` | `test_non_research_modes_are_rejected`, `test_recommendation_cannot_claim_execution_or_drop_advisory` |
| No exchange orders | No exchange/HTTP-client imports; only network host in source is `api.anthropic.com` | `test_source_contains_no_exchange_execution_or_dynamic_code_paths`, `test_adapter_exposes_no_execution_surface` |
| No LLM-generated code execution | Strategies reference built-in engines by name; no `eval/exec/compile/subprocess/importlib` | same source scan |
| No auto-installs | Nothing shells out; optional extras are documented manual installs | source scan |
| Secrets | Read only from env; strategy records containing credential-like text are rejected; reports/logs are redacted; report file names sanitised | `test_strategy_rejects_secrets...`, `test_secrets_never_reach_reports_logs_or_prompts` |
| Prompt injection | Strategy/snapshot text is wrapped as untrusted data; output must pass a strict schema (`extra=forbid`), ids must be candidates, cited numbers must exist in the snapshot/parameters | `test_prompt_injection...`, `test_unknown_strategy_ids_and_invented_numbers_are_dropped` |
| Fail closed | Missing regime/risk, blocked risk, stale or invalid snapshot, internal error -> non-OK status with no candidates | `test_fail_closed_cases`, `test_internal_error_becomes_error_status_not_exception` |
| Risk Manager not bypassed | The bundle never calls or replaces it; `trading_allowed=False` suppresses all recommendations | `test_fail_closed_cases` |
| Bounded LLM calls | per-call timeout, `max_retries` (<=5), exponential backoff, fallback to offline rules | `test_timeout_is_retried_a_bounded_number_of_times_then_falls_back` |
| Duplicate trades | `trade_id` primary key; identical resubmission = `duplicate`; different content = `conflict`, never overwritten | `test_record_then_duplicate_then_conflict` |
| Transactions / recovery | `BEGIN IMMEDIATE` ... `COMMIT/ROLLBACK`; row + revision log atomic; WAL + busy timeout | `test_failed_add_is_rolled_back_no_orphan_revision` |
| Production config untouched | Bundle reads only its own YAML and `BSI_*` env vars (Brain Bot variables such as `EXECUTION_MODE`, `BINANCE_*` are ignored) | `test_config_isolation` |

Limits: the redaction patterns are heuristic; do not paste credentials into strategy text. PostgreSQL DSNs come from env only. Review any
change to `security.py` or the source-scan test as security-relevant.
