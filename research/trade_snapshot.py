"""research/trade_snapshot.py + dataset_builder.py — Phase 3B capture & export"""
from __future__ import annotations
from utils.logger import get_logger
logger = get_logger(__name__)

def _sf(v, fb=None, default=0.0):
    for c in (v, fb):
        if c is None: continue
        try: return float(c)
        except Exception: continue
    return default

def build_feature_vector(mission=None, trade_row: dict | None=None,
                          market_context: dict | None=None,
                          intelligence: dict | None=None) -> dict:
    try:
        mm = (mission.meta if mission is not None else {}) or {}
        tr = trade_row or {}; mc = market_context or {}; intel = intelligence or {}
        direction = getattr(mission,"direction",None) or tr.get("direction","")
        confidence = _sf(getattr(mission,"confidence",None) if mission else None,
                         fb=tr.get("confidence"), default=0.0)
        futures_ctx = mc.get("futures",{}) or {}
        funding = _sf(mm.get("funding"), fb=tr.get("funding") or
                      (futures_ctx.get("funding",{}) or {}).get("rate"), default=0.0)
        oi = _sf(mm.get("open_interest"), fb=(futures_ctx.get("open_interest",{}) or {}).get("value"), default=0.0)
        oid = _sf(mm.get("oi_delta"), fb=tr.get("oi_delta"), default=0.0)
        liq = intel.get("liquidations") or futures_ctx.get("liquidation",{}) or {}
        liq_sig = 1.0 if liq.get("detected") else 0.0
        fg = intel.get("fear_greed") or {}
        fg_val = fg.get("value")
        fear_greed = float(fg_val) if fg_val is not None else 50.0
        regime = (mm.get("regime") or tr.get("regime") or mc.get("regime","") or "")
        rd = mc.get("regime_data",{}) or {}
        atr_n = _sf(rd.get("atr_normalized"), default=0.0)
        smc = mc.get("smc_m15",{}) or {}; vol = mc.get("volume",{}) or {}
        return {
            "direction": direction, "confidence": confidence, "funding": funding,
            "open_interest": oi, "oi_delta": oid, "liquidation_signal": liq_sig,
            "fear_greed": fear_greed, "regime": regime, "volatility": atr_n, "atr": atr_n,
            "smc_score": _sf(smc.get("score")), "volume_score": _sf(vol.get("score")),
            "entry_price": _sf(tr.get("entry_price")), "stop_loss": _sf(tr.get("stop_loss")),
            "take_profit": _sf(tr.get("take_profit")),
        }
    except Exception as exc:
        logger.error(f"build_feature_vector failed: {exc}", exc_info=True)
        return {"direction":"","confidence":0.0,"funding":0.0,"open_interest":0.0,"oi_delta":0.0,
                "liquidation_signal":0.0,"fear_greed":50.0,"regime":"","volatility":0.0,"atr":0.0,
                "smc_score":0.0,"volume_score":0.0,"entry_price":0.0,"stop_loss":0.0,"take_profit":0.0}

def build_outcome(trade_row: dict):
    try:
        outcome = (trade_row.get("result") or "").upper()
        result = 1.0 if outcome=="WIN" else (0.0 if outcome=="LOSS" else None)
        pnl = _sf(trade_row.get("pnl"), default=None)
        ht = None
        opened = trade_row.get("timestamp"); closed = trade_row.get("closed_at") or trade_row.get("exit_timestamp")
        if opened and closed:
            try:
                from datetime import datetime
                ht = (datetime.fromisoformat(closed) - datetime.fromisoformat(opened)).total_seconds()
            except Exception: pass
        return result, pnl, ht
    except Exception as exc:
        logger.error(f"build_outcome failed: {exc}", exc_info=True)
        return None, None, None
