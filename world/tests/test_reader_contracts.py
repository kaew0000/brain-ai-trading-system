"""Phase W4: reader + DataSource contract tests, all against synthetic
fixture files (tmp_path) — never against any real engine path, since
readers must work with no assumption about what exists today."""

import csv
import json
import sqlite3

import pytest

from world.readers.base import (
    CSVFileSource,
    DataSource,
    EventBusSource,
    JSONFileSource,
    LogFileSource,
    Reader,
    SQLiteSource,
)
from world.readers.event_reader import EventReader
from world.readers.journal_reader import JournalReader
from world.readers.mission_reader import MissionReader
from world.readers.order_reader import OrderReader
from world.readers.portfolio_reader import PortfolioReader
from world.readers.telemetry_reader import TelemetryReader


def test_data_source_is_abstract():
    with pytest.raises(TypeError):
        DataSource()


def test_reader_is_abstract():
    with pytest.raises(TypeError):
        Reader(source=None)


def test_event_bus_source_raises_not_implemented():
    with pytest.raises(NotImplementedError):
        EventBusSource().load_raw()


# ---------------------------------------------------------------- sources

def test_json_file_source(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"a": 1}]))
    assert JSONFileSource(str(p)).load_raw() == [{"a": 1}]


def test_csv_file_source(tmp_path):
    p = tmp_path / "data.csv"
    with open(p, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "district"])
        writer.writeheader()
        writer.writerow({"symbol": "BTCUSDT", "district": "portfolio-garden"})
    rows = CSVFileSource(str(p)).load_raw()
    assert rows == [{"symbol": "BTCUSDT", "district": "portfolio-garden"}]


def test_sqlite_source(tmp_path):
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE journal (id TEXT, timestamp TEXT, symbol TEXT, action TEXT)")
    conn.execute("INSERT INTO journal VALUES ('j1', '2026-07-30T00:00:00Z', 'BTCUSDT', 'open')")
    conn.commit()
    conn.close()

    rows = SQLiteSource(str(db_path), "journal").load_raw()
    assert rows == [{"id": "j1", "timestamp": "2026-07-30T00:00:00Z", "symbol": "BTCUSDT", "action": "open"}]


def test_log_file_source(tmp_path):
    p = tmp_path / "engine.log"
    p.write_text("line one\nline two\n")
    assert LogFileSource(str(p)).load_raw() == ["line one", "line two"]


def test_json_file_source_missing_file_raises(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    with pytest.raises(FileNotFoundError):
        JSONFileSource(str(missing)).load_raw()


# ---------------------------------------------------------------- domain readers

def test_journal_reader_happy_path(tmp_path):
    p = tmp_path / "journal.json"
    p.write_text(json.dumps([
        {"id": "j1", "timestamp": "2026-07-30T00:00:00Z", "symbol": "BTCUSDT", "action": "open", "note": "test"},
    ]))
    entries = JournalReader(JSONFileSource(str(p))).read()
    assert len(entries) == 1
    assert entries[0].entry_id == "j1"
    assert entries[0].note == "test"


def test_journal_reader_skips_malformed_rows(tmp_path):
    p = tmp_path / "journal.json"
    p.write_text(json.dumps([
        {"id": "j1", "timestamp": "t", "symbol": "BTCUSDT", "action": "open"},
        {"id": "j2"},  # missing required keys
    ]))
    entries = JournalReader(JSONFileSource(str(p))).read()
    assert len(entries) == 1


def test_telemetry_reader_skips_non_numeric_value(tmp_path):
    p = tmp_path / "telemetry.json"
    p.write_text(json.dumps([
        {"name": "lag", "value": 1.5},
        {"name": "bad", "value": "not-a-number"},
    ]))
    points = TelemetryReader(JSONFileSource(str(p))).read()
    assert len(points) == 1
    assert points[0].value == 1.5


def test_portfolio_reader_defaults_district(tmp_path):
    p = tmp_path / "portfolio.json"
    p.write_text(json.dumps([{"symbol": "ETHUSDT"}]))
    positions = PortfolioReader(JSONFileSource(str(p))).read()
    assert positions[0].district == "portfolio-garden"


def test_mission_reader_skips_invalid_status(tmp_path):
    p = tmp_path / "missions.json"
    p.write_text(json.dumps([
        {"id": "m1", "title": "T", "district": "recovery-center", "status": "active"},
        {"id": "m2", "title": "T2", "district": "recovery-center", "status": "not-a-real-status"},
    ]))
    missions = MissionReader(JSONFileSource(str(p))).read()
    assert len(missions) == 1
    assert missions[0].mission_id == "m1"


def test_event_reader_skips_invalid_severity(tmp_path):
    p = tmp_path / "events.json"
    p.write_text(json.dumps([
        {"id": "e1", "timestamp": "t", "type": "trade_fill", "district": "execution-forge", "severity": "success"},
        {"id": "e2", "timestamp": "t", "type": "x", "district": "execution-forge", "severity": "not-a-real-severity"},
    ]))
    events = EventReader(JSONFileSource(str(p))).read()
    assert len(events) == 1
    assert events[0].event_id == "e1"


# ---------------------------------------------------------------- W13-1 OrderReader

def test_order_reader_happy_path(tmp_path):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps({
        "timestamp": "2026-08-07T00:00:00Z",
        "states": [{"symbol": "BTCUSDT", "state": "OPEN"}],
        "reconciliation": {
            "lastRun": "2026-08-07T00:00:00Z", "lastResult": "clean",
            "eventCount": 2, "suppressedRepeatCount": 0,
        },
    }))
    reader = OrderReader(JSONFileSource(str(p)))
    entries = reader.read()
    assert len(entries) == 1
    assert entries[0].symbol == "BTCUSDT"
    assert entries[0].state == "OPEN"
    assert reader.last_reconciliation.last_result == "clean"
    assert reader.last_reconciliation.event_count == 2


def test_order_reader_skips_rows_missing_symbol(tmp_path):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps({
        "timestamp": "t",
        "states": [{"symbol": "BTCUSDT", "state": "OPEN"}, {"state": "CLOSED"}],
    }))
    entries = OrderReader(JSONFileSource(str(p))).read()
    assert len(entries) == 1
    assert entries[0].symbol == "BTCUSDT"


def test_order_reader_no_reconciliation_key_leaves_none(tmp_path):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps({"timestamp": "t", "states": []}))
    reader = OrderReader(JSONFileSource(str(p)))
    reader.read()
    assert reader.last_reconciliation is None


def test_order_reader_empty_payload(tmp_path):
    p = tmp_path / "orders.json"
    p.write_text(json.dumps({"timestamp": "t", "states": []}))
    entries = OrderReader(JSONFileSource(str(p))).read()
    assert entries == []


def test_order_reader_resets_reconciliation_between_reads(tmp_path):
    """Same discipline PortfolioReader.last_summary uses (see
    test_portfolio_reader_summary.py::test_last_summary_resets_between_reads):
    a capture with no reconciliation object must not leak the previous
    capture's reconciliation into this one."""
    p = tmp_path / "orders.json"
    reader = OrderReader(JSONFileSource(str(p)))

    p.write_text(json.dumps({
        "timestamp": "t1", "states": [],
        "reconciliation": {"lastResult": "clean"},
    }))
    reader.read()
    assert reader.last_reconciliation is not None

    p.write_text(json.dumps({"timestamp": "t2", "states": []}))
    reader.read()
    assert reader.last_reconciliation is None
