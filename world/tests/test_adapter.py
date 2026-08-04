"""Phase W4: adapter orchestration tests, using fake in-memory readers
(no real files needed — the point of dependency injection)."""

import json

from world.adapter.adapter import ReadOnlyIngestionAdapter
from world.readers.base import JSONFileSource
from world.readers.event_reader import EventReader


class _FakeReader:
    def __init__(self, value):
        self._value = value

    def read(self):
        return self._value


class _RaisingReader:
    def read(self):
        raise RuntimeError("source unavailable")


def test_capture_snapshot_with_no_readers_is_empty_but_valid():
    adapter = ReadOnlyIngestionAdapter()
    snapshot = adapter.capture_snapshot()
    assert snapshot.journal_entries == []
    assert snapshot.telemetry_points == []
    assert snapshot.portfolio_positions == []
    assert snapshot.missions == []
    assert snapshot.events == []
    assert all(v is False for v in snapshot.sources_available.values())
    assert snapshot.captured_at  # non-empty timestamp


def test_capture_snapshot_uses_provided_readers():
    adapter = ReadOnlyIngestionAdapter(journal_reader=_FakeReader(["j1", "j2"]))
    snapshot = adapter.capture_snapshot()
    assert snapshot.journal_entries == ["j1", "j2"]
    assert snapshot.sources_available["journal"] is True
    assert snapshot.sources_available["telemetry"] is False


def test_one_failing_reader_does_not_break_the_others():
    adapter = ReadOnlyIngestionAdapter(
        journal_reader=_RaisingReader(),
        telemetry_reader=_FakeReader(["t1"]),
    )
    snapshot = adapter.capture_snapshot()
    assert snapshot.journal_entries == []
    assert snapshot.sources_available["journal"] is False
    assert snapshot.telemetry_points == ["t1"]
    assert snapshot.sources_available["telemetry"] is True


def test_portfolio_summary_is_none_when_reader_has_no_last_summary():
    """Phase W11: a portfolio reader that doesn't define `last_summary`
    (e.g. this file's own _FakeReader, or any older stub) must not
    break the adapter — portfolio_summary simply stays None."""
    adapter = ReadOnlyIngestionAdapter(portfolio_reader=_FakeReader(["p1"]))
    snapshot = adapter.capture_snapshot()
    assert snapshot.portfolio_positions == ["p1"]
    assert snapshot.portfolio_summary is None


def test_portfolio_summary_is_read_from_reader_side_channel():
    """Phase W11: after a successful .read(), the adapter picks up
    whatever the portfolio reader left on its `last_summary`
    attribute."""

    class _ReaderWithSummary:
        def __init__(self):
            self.last_summary = "sentinel-summary"

        def read(self):
            return ["p1"]

    adapter = ReadOnlyIngestionAdapter(portfolio_reader=_ReaderWithSummary())
    snapshot = adapter.capture_snapshot()
    assert snapshot.portfolio_summary == "sentinel-summary"


def test_portfolio_summary_is_none_when_portfolio_reader_raises():
    """Phase W11: same never-fatal contract as every other reader — a
    raising portfolio reader must not leave a stale/wrong summary."""
    adapter = ReadOnlyIngestionAdapter(portfolio_reader=_RaisingReader())
    snapshot = adapter.capture_snapshot()
    assert snapshot.portfolio_summary is None
    assert snapshot.sources_available["portfolio"] is False


def test_adapter_never_writes_a_file(tmp_path, monkeypatch):
    """The adapter must only read. Assert no new file appears in a
    scratch directory during a capture, using a real (working) reader
    to make sure this isn't just 'nothing happened because it
    crashed'."""
    source_path = tmp_path / "events.json"
    source_path.write_text(json.dumps([
        {"id": "e1", "timestamp": "t", "type": "x", "district": "execution-forge", "severity": "info"},
    ]))
    monkeypatch.chdir(tmp_path)

    adapter = ReadOnlyIngestionAdapter(event_reader=EventReader(JSONFileSource(str(source_path))))
    before = set(tmp_path.iterdir())
    snapshot = adapter.capture_snapshot()
    after = set(tmp_path.iterdir())

    assert len(snapshot.events) == 1
    assert before == after
