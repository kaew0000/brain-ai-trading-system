"""SnapshotCache — avoids rewriting a runtime JSON file when its
content hasn't actually changed. Stateless across process restarts by
design: it hashes the *new* content and compares against a hash of
whatever is already on disk (if anything), rather than keeping its own
separate hash-history file. That means it stays correct even if the
file was written by a previous process run, or edited by hand."""

import hashlib
import json
import os
from typing import Any


def _canonical_json_bytes(data: Any) -> bytes:
    """Stable serialization: sorted keys, fixed separators - so
    semantically-identical dicts always hash the same regardless of
    key insertion order."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class SnapshotCache:
    def _existing_hash(self, path: str) -> str | None:
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                existing_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            # Corrupt/unreadable existing file: treat as "no prior
            # content" so write_if_changed proceeds to overwrite it
            # with valid content, rather than raising.
            return None
        return hashlib.sha256(_canonical_json_bytes(existing_data)).hexdigest()

    def write_if_changed(self, path: str, data: Any) -> bool:
        """Write `data` as pretty-printed JSON to `path` only if it
        differs from what's already there. Returns whether a write
        happened. Creates parent directories if needed."""
        new_bytes = _canonical_json_bytes(data)
        new_hash = hashlib.sha256(new_bytes).hexdigest()

        if new_hash == self._existing_hash(path):
            return False

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        return True
