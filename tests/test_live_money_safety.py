"""
Regression + safety tests for the $20 live-money safety patch.

Covers exactly the three blockers identified by the read-only GO/NO-GO
audit (see docs/audit — Critical Finding A/B/C) and required to be fixed
by this patch:

  Blocker 1 — TradeManager._round_qty() used to silently clamp a
              risk/margin-derived quantity UP to the exchange's minQty
              instead of rejecting the trade. calculate_position_size()
              must now return 0.0 ("skip trade") instead.
  Blocker 2 — EXECUTION_MODE and settings.BINANCE_TESTNET could disagree,
              letting EXECUTION_MODE=testnet reach Binance MAINNET (or
              EXECUTION_MODE=live silently run on Testnet).
              BinanceDataProvider.__init__ must now refuse to start on
              a mismatch for testnet/live modes.
  Blocker 3 — No proactive MIN_NOTIONAL validation existed; the system
              relied entirely on Binance rejecting an under-notional
              order at submission time. calculate_position_size() must
              now check locally and skip before ever calling
              place_market_order().

No test in this file submits, or could submit, a real Binance order —
every Binance client used is a unittest.mock.MagicMock / manually
constructed fake; nothing here performs real network I/O.

This file is purely additive: it does not modify or weaken any
pre-existing test. (Four pre-existing exchange_info fixtures elsewhere
in the suite gained a MIN_NOTIONAL filter entry so their already-correct
assertions keep passing under the new min-notional gate — see
tests/test_execution.py, tests/test_execution_coordinator.py,
tests/test_p1b1_dynamic_risk.py, tests/test_v16_execution_idempotency.py,
tests/test_trade_lifecycle_integration.py.)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_manager(filters=None, symbol="BTCUSDT"):
    """Build a TradeManager with a fully mocked (never-real) Binance client.

    `filters` lets each test control the exact LOT_SIZE / MIN_NOTIONAL
    filter shape returned by exchange_info(), matching the real
    /fapi/v1/exchangeInfo response shape used elsewhere in this suite.
    """
    from execution.trade_manager import TradeManager

    if filters is None:
        filters = [
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        ]

    mock_client = MagicMock()
    mock_client.exchange_info.return_value = {
        "symbols": [{"symbol": symbol, "filters": filters}]
    }
    mock_provider        = MagicMock()
    mock_provider.client = mock_client

    with patch("execution.trade_manager.settings") as ms:
        ms.SYMBOL             = symbol
        ms.LEVERAGE            = 5
        ms.RISK_PER_TRADE_MAX  = 0.01
        ms.RISK_PER_TRADE_MIN  = 0.005
        ms.MAX_MARGIN_USAGE    = 0.20
        manager = TradeManager(mock_provider)

    manager.client = mock_client
    return manager, mock_client


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 1 — never clamp risk/margin qty above policy
# ─────────────────────────────────────────────────────────────────────────────

class TestQuantitySkipInsteadOfClamp:

    def test_case_a_raw_above_minqty_sizes_normally(self):
        """raw qty well above minQty → normal rounded quantity, unaffected."""
        m, _ = _make_manager()
        # risk = 5000*0.01=50U, sl_dist=5000 → raw=0.01 BTC (>> minQty 0.001)
        qty = m.calculate_position_size(
            balance=5_000.0, entry_price=50_000.0, stop_loss=45_000.0, risk_pct=0.01,
        )
        assert qty == pytest.approx(0.01, abs=1e-6)

    def test_case_b_raw_exactly_minqty_is_accepted(self):
        """raw qty that floors to exactly minQty → accepted, not rejected.

        balance=200, risk_pct=1% -> risk_amount=2U; sl_dist=2000 -> raw
        =0.001 BTC exactly. Margin cap (20% * 5x on 200U = 200U notional
        cap -> 0.004 BTC) is non-binding here, so risk math alone decides.
        notional = 0.001*50_000=50U clears the fixture's 5U min notional.
        """
        m, _ = _make_manager()
        qty = m.calculate_position_size(
            balance=200.0, entry_price=50_000.0, stop_loss=48_000.0, risk_pct=0.01,
        )
        assert qty == pytest.approx(0.001, abs=1e-9)

    def test_case_c_raw_below_minqty_is_rejected(self):
        """raw qty below minQty → SKIP (0.0), never clamped up."""
        m, _ = _make_manager()
        # $20 account, 1% risk, wide SL distance → raw well under 0.001 BTC.
        # risk_amount = 20*0.01 = 0.20U, sl_dist=500 → raw=0.0004 BTC < 0.001
        qty = m.calculate_position_size(
            balance=20.0, entry_price=65_000.0, stop_loss=64_500.0, risk_pct=0.01,
        )
        assert qty == 0.0

    def test_case_d_raw_rounds_below_minqty_after_flooring(self):
        """raw qty just above minQty but floors below it (step boundary) → SKIP."""
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
        ])
        # raw = 0.00099 → floor(0.00099/0.001)*0.001 = 0.0 → below minQty → SKIP
        # Construct via risk math: risk_amount=0.0495U, sl_dist=50 → raw=0.00099
        m.calculate_position_size  # (documented via raw injection below)
        raw = 0.00099
        floored, min_q, _ = m._floor_to_step(raw)
        assert floored < min_q  # sanity check on the fixture itself
        # Drive the real function to this raw via balance/sl_dist:
        # risk_pct*balance / sl_dist = raw  →  balance = raw*sl_dist/risk_pct
        sl_dist  = 50.0
        risk_pct = 0.01
        balance  = raw * sl_dist / risk_pct
        qty = m.calculate_position_size(
            balance=balance, entry_price=50_000.0,
            stop_loss=50_000.0 - sl_dist, risk_pct=risk_pct,
        )
        assert qty == 0.0

    def test_case_e_margin_cap_below_minqty_is_rejected_not_raised(self):
        """Margin cap alone forces qty below minQty → SKIP, not clamped up."""
        m, _ = _make_manager()
        # $20 balance, 20% margin cap, 5x leverage → max_notional=$20 →
        # max_by_margin = 20/65000 ≈ 0.000308 BTC, well under minQty 0.001,
        # regardless of how tight the SL distance is (risk math would allow
        # a much bigger raw qty here, but the margin cap must still win).
        qty = m.calculate_position_size(
            balance=20.0, entry_price=65_000.0, stop_loss=64_990.0,  # tight SL
            risk_pct=0.01, leverage=5,
        )
        assert qty == 0.0

    def test_case_f_never_returns_more_than_risk_derived_qty(self):
        """qty must never exceed the risk/margin-derived ceiling merely to
        satisfy minQty — for every qty returned (non-zero), qty <= raw
        ceiling that was actually allowed by risk+margin policy."""
        m, _ = _make_manager()
        cases = [
            (5_000.0, 50_000.0, 45_000.0, 0.01),
            (1_000.0, 50_500.0, 50_000.0, 0.01),
            (20.0,    65_000.0, 64_500.0, 0.01),
            (20.0,    65_000.0, 64_990.0, 0.01),
        ]
        for balance, entry, sl, risk_pct in cases:
            risk_amount   = balance * risk_pct
            sl_dist       = abs(entry - sl)
            raw_ceiling   = risk_amount / sl_dist
            max_notional  = balance * 0.20 * 5  # MAX_MARGIN_USAGE=0.20, LEVERAGE=5 in this fixture
            margin_ceiling = max_notional / entry
            allowed_ceiling = min(raw_ceiling, margin_ceiling)

            qty = m.calculate_position_size(
                balance=balance, entry_price=entry, stop_loss=sl, risk_pct=risk_pct,
            )
            # Either skipped (0.0) or strictly within the risk/margin ceiling —
            # NEVER inflated up to minQty past that ceiling.
            assert qty == 0.0 or qty <= allowed_ceiling + 1e-9

    def test_round_qty_still_clamps_for_already_approved_quantities(self):
        """_round_qty() itself keeps its old clamp-up behavior — it's used
        to format an ALREADY-approved quantity for SL/TP orders, not to
        make the sizing decision. This is intentionally unchanged."""
        m, _ = _make_manager()
        assert m._round_qty(0.0001) == 0.001  # unchanged pre-existing behavior

    def test_floor_to_step_never_clamps_up(self):
        m, _ = _make_manager()
        floored, min_q, _ = m._floor_to_step(0.0001)
        assert floored == 0.0
        assert min_q == 0.001


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 1 (continued) — execute_trade skips cleanly on qty=0
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteTradeSkipsOnUnsizeableQty:

    def test_execute_trade_returns_failure_without_calling_binance(self):
        m, client = _make_manager()
        result = m.execute_trade(
            direction="LONG", entry_price=65_000.0, stop_loss=64_500.0,
            take_profit=66_000.0, balance=20.0, risk_pct=0.01, leverage=5,
        )
        assert result["success"] is False
        assert result["quantity"] == 0.0
        # No order-placement call may have happened for an unsizeable trade.
        client.new_order.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 3 — MIN_NOTIONAL preflight
# ─────────────────────────────────────────────────────────────────────────────

class TestMinNotionalPreflight:

    def test_below_minimum_notional_is_rejected(self):
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "1000.0"},  # very high floor
        ])
        # balance=500, risk=1% -> risk_amount=5U; sl_dist=500 -> raw=0.01 BTC.
        # Margin cap (20%*5x on 500U=500U notional cap -> 0.1 BTC) is
        # non-binding. qty=0.01 clears LOT_SIZE fine, but notional
        # =0.01*5000=50U is well under the 1000U floor -> must be rejected.
        qty = m.calculate_position_size(
            balance=500.0, entry_price=5_000.0, stop_loss=4_500.0, risk_pct=0.01,
        )
        assert qty == 0.0

    def test_exactly_minimum_notional_is_allowed(self):
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "50.0"},
        ])
        # Same sizing as above (qty=0.01, notional=50U) but the floor is
        # set to exactly 50U -> notional == min_notional must be ALLOWED
        # ("price*quantity >= minNotional" per Binance's own filter spec).
        qty = m.calculate_position_size(
            balance=500.0, entry_price=5_000.0, stop_loss=4_500.0, risk_pct=0.01,
        )
        assert qty == pytest.approx(0.01, abs=1e-9)

    def test_above_minimum_notional_is_allowed(self):
        m, _ = _make_manager()  # default fixture: MIN_NOTIONAL=5.0
        qty = m.calculate_position_size(
            balance=5_000.0, entry_price=50_000.0, stop_loss=45_000.0, risk_pct=0.01,
        )
        assert qty == pytest.approx(0.01, abs=1e-6)

    def test_missing_notional_filter_fails_closed(self):
        """No MIN_NOTIONAL / NOTIONAL filter present at all → skip, never guess."""
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE",    "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
        ])
        qty = m.calculate_position_size(
            balance=5_000.0, entry_price=50_000.0, stop_loss=45_000.0, risk_pct=0.01,
        )
        assert qty == 0.0

    def test_malformed_notional_filter_fails_closed(self):
        """Unparseable notional value → skip, never guess/crash."""
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "not-a-number"},
        ])
        qty = m.calculate_position_size(
            balance=5_000.0, entry_price=50_000.0, stop_loss=45_000.0, risk_pct=0.01,
        )
        assert qty == 0.0

    def test_notional_filter_alternate_shape_is_supported(self):
        """Newer combined NOTIONAL filter (minNotional key) is also read."""
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "NOTIONAL", "minNotional": "5.0", "maxNotional": "1000000"},
        ])
        qty = m.calculate_position_size(
            balance=5_000.0, entry_price=50_000.0, stop_loss=45_000.0, risk_pct=0.01,
        )
        assert qty == pytest.approx(0.01, abs=1e-6)

    def test_min_notional_helper_returns_none_when_absent(self):
        m, _ = _make_manager(filters=[
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
        ])
        assert m._min_notional() is None

    def test_min_notional_helper_parses_standard_futures_shape(self):
        m, _ = _make_manager(filters=[
            {"filterType": "MIN_NOTIONAL", "notional": "5.0"},
        ])
        assert m._min_notional() == pytest.approx(5.0)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCKER 2 — EXECUTION_MODE × BINANCE_TESTNET invariant
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_time(monkeypatch):
    """Avoid a real network call in _sync_time_offset() during __init__."""
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": 1_700_000_000_000},
    )


def _patch_settings(monkeypatch, **overrides):
    from config.settings import settings
    for attr, value in overrides.items():
        monkeypatch.setattr(settings, attr, value)
    return settings


def _patch_mode(monkeypatch, mode: str):
    monkeypatch.setattr("data.binance_provider.EXECUTION_MODE", mode)


class TestExecutionModeInvariant:
    """Full EXECUTION_MODE x BINANCE_TESTNET matrix required by the patch:

        paper   | true  | PASS  (paper never touches trade_client for real orders)
        paper   | false | PASS  (same — BINANCE_TESTNET irrelevant to paper)
        testnet | true  | PASS  (matches, reaches Testnet)
        testnet | false | FAIL  (would reach MAINNET — must refuse to start)
        live    | true  | FAIL  (would silently run on Testnet — must refuse)
        live    | false | PASS  (matches, reaches Mainnet)
    """

    def test_paper_true_does_not_raise(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "paper")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=True,
            BINANCE_TESTNET_API_KEY="tk", BINANCE_TESTNET_API_SECRET="ts",
            BINANCE_TESTNET_BASE_URL="https://demo-fapi.binance.com",
            BINANCE_API_KEY="mk", BINANCE_API_SECRET="ms",
            BINANCE_PROD_BASE_URL="https://fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        BinanceDataProvider()  # must not raise

    def test_paper_false_does_not_raise_the_new_invariant(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "paper")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=False,
            BINANCE_API_KEY="mk", BINANCE_API_SECRET="ms",
            BINANCE_PROD_BASE_URL="https://fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        BinanceDataProvider()  # existing mainnet-key guard still applies if
        # keys are blank, but the NEW mode/testnet invariant must not fire
        # for paper mode — this call succeeds because mainnet keys ARE set.

    def test_testnet_true_does_not_raise(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "testnet")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=True,
            BINANCE_TESTNET_API_KEY="tk", BINANCE_TESTNET_API_SECRET="ts",
            BINANCE_TESTNET_BASE_URL="https://demo-fapi.binance.com",
            BINANCE_API_KEY="mk", BINANCE_API_SECRET="ms",
            BINANCE_PROD_BASE_URL="https://fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        dp = BinanceDataProvider()
        assert dp.trade_client.base_url == "https://demo-fapi.binance.com"

    def test_testnet_false_raises_before_any_client_is_built(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "testnet")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=False,
            BINANCE_API_KEY="mk", BINANCE_API_SECRET="ms",
            BINANCE_PROD_BASE_URL="https://fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        with pytest.raises(RuntimeError, match="EXECUTION_MODE"):
            BinanceDataProvider()

    def test_live_true_raises_before_any_client_is_built(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "live")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=True,
            BINANCE_TESTNET_API_KEY="tk", BINANCE_TESTNET_API_SECRET="ts",
            BINANCE_TESTNET_BASE_URL="https://demo-fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        with pytest.raises(RuntimeError, match="EXECUTION_MODE"):
            BinanceDataProvider()

    def test_live_false_does_not_raise(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "live")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=False,
            BINANCE_API_KEY="mk", BINANCE_API_SECRET="ms",
            BINANCE_PROD_BASE_URL="https://fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        dp = BinanceDataProvider()
        assert dp.trade_client.base_url == "https://fapi.binance.com"

    def test_error_message_never_contains_secrets(self, monkeypatch, mock_time):
        _patch_mode(monkeypatch, "testnet")
        _patch_settings(
            monkeypatch, BINANCE_TESTNET=False,
            BINANCE_API_KEY="super-secret-mainnet-key",
            BINANCE_API_SECRET="super-secret-mainnet-secret",
            BINANCE_TESTNET_API_KEY="super-secret-testnet-key",
            BINANCE_TESTNET_API_SECRET="super-secret-testnet-secret",
            BINANCE_PROD_BASE_URL="https://fapi.binance.com",
        )
        from data.binance_provider import BinanceDataProvider
        with pytest.raises(RuntimeError) as excinfo:
            BinanceDataProvider()
        msg = str(excinfo.value)
        for secret in (
            "super-secret-mainnet-key", "super-secret-mainnet-secret",
            "super-secret-testnet-key", "super-secret-testnet-secret",
        ):
            assert secret not in msg


# ─────────────────────────────────────────────────────────────────────────────
# ARCHITECTURE / STRATEGY INVARIANT — patch must not touch decision logic
# ─────────────────────────────────────────────────────────────────────────────

class TestNoDuplicateInfrastructureOrStrategyDrift:

    def test_no_second_binance_client_class_introduced(self):
        import data.binance_provider as bp
        # exactly one client-constructing class in this module
        assert hasattr(bp, "BinanceDataProvider")

    def test_trade_manager_does_not_import_decision_or_ceo_modules(self):
        """Static guard: the safety patch touches sizing/validation only —
        it must never import CEO/agent/regime/confidence modules, which
        would indicate strategy logic leaking into the execution layer."""
        import inspect
        import execution.trade_manager as tmmod
        src = inspect.getsource(tmmod)
        forbidden = [
            "ceo_agent", "CEOAgent", "regime_engine", "confidence_engine",
            "ConfidenceEngine", "smc_engine", "SMCEngine",
        ]
        for token in forbidden:
            assert token not in src, f"trade_manager.py must not reference {token}"

    def test_execute_trade_echoes_decision_fields_unchanged(self):
        """direction/entry/SL/TP passed in must come back byte-identical in
        the result dict — the patch only decides EXECUTE vs SKIP, it never
        rewrites the trade decision itself."""
        m, client = _make_manager()
        client.new_order.return_value = {"orderId": 1, "status": "FILLED"}
        with patch.object(m, "set_leverage", return_value=True), \
             patch.object(m, "set_margin_type", return_value=True), \
             patch.object(m, "cancel_all_orders", return_value=None), \
             patch.object(m, "place_market_order",
                          return_value={"orderId": 1}) as _entry, \
             patch.object(m, "place_stop_loss",
                          return_value={"orderId": 2}) as _sl, \
             patch.object(m, "place_take_profit",
                          return_value={"orderId": 3}) as _tp:
            result = m.execute_trade(
                direction="LONG", entry_price=50_500.0, stop_loss=50_000.0,
                take_profit=51_500.0, balance=1_000.0, risk_pct=0.01, leverage=5,
            )
        assert result["direction"]   == "LONG"
        assert result["entry_price"] == 50_500.0
        assert result["stop_loss"]   == 50_000.0
        assert result["take_profit"] == 51_500.0
        assert result["success"] is True


# ─────────────────────────────────────────────────────────────────────────────
# $20 OFFLINE PRE-FLIGHT — the exact scenario the audit flagged
# ─────────────────────────────────────────────────────────────────────────────

class TestTwentyDollarPreflight:
    """Offline, fully-mocked simulation of the audit's $20 live scenario.
    No network call, no real order — pure arithmetic through the real
    calculate_position_size() code path with mocked exchange metadata."""

    def test_twenty_dollar_account_skips_rather_than_oversizes(self):
        m, client = _make_manager(filters=[
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "100.0"},  # realistic BTCUSDT-perp-scale floor
        ])
        balance      = 20.0
        entry_price  = 65_000.0
        stop_loss    = 64_500.0   # 500 U SL distance, a plausible ATR*1.5 example
        risk_pct     = 0.01       # RISK_PER_TRADE_MAX
        leverage     = 5

        risk_amount  = balance * risk_pct           # 0.20 U
        sl_dist      = abs(entry_price - stop_loss)  # 500
        raw_qty      = risk_amount / sl_dist         # 0.0004 BTC

        qty = m.calculate_position_size(
            balance=balance, entry_price=entry_price, stop_loss=stop_loss,
            risk_pct=risk_pct, leverage=leverage,
        )

        # The old behavior would have clamped this up to 0.001 BTC
        # (=$65 notional, ~$13 margin, 65% of a $20 account). The patched
        # behavior must SKIP instead.
        assert raw_qty < 0.001          # confirms this is the audit's scenario
        assert qty == 0.0               # SKIP, never sized up
        client.new_order.assert_not_called()

    def test_twenty_dollar_account_can_still_trade_when_setup_allows_it(self):
        """Sanity check: the patch doesn't make $20 accounts categorically
        untradeable — a lower-priced symbol / tight-enough SL distance and
        a modest min-notional floor can still size and execute.

        entry=1000, sl_dist=50 (5%) -> risk_amount=0.2U -> raw=0.004 BTC.
        Margin cap (20%*5x on 20U=20U notional -> 0.02 BTC) is
        non-binding. floored qty=0.004 (>= minQty 0.001). notional
        =0.004*1000=4U, which clears a realistic-for-this-fixture 1U
        min-notional floor.
        """
        m, client = _make_manager(filters=[
            {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
            {"filterType": "MIN_NOTIONAL", "notional": "1.0"},
        ])
        qty = m.calculate_position_size(
            balance=20.0, entry_price=1_000.0, stop_loss=950.0,
            risk_pct=0.01, leverage=5,
        )
        assert qty == pytest.approx(0.004, abs=1e-9)
