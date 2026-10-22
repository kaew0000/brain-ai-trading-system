"""CLI end-to-end on SYNTHETIC data, in a temp directory."""

import pytest
import json
from datetime import UTC, datetime
from pathlib import Path

from brain_strategy_intelligence.cli import main

pytestmark = pytest.mark.unit

EXAMPLES = str(Path(__file__).resolve().parent.parent / "brain_strategy_intelligence" / "strategies")


def run(tmp_path, *args):
    return main(["--data-dir", str(tmp_path), *args])


def test_init_list_search_evaluate_rank_report(tmp_path, capsys):
    assert run(tmp_path, "init-kb", "--examples", EXAMPLES) == 0
    assert "added 9" in capsys.readouterr().out
    assert run(tmp_path, "init-kb", "--examples", EXAMPLES) == 0  # idempotent: duplicates skipped, not duplicated
    assert "added 0" in capsys.readouterr().out
    assert run(tmp_path, "list") == 0 and "trend-sma-cross" in capsys.readouterr().out
    assert run(tmp_path, "search", "breakout channel") == 0 and "breakout-donchian" in capsys.readouterr().out
    assert run(tmp_path, "evaluate", "trend-sma-cross", "--synthetic", "--bars", "2000") == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC" in out and "status=" in out
    assert any((tmp_path / "reports").glob("evaluation_trend-sma-cross_*.md"))
    assert run(tmp_path, "rank", "--synthetic") == 0
    assert (tmp_path / "reports" / "ranking_latest.json").is_file()
    assert run(tmp_path, "report") == 0


def test_unknown_strategy_and_bad_inputs_return_nonzero(tmp_path, capsys):
    run(tmp_path, "init-kb", "--examples", EXAMPLES)
    assert run(tmp_path, "evaluate", "nope", "--synthetic") == 2
    assert run(tmp_path, "evaluate", "trend-sma-cross", "--csv", str(tmp_path / "missing.csv")) == 2
    assert run(tmp_path, "init-kb", "--examples", str(tmp_path / "nodir")) == 2
    assert run(tmp_path, "research", "--snapshot", str(tmp_path / "none.json")) == 2


def test_research_command_uses_adapter_and_fails_closed(tmp_path, capsys):
    run(tmp_path, "init-kb", "--examples", EXAMPLES)
    snap = {
        "symbol": "BTCUSDT",
        "timestamp": datetime.now(UTC).isoformat(),
        "mark_price": 100.0,
        "regime": "TREND",
        "risk": {"trading_allowed": True, "max_leverage": 1, "risk_pct": 0.01},
    }
    p = tmp_path / "snap.json"
    p.write_text(json.dumps(snap))
    assert run(tmp_path, "research", "--snapshot", str(p)) == 0
    assert "Advisory only" in capsys.readouterr().out
    del snap["risk"]
    p.write_text(json.dumps(snap))
    assert run(tmp_path, "research", "--snapshot", str(p)) == 1  # REJECTED_MISSING_DATA


def test_disabled_bundle_exits_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BSI_ENABLED", "false")
    assert run(tmp_path, "list") == 0 and "disabled" in capsys.readouterr().out
    assert not (tmp_path / "knowledge.sqlite3").exists()
