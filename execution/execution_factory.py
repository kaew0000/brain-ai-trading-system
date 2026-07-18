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
        coordinator = ExecutionCoordinator(data_provider, symbols=settings.symbol_list)
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
