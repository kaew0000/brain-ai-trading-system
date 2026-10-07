"""
Top-down SMC confirmation (pure logic, no I/O).

Implements the sequential structure from the SMC strategy doc as a small
state machine instead of independent score factors:

  1. BIAS     H4 bias matches direction, H1 does not oppose it
  2. ZONE     price is inside an H1 order block / FVG of that direction
  3. CONFIRM  M15 liquidity sweep AND M15 CHoCH, both in that direction
  4. ENTRY    M5 CHoCH + M5 FVG/OB in that direction (skipped, noted
              as m5_used=False, when no M5 data is present)

CONFLICT is evaluated first: any analysed timeframe whose trend bias
opposes the direction means the timeframes disagree.

States: NO_BIAS | CONFLICT | WAIT_BIAS | WAIT_ZONE | WAIT_SWEEP_CHOCH |
        WAIT_ENTRY | READY

Observational by default. ConfidenceEngine only turns a non-READY /
CONFLICT result into a hard block when the matching setting is enabled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config.settings import settings
from features.smc_engine import SMCSignals


def _is_bull(s: str) -> bool:
    return "ullish" in s or s in ("LONG", "LONG_BIAS")


def _is_bear(s: str) -> bool:
    return "earish" in s or s in ("SHORT", "SHORT_BIAS")


def _matches(value: str, direction: str) -> bool:
    return _is_bull(value) if direction == "LONG" else _is_bear(value)


def _opposes(value: str, direction: str) -> bool:
    return _is_bear(value) if direction == "LONG" else _is_bull(value)


@dataclass
class TopDownResult:
    direction: str = ""
    state: str = "NO_BIAS"
    ready: bool = False
    conflict: bool = False
    m5_used: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "direction": self.direction,
            "state": self.state,
            "ready": self.ready,
            "conflict": self.conflict,
            "m5_used": self.m5_used,
            "reasons": list(self.reasons),
        }


def _in_zone(sig: SMCSignals, direction: str, price: float) -> bool:
    tol = settings.SMC_ZONE_TOLERANCE_PCT
    lo_pad, hi_pad = 1 - tol, 1 + tol
    if sig.ob and _matches(sig.ob_direction, direction) and sig.ob_bottom > 0:
        if sig.ob_bottom * lo_pad <= price <= sig.ob_top * hi_pad:
            return True
    if sig.fvg and _matches(sig.fvg_direction, direction) and sig.fvg_bottom > 0:
        if sig.fvg_bottom * lo_pad <= price <= sig.fvg_top * hi_pad:
            return True
    return False


def evaluate_topdown(
    direction: str,
    h4: SMCSignals,
    h1: SMCSignals,
    m15: SMCSignals,
    m5: SMCSignals | None,
    price: float,
) -> TopDownResult:
    """Evaluate the top-down sequence for `direction` ("LONG"|"SHORT"|"")."""
    res = TopDownResult(direction=direction, m5_used=m5 is not None)
    if direction not in ("LONG", "SHORT"):
        return res                                   # NO_BIAS

    # ── Conflict: any timeframe bias against the direction ────────────────
    frames = {"H4": h4, "H1": h1, "M15": m15}
    if m5 is not None:
        frames["M5"] = m5
    opposing = [tf for tf, s in frames.items() if _opposes(s.trend_bias, direction)]
    if m5 is not None and m5.choch and _opposes(m5.choch_direction, direction):
        opposing.append("M5_CHOCH")
    if opposing:
        res.state, res.conflict = "CONFLICT", True
        res.reasons.append(f"opposing: {','.join(opposing)}")
        return res

    # ── 1. Bias ───────────────────────────────────────────────────────────
    if not _matches(h4.trend_bias, direction):
        res.state = "WAIT_BIAS"
        res.reasons.append("H4 bias does not match direction")
        return res

    # ── 2. H1 zone ────────────────────────────────────────────────────────
    if not _in_zone(h1, direction, price):
        res.state = "WAIT_ZONE"
        res.reasons.append("price not inside an H1 OB/FVG")
        return res

    # ── 3. M15 sweep + CHoCH ──────────────────────────────────────────────
    sweep_ok = m15.sweep and _matches(m15.sweep_direction, direction)
    choch_ok = m15.choch and _matches(m15.choch_direction, direction)
    if not (sweep_ok and choch_ok):
        res.state = "WAIT_SWEEP_CHOCH"
        res.reasons.append(f"M15 sweep={bool(sweep_ok)} choch={bool(choch_ok)}")
        return res

    # ── 4. M5 entry trigger (only when M5 data exists) ────────────────────
    if m5 is not None:
        m5_choch = m5.choch and _matches(m5.choch_direction, direction)
        m5_zone = (m5.fvg and _matches(m5.fvg_direction, direction)) or \
                  (m5.ob and _matches(m5.ob_direction, direction))
        if not (m5_choch and m5_zone):
            res.state = "WAIT_ENTRY"
            res.reasons.append(f"M5 choch={bool(m5_choch)} fvg/ob={bool(m5_zone)}")
            return res

    res.state, res.ready = "READY", True
    return res
