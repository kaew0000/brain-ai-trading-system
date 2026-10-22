"""Load strategy definitions from JSON files (one object per file, or a list)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ..errors import BSIError
from ..schemas import StrategyDefinition


def load_strategy_files(directory: str | Path) -> tuple[list[StrategyDefinition], list[str]]:
    out: list[StrategyDefinition] = []
    errors: list[str] = []
    d = Path(directory)
    if not d.is_dir():
        raise BSIError(f"strategy directory not found: {d}")
    for f in sorted(d.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            for obj in raw if isinstance(raw, list) else [raw]:
                out.append(StrategyDefinition.model_validate(obj))
        except (json.JSONDecodeError, ValidationError) as exc:
            errors.append(f"{f.name}: {type(exc).__name__}")
    return out, errors
