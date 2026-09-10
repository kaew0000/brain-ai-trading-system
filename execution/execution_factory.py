"""
Execution Factory

Single function that returns the correct execution engine based on
EXECUTION_MODE from settings / .env.

EXECUTION_MODE values
---------------------
  paper    → PaperExecutionEngine  — no real orders, simulated P&L  (DEFAULT)
  testnet  → ExecutionCoordinator  → Binance Futures Testnet (fake money, real API)
  live     → ExecutionCoordinator  → Binance Futures Mainnet (REAL MONEY ⚠️)

V16 Phase 1 (Multi-Symbol Foundation): testnet/live now return an
ExecutionCoordinator instead of a bare TradeManager. This is a pure
architecture change — behavior for the default (or only) symbol is
byte-for-byte identical to before, because ExecutionCoordinator.execute_trade()
mirrors TradeManager.execute_trade()'s exact signature and, with a single
configured symbol, does nothing but forward the call. Paper mode is
untouched (multi-symbol paper trading is out of scope for this phase).

Usage in main.py
----------------
  from execution.execution_factory import build_execution_engine
  trade_manager = build_execution_engine(data_provider)

The returned object exposes:
  execute_trade(direction, entry_price, stop_loss, take_profit,
                balance, risk_pct, leverage=None) → dict{success, quantity, ...}
  (leverage: added in P1-B1, optional, defaults to settings.LEVERAGE —
   see TradeManager.execute_trade and _PaperAdapter.execute_trade docstrings)
  (symbol: added in V16 Phase 1, optional, only meaningful when
   ExecutionCoordinator is managing more than one symbol — see
   ExecutionCoordinator.execute_trade docstring)

fix/execution-coordinator-symbol-mismatch: settings.EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS
(default False) controls whether the returned ExecutionCoordinator accepts
a scanner/ranker-discovered symbol outside settings.symbol_list, instead
of rejecting it — see execution/execution_coordinator.py's __init__
docstring for the full design. Off by default: unchanged behavior.
"""

from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)


def build_execution_engine(data_provider=None, paper_balance: float = 10_000.0):
    """
    Return the execution engine for the current EXECUTION_MODE.

    Parameters
    ----------
    data_provider : BinanceDataProvider — required for testnet / live modes.
    paper_balance : Starting USDT balance for paper trading.

    Returns
    -------
    An object with .execute_trade(direction, entry_price, stop_loss,
                                   take_profit, balance, risk_pct,
                                   leverage=None) → dict
    """
    from config.settings import EXECUTION_MODE, settings

    mode = EXECUTION_MODE.strip().lower()
    logger.info(f"ExecutionFactory: EXECUTION_MODE={mode}")

    if mode == "paper":
        from paper.paper_execution import PaperExecutionEngine
        engine = PaperExecutionEngine(starting_usdt=paper_balance)
        logger.info(f"  → PaperExecutionEngine | balance={paper_balance} USDT")
        return _PaperAdapter(engine)

    if mode in ("testnet", "live"):
        if data_provider is None:
            raise RuntimeError(
                f"EXECUTION_MODE={mode} requires a BinanceDataProvider instance"
            )
        from execution.execution_coordinator import ExecutionCoordinator
        # V16 §61: allow_dynamic_symbols is True whenever EITHER the
        # operator explicitly asked for it OR SCHEDULER_ENABLED is on.
        # Found during §60's own migration write-up: SCANNER_ENABLED +
        # SCHEDULER_ENABLED alone was not enough to actually trade any
        # symbol beyond settings.symbol_list (which defaults to just
        # [settings.SYMBOL]) — MarketScanner/OpportunityRanker discover
        # candidates across the full Binance universe (this class's own
        # module docstring), but every one of them outside that
        # single-symbol default would hit get_manager()'s ValueError
        # ("not configured on this coordinator") the moment the
        # scheduler tried to execute it, since EXECUTION_COORDINATOR_
        # DYNAMIC_SYMBOLS defaults False independently of
        # SCHEDULER_ENABLED. Enabling "trade every symbol the scanner
        # finds" was the entire point of turning SCHEDULER_ENABLED on —
        # requiring a THIRD, separately-discovered flag just to make
        # that actually work was a real gap in what operators need to
        # know, not a deliberate extra safety gate (unlike
        # SCHEDULER_ENABLED itself, or MODEL_PROMOTION_REQUIRES_APPROVAL,
        # which genuinely do gate something worth pausing on). An
        # operator who wants the OPPOSITE — scheduler on, but strictly
        # confined to a fixed symbol list — should set settings.SYMBOLS
        # explicitly rather than relying on this default; that already
        # works today (symbol_list is a superset check either way,
        # dynamic registration only ever ADDS symbols beyond it).
        coordinator = ExecutionCoordinator(
            data_provider,
            symbols=settings.symbol_list,
            allow_dynamic_symbols=(
                settings.EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS or settings.SCHEDULER_ENABLED
            ),
            max_dynamic_symbols=settings.EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS,
        )
        mode_label = "Binance Testnet" if mode == "testnet" else "Binance LIVE ⚠️"
        logger.info(f"  → ExecutionCoordinator | {mode_label} | symbols={coordinator.symbols}")
        return coordinator

    raise ValueError(
        f"Unknown EXECUTION_MODE='{mode}'. "
        f"Must be 'paper', 'testnet', or 'live'."
    )


class _PaperAdapter:
    """
    Adapts PaperExecutionEngine.execute() to the
    TradeManager.execute_trade() interface so main.py
    doesn't need to know which engine is in use.
    """

    def __init__(self, engine):
        self._engine = engine

    def execute_trade(
        self,
        direction:   str,
        entry_price: float,
        stop_loss:   float,
        take_profit: float,
        balance:     float,
        risk_pct:    float = 0.01,
        leverage:    float = None,
        symbol:      str = None,
    ) -> dict:
        """
        Forward to PaperExecutionEngine with a synthetic decision object.

        `leverage` (P1-B1): accepted so main.py can call this adapter and
        TradeManager.execute_trade() with the identical keyword set — but
        NOT forwarded to PaperExecutionEngine. PaperAccount's leverage is
        fixed for the life of the paper session (set once at construction
        in paper/paper_account.py), by design: simulated margin/liquidation
        math assumes one leverage value per account. Making paper mode
        honor per-trade dynamic leverage would mean per-trade margin
        simulation, which is a real change to PaperAccount/PaperPosition,
        not a one-line pass-through — out of scope for P1-B1. Flagging as
        a natural P1-B follow-up if paper-mode fidelity to live leverage
        behavior matters for your testing.

        `symbol` (V16 Phase 1): same story — accepted for interface parity
        with ExecutionCoordinator.execute_trade() so any future caller can
        pass `symbol=` uniformly regardless of execution mode, but NOT
        forwarded. Multi-symbol paper trading (separate simulated balances
        per symbol) is explicitly out of scope for this phase.
        """
        decision = _DecisionStub(
            action      = direction,
            direction   = direction,
            entry_price = entry_price,
            stop_loss   = stop_loss,
            take_profit = take_profit,
        )
        return self._engine.execute(decision, risk_pct=risk_pct)

    def get_metrics(self) -> dict:
        return self._engine.get_metrics()

    # Passthrough for any attribute the engine exposes (e.g. .account)
    def __getattr__(self, name):
        return getattr(self._engine, name)


class _DecisionStub:
    """Minimal duck-type of ConfidenceResult for PaperExecutionEngine."""
    def __init__(self, action, direction, entry_price, stop_loss, take_profit):
        self.action      = action
        self.direction   = direction
        self.entry_price = entry_price
        self.stop_loss   = stop_loss
        self.take_profit = take_profit
        self.confidence  = 0
        self.regime      = ""
        self.oi_delta    = 0.0
        self.funding_rate = 0.0
