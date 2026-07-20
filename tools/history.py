"""
tools/history.py — Bundle Manager: bundle_history.json

The duplicate-import guard. Every bundle this tool has ever successfully
imported gets one record here, keyed by head commit SHA — the same SHA
across two differently-named bundle files (e.g. a bundle re-sent after a
rename) is still recognized as a duplicate, since the SHA is the actual
identity of the content, not the filename.

bundle_history.json is tracked in git (not gitignored) deliberately —
it's shared history, not local cache: a fresh clone must know what's
already been imported, or it could re-import (and re-push) a bundle
someone already merged from a different machine.

Write safety: every write is atomic (write to a temp file in the same
directory, then os.replace) so a crash or Ctrl-C mid-write can never
leave bundle_history.json truncated/corrupted — the previous good
version is either fully replaced or not touched at all.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BundleRecord:
    sha:              str
    branch:           str
    bundle_filename:  str
    status:           str            # "applied" | "failed"
    imported_at:      str            # ISO 8601 UTC
    pushed:           bool = False
    reason:           Optional[str] = None   # populated when status == "failed"


class BundleHistory:
    """Loaded once, mutated in memory, saved explicitly via save() —
    callers control exactly when the atomic write happens rather than
    every record() call hitting disk."""

    def __init__(self, path: Path):
        self.path = path
        self._records: List[BundleRecord] = []
        self._by_sha: dict = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            logger.info("history: %s not found, starting empty", self.path)
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # Fail loud, not silent — an unreadable history file is exactly
            # the situation where guessing "assume empty" risks a real
            # duplicate re-import/re-push. Caller must resolve this by hand.
            raise RuntimeError(
                f"bundle_history.json at {self.path} exists but could not be "
                f"read/parsed ({exc}). Refusing to proceed with an assumed-"
                f"empty history, since that risks re-importing an already-"
                f"pushed bundle. Fix or restore the file from git history."
            ) from exc

        for entry in raw.get("records", []):
            record = BundleRecord(
                sha=entry["sha"], branch=entry["branch"],
                bundle_filename=entry["bundle_filename"], status=entry["status"],
                imported_at=entry["imported_at"], pushed=entry.get("pushed", False),
                reason=entry.get("reason"),
            )
            self._records.append(record)
            self._by_sha[record.sha] = record

    def has_sha(self, sha: str) -> bool:
        """True only for a previously *applied* (successfully imported
        and pushed) SHA — a prior *failed* attempt for the same SHA does
        not block retrying it after the underlying problem is fixed."""
        record = self._by_sha.get(sha)
        return record is not None and record.status == "applied"

    def get(self, sha: str) -> Optional[BundleRecord]:
        return self._by_sha.get(sha)

    def record_applied(self, sha: str, branch: str, bundle_filename: str, pushed: bool) -> None:
        self._add(BundleRecord(
            sha=sha, branch=branch, bundle_filename=bundle_filename,
            status="applied", imported_at=_now_iso(), pushed=pushed,
        ))

    def record_failed(self, sha: str, branch: str, bundle_filename: str, reason: str) -> None:
        self._add(BundleRecord(
            sha=sha, branch=branch, bundle_filename=bundle_filename,
            status="failed", imported_at=_now_iso(), pushed=False, reason=reason,
        ))

    def _add(self, record: BundleRecord) -> None:
        # A later record for the same SHA supersedes an earlier one (e.g.
        # a failed attempt followed by a successful retry) — replace, not
        # append duplicate entries for the same SHA.
        self._records = [r for r in self._records if r.sha != record.sha]
        self._records.append(record)
        self._by_sha[record.sha] = record

    def all_records(self) -> List[BundleRecord]:
        return list(self._records)

    def save(self) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "updated_at": _now_iso(),
            "records": [asdict(r) for r in self._records],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file in the same directory (so os.replace is
        # guaranteed atomic — same filesystem), then replace.
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".bundle_history_", suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=False)
                f.write("\n")
            os.replace(tmp_path, self.path)
        except Exception:
            # Best-effort cleanup of the temp file on any failure — the
            # real file (if it existed) is untouched either way.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
