# MIGRATION — close stale N+1 roadmap item; add dataset read benchmark (V16 §77)

## Do you need to do anything?

No. No runtime code, setting, dependency, schema or data changed. Merge and deploy as usual.

## Optional: measure read scaling on your own hardware

From the repo root, in the project's environment:

    python -m tools.benchmark_ensemble_dataset --check

Prints latency and SQL statement count at 100 / 1,000 / 5,000 synthetic trades in a temporary database (never the live journal)
and exits 1 if the read pattern regresses to N+1. Add `--with-reference` to also time the old per-trade shape (slow at 5,000).

## Rollback

`git revert` the single commit (or delete `tools/benchmark_ensemble_dataset.py` and
`tests/test_ensemble_dataset_benchmark.py`). Nothing persisted anywhere.
