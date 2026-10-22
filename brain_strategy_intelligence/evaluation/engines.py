"""Built-in deterministic signal engines.

Strategies reference an engine by NAME; no strategy text or LLM output is ever executed as code.

Contract: fn(window, params, pos) -> target position in {-1, 0, +1}.
`window` contains ONLY bars up to and including the decision bar (the engine physically cannot see the future);
the backtester fills the resulting order at the NEXT bar's open.
Strategies whose category has no engine here (smart money, support/resistance, volume/derivatives) are
knowledge-only: evaluating them yields INCOMPLETE rather than invented numbers.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..schemas import Candle

Params = Mapping[str, int | float | bool | str]


def _need(p: Params, *keys: str) -> None:
    missing = [k for k in keys if k not in p]
    if missing:
        raise ValueError(f"missing parameters: {missing}")


def _int(p: Params, k: str) -> int:
    v = int(p[k])  # type: ignore[arg-type]
    if v < 1:
        raise ValueError(f"{k} must be >= 1")
    return v


def _mean(v: Sequence[float]) -> float:
    return sum(v) / len(v)


def _closes(w: Sequence[Candle]) -> list[float]:
    return [c.close for c in w]


@dataclass(frozen=True)
class Engine:
    name: str
    fn: Callable[[Sequence[Candle], Params, int], int]
    history: Callable[[Params], int]
    validate: Callable[[Params], None]


# ---- sma_cross -------------------------------------------------------------
def _sma_validate(p: Params) -> None:
    _need(p, "fast", "slow")
    if _int(p, "fast") >= _int(p, "slow"):
        raise ValueError("fast must be < slow")


def _sma_cross(w: Sequence[Candle], p: Params, pos: int) -> int:
    f, s = _int(p, "fast"), _int(p, "slow")
    c = _closes(w)
    a, b = _mean(c[-f:]), _mean(c[-s:])
    return 1 if a > b else -1 if a < b else pos


# ---- donchian_breakout -----------------------------------------------------
def _don_validate(p: Params) -> None:
    _need(p, "entry_lookback")
    _int(p, "entry_lookback")
    if "exit_lookback" in p:
        _int(p, "exit_lookback")


def _donchian(w: Sequence[Candle], p: Params, pos: int) -> int:
    n = _int(p, "entry_lookback")
    prev = w[-n - 1 : -1]  # previous n bars, EXCLUDING the decision bar
    close = w[-1].close
    hi, lo = max(c.high for c in prev), min(c.low for c in prev)
    if close > hi:
        return 1
    if close < lo:
        return -1
    if "exit_lookback" in p and pos != 0:
        m = _int(p, "exit_lookback")
        pm = w[-m - 1 : -1]
        if pos > 0 and close < min(c.low for c in pm):
            return 0
        if pos < 0 and close > max(c.high for c in pm):
            return 0
    return pos


# ---- rsi_reversion ---------------------------------------------------------
def _rsi_validate(p: Params) -> None:
    _need(p, "period", "oversold", "overbought")
    _int(p, "period")
    if not 0 < float(p["oversold"]) < float(p["overbought"]) < 100:  # type: ignore[arg-type]
        raise ValueError("require 0 < oversold < overbought < 100")


def _rsi(closes: Sequence[float], period: int) -> float:
    d = [closes[i] - closes[i - 1] for i in range(len(closes) - period, len(closes))]
    gain = sum(x for x in d if x > 0) / period
    loss = sum(-x for x in d if x < 0) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gain / loss)


def _rsi_reversion(w: Sequence[Candle], p: Params, pos: int) -> int:
    r = _rsi(_closes(w), _int(p, "period"))
    exit_level = float(p.get("exit_level", 50.0))  # type: ignore[arg-type]
    if pos == 0:
        return 1 if r < float(p["oversold"]) else -1 if r > float(p["overbought"]) else 0  # type: ignore[arg-type]
    if pos > 0 and r >= exit_level:
        return 0
    if pos < 0 and r <= exit_level:
        return 0
    return pos


# ---- roc_momentum ----------------------------------------------------------
def _roc_validate(p: Params) -> None:
    _need(p, "lookback", "threshold_pct")
    _int(p, "lookback")
    if float(p["threshold_pct"]) <= 0:  # type: ignore[arg-type]
        raise ValueError("threshold_pct must be > 0")


def _roc(w: Sequence[Candle], p: Params, pos: int) -> int:
    n = _int(p, "lookback")
    roc = (w[-1].close / w[-1 - n].close - 1.0) * 100.0
    thr = float(p["threshold_pct"])  # type: ignore[arg-type]
    return 1 if roc > thr else -1 if roc < -thr else 0


# ---- bb_squeeze_breakout (volatility) --------------------------------------
def _bb_validate(p: Params) -> None:
    _need(p, "period", "num_std", "squeeze_bandwidth_pct")
    if _int(p, "period") < 5:
        raise ValueError("period must be >= 5")


def _bands(closes: Sequence[float], n: int, k: float) -> tuple[float, float, float]:
    seg = closes[-n:]
    m = _mean(seg)
    sd = math.sqrt(sum((x - m) ** 2 for x in seg) / n)
    return m - k * sd, m, m + k * sd


def _bb(w: Sequence[Candle], p: Params, pos: int) -> int:
    n, k = _int(p, "period"), float(p["num_std"])  # type: ignore[arg-type]
    c = _closes(w)
    lo, mid, hi = _bands(c, n, k)
    plo, pmid, phi = _bands(c[:-1], n, k)
    squeezed_before = (phi - plo) / pmid * 100.0 <= float(p["squeeze_bandwidth_pct"])  # type: ignore[arg-type]
    if squeezed_before and c[-1] > hi:
        return 1
    if squeezed_before and c[-1] < lo:
        return -1
    if (pos > 0 and c[-1] < mid) or (pos < 0 and c[-1] > mid):
        return 0
    return pos


# ---- mtf_confluence (lookback-scaled proxy for multi-timeframe agreement) ---
def _mtf_validate(p: Params) -> None:
    _need(p, "fast", "slow", "htf_factor")
    if _int(p, "fast") >= _int(p, "slow") or _int(p, "htf_factor") < 2:
        raise ValueError("require fast < slow and htf_factor >= 2")


def _mtf(w: Sequence[Candle], p: Params, pos: int) -> int:
    f, s, k = _int(p, "fast"), _int(p, "slow"), _int(p, "htf_factor")
    c = _closes(w)
    base = 1 if _mean(c[-f:]) > _mean(c[-s:]) else -1
    htf = 1 if c[-1] > _mean(c[-s * k :]) else -1
    return base if base == htf else 0


ENGINES: dict[str, Engine] = {
    "sma_cross": Engine("sma_cross", _sma_cross, lambda p: _int(p, "slow") + 1, _sma_validate),
    "donchian_breakout": Engine(
        "donchian_breakout",
        _donchian,
        lambda p: max(_int(p, "entry_lookback"), _int(p, "exit_lookback") if "exit_lookback" in p else 1) + 1,
        _don_validate,
    ),
    "rsi_reversion": Engine("rsi_reversion", _rsi_reversion, lambda p: _int(p, "period") + 1, _rsi_validate),
    "roc_momentum": Engine("roc_momentum", _roc, lambda p: _int(p, "lookback") + 1, _roc_validate),
    "bb_squeeze_breakout": Engine("bb_squeeze_breakout", _bb, lambda p: _int(p, "period") + 1, _bb_validate),
    "mtf_confluence": Engine("mtf_confluence", _mtf, lambda p: _int(p, "slow") * _int(p, "htf_factor"), _mtf_validate),
}


def get_engine(name: str | None) -> Engine | None:
    return ENGINES.get(name) if name else None
