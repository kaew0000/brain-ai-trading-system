"""Owns `world/data/runtime/` — and nothing else. `RuntimeManager`
(`runtime_manager.py`) is the only class in this repo permitted to
write there; `SnapshotCache` (`cache.py`) is what makes those writes
skip when content is unchanged."""
