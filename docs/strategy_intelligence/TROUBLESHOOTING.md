# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ConfigError: PyYAML is required...` | Only raised when a YAML config is loaded: `pip install PyYAML` (normally already present via uvicorn[standard]) |
| `error: invalid configuration` | Config sections are strict. Compare with `config/strategy_intelligence.yaml`; `bundle.mode` must be `research_only` |
| `status=INCOMPLETE` | Read `incomplete_reasons`: too few bars/trades, gaps, unordered candles, knowledge-only strategy, invalid parameters. The bundle will not fabricate numbers - supply more data or relax `evaluation.min_*` consciously |
| Strategy shows `UNRANKED` | Its evaluation is INCOMPLETE; ranking requires COMPLETE |
| `REJECTED_MISSING_DATA` | Snapshot lacks `regime` or the `risk` block (required; fails closed) |
| `REJECTED_STALE_SNAPSHOT` | Snapshot older than `integration.max_snapshot_age_seconds` (or in the future by >60 s) - check clocks/timezones (naive timestamps are read as UTC) |
| LLM never used | `llm.provider` is `none`, `llm.model` empty, or the API key env var is unset -> offline mode by design (see log line "falling back to offline mode") |
| `research_mode: offline_rules_fallback` | The LLM timed out, was unavailable, or returned output that failed validation; see `warnings` |
| `StorageError: ... database is locked` | Another process holds a write lock; the store retries for 10 s. Close other brain_strategy_intelligence processes |
| Crash during a write | SQLite rolls back the open transaction on next open (WAL). Data files: `brain_strategy_intelligence_data/knowledge.sqlite3`, `brain_strategy_intelligence_data/outcomes.sqlite3` - back them up by copying while no brain_strategy_intelligence process runs |
| `BackendUnavailable` | PostgreSQL extras not installed/configured: `pip install "psycopg[binary]>=3.1,<4" "pgvector>=0.2,<1"` and set `BSI_POSTGRES_DSN` |
| Windows path/quoting problems | Use `py -3.12`, activate `.venv\Scripts\Activate.ps1`; quote paths with spaces |
