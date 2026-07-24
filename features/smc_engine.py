"""
Feature Layer: SMC Engine
Wraps the `smartmoneyconcepts` library (joshyattridge/smart-money-concepts).

Extracts per-timeframe:
  BOS · CHOCH · FVG · Order Block · Liquidity · Previous High/Low · Swing H/L

Usage
-----
engine = SMCEngine()
signals: SMCSignals = engine.analyze(df_m15, "M15")
mtf: dict[str, SMCSignals] = engine.analyze_mtf({"h4": df_h4, "h1": df_h1, "m15": df_m15})
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from smartmoneyconcepts import smc

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data container
# ──────────────────────────────────────────────────────────────────────────────

class SMCSignals:
    """All SMC signals extracted from one timeframe's OHLCV."""

    __slots__ = (
        "bos",
        "bos_direction",
        "choch",
        "choch_direction",
        "fvg",
        "fvg_bottom",
        "fvg_direction",
        "fvg_top",
        "liquidity_high",
        "liquidity_low",
        "ob",
        "ob_bottom",
        "ob_direction",
        "ob_top",
        "prev_high",
        "prev_low",
        "swing_highs",
        "swing_lows",
        "trend_bias",
    )

    def __init__(self) -> None:
        self.bos: bool = False
        self.bos_direction: str = ""       # "Bullish" | "Bearish"
        self.choch: bool = False
        self.choch_direction: str = ""
        self.fvg: bool = False
        self.fvg_direction: str = ""       # "Bullish" | "Bearish"
        self.fvg_top: float = 0.0
        self.fvg_bottom: float = 0.0
        self.ob: bool = False
        self.ob_direction: str = ""
        self.ob_top: float = 0.0
        self.ob_bottom: float = 0.0
        self.liquidity_high: float = 0.0
        self.liquidity_low: float = 0.0
        self.prev_high: float = 0.0
        self.prev_low: float = 0.0
        self.swing_highs: list[float] = []
        self.swing_lows: list[float] = []
        self.trend_bias: str = ""          # "Bullish" | "Bearish" | ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class SMCEngine:
    """
    Stateless wrapper around smartmoneyconcepts.smc.

    Every public method is pure: same input → same output.
    """

    def __init__(self, swing_hl_count: int | None = None) -> None:
        self.swing_hl_count = swing_hl_count or settings.SWING_HL_COUNT
        logger.info(f"SMCEngine | swing_hl_count={self.swing_hl_count}")
        # NOTE: smartmoneyconcepts >= newer versions use 'swing_length' parameter

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _validate(df: pd.DataFrame) -> pd.DataFrame:
        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"SMC: missing columns {missing}")
        out = df[required].copy()
        for col in required:
            out[col] = out[col].astype(float)
        return out.dropna()

    @staticmethod
    def _col_str(series: pd.Series, idx: int) -> str:
        """Safely get string value from a Series by positional index."""
        try:
            val = series.iloc[idx]
            return str(val) if pd.notna(val) else ""
        except Exception:
            return ""

    # ── Signal extractors ─────────────────────────────────────────────────

    def _extract_swing(self, df: pd.DataFrame, signals: SMCSignals) -> pd.DataFrame:
        swing_hl = smc.swing_highs_lows(df, swing_length=self.swing_hl_count)
        if swing_hl is None or len(swing_hl) == 0:
            return swing_hl  # type: ignore[return-value]
        if "HighLow" in swing_hl.columns and "Level" in swing_hl.columns:
            sh = swing_hl[swing_hl["HighLow"] == 1]["Level"].dropna()
            sl = swing_hl[swing_hl["HighLow"] == -1]["Level"].dropna()
            signals.swing_highs = [float(v) for v in sh.tail(5)]
            signals.swing_lows  = [float(v) for v in sl.tail(5)]
        return swing_hl

    def _extract_bos_choch(
        self, df: pd.DataFrame, swing_hl: pd.DataFrame, signals: SMCSignals
    ) -> None:
        bc = smc.bos_choch(df, swing_hl, close_break=True)
        if bc is None or len(bc) == 0:
            return

        # BOS
        if "BOS" in bc.columns:
            bos_rows = bc[bc["BOS"].notna()].tail(3)
            if len(bos_rows) > 0:
                signals.bos = True
                if "Direction" in bos_rows.columns:
                    signals.bos_direction = self._col_str(bos_rows["Direction"], -1)

        # CHOCH
        if "CHOCH" in bc.columns:
            choch_rows = bc[bc["CHOCH"].notna()].tail(3)
            if len(choch_rows) > 0:
                signals.choch = True
                if "Direction" in choch_rows.columns:
                    signals.choch_direction = self._col_str(choch_rows["Direction"], -1)

        # Trend bias from most recent BOS/CHOCH
        # Support both: Direction="Bullish"/"Bearish" and BOS/CHOCH=1/-1 (numeric)
        all_signals = pd.DataFrame()
        if "BOS" in bc.columns and "CHOCH" in bc.columns:
            all_signals = bc[bc["BOS"].notna() | bc["CHOCH"].notna()]
        elif "BOS" in bc.columns:
            all_signals = bc[bc["BOS"].notna()]

        if len(all_signals) > 0:
            if "Direction" in all_signals.columns:
                last_dir = self._col_str(all_signals["Direction"], -1)
                if "Bullish" in last_dir:
                    signals.trend_bias = "Bullish"
                elif "Bearish" in last_dir:
                    signals.trend_bias = "Bearish"
            else:
                # Numeric fallback: BOS/CHOCH column values are 1 (bull) or -1 (bear)
                last_row = all_signals.iloc[-1]
                bos_val   = last_row.get("BOS",   0) if "BOS"   in last_row.index else 0
                choch_val = last_row.get("CHOCH", 0) if "CHOCH" in last_row.index else 0
                # Prefer BOS over CHOCH as trend indicator
                signal = bos_val if pd.notna(bos_val) and bos_val != 0 else choch_val
                if pd.isna(signal):
                    logger.warning("SMC: BOS/CHOCH numeric fallback got NaN — trend_bias left empty")
                    signal = 0.0
                try:
                    signal = float(signal)
                except (TypeError, ValueError):
                    signal = 0.0
                if signal > 0:
                    signals.trend_bias = "Bullish"
                elif signal < 0:
                    signals.trend_bias = "Bearish"

        logger.info(f"TrendBias={signals.trend_bias}")

    def _extract_fvg(
        self, df: pd.DataFrame, current_price: float, signals: SMCSignals
    ) -> None:
        fvg_df = smc.fvg(df, join_consecutive=False)
        if fvg_df is None or len(fvg_df) == 0:
            return

        # Only unmitigated FVGs
        if "FVG" in fvg_df.columns:
            active = fvg_df[fvg_df["FVG"].notna()]
            if "MitigatedIndex" in active.columns:
                active = active[active["MitigatedIndex"].isna() | (active["MitigatedIndex"] == 0)]
            if len(active) == 0:
                return
            last = active.iloc[-1]
            signals.fvg = True
            fvg_val = last["FVG"]
            if isinstance(fvg_val, (int, float, np.integer, np.floating)):
                signals.fvg_direction = "Bullish" if float(fvg_val) > 0 else "Bearish"
            elif isinstance(fvg_val, str):
                signals.fvg_direction = fvg_val
            if "Top" in last.index and pd.notna(last["Top"]):
                signals.fvg_top = float(last["Top"])
            if "Bottom" in last.index and pd.notna(last["Bottom"]):
                signals.fvg_bottom = float(last["Bottom"])

    def _extract_ob(
        self, df: pd.DataFrame, swing_hl: pd.DataFrame,
        current_price: float, signals: SMCSignals
    ) -> None:
        ob_df = smc.ob(df, swing_hl, close_mitigation=False)
        if ob_df is None or len(ob_df) == 0:
            return

        if "OB" not in ob_df.columns:
            return

        active = ob_df[ob_df["OB"].notna()]
        # Keep only unmitigated
        if "MitigatedIndex" in active.columns:
            active = active[active["MitigatedIndex"].isna() | (active["MitigatedIndex"] == 0)]
        if len(active) == 0:
            return

        if "Top" not in active.columns or "Bottom" not in active.columns:
            return

        active = active.copy()
        active["_mid"] = (active["Top"].astype(float) + active["Bottom"].astype(float)) / 2
        active = active[active["_mid"].notna()]
        if len(active) == 0:
            return
        active["_dist"] = (active["_mid"] - current_price).abs()
        closest = active.nsmallest(1, "_dist").iloc[0]

        if pd.isna(closest["Top"]) or pd.isna(closest["Bottom"]):
            logger.warning("SMC: closest OB has NaN Top/Bottom — skipping")
            return

        signals.ob        = True
        signals.ob_top    = float(closest["Top"])
        signals.ob_bottom = float(closest["Bottom"])
        ob_val = closest["OB"]
        if isinstance(ob_val, (int, float, np.integer, np.floating)) and pd.notna(ob_val):
            signals.ob_direction = "Bullish" if float(ob_val) > 0 else "Bearish"

    def _extract_liquidity(
        self, df: pd.DataFrame, swing_hl: pd.DataFrame, signals: SMCSignals
    ) -> None:
        liq_df = smc.liquidity(df, swing_hl, range_percent=0.01)
        if liq_df is None or len(liq_df) == 0:
            return

        if "Liquidity" not in liq_df.columns or "Level" not in liq_df.columns:
            return

        # Unswept liquidity only
        if "Swept" in liq_df.columns:
            liq_df = liq_df[liq_df["Swept"].isna() | (liq_df["Swept"] == 0)]

        highs = liq_df[liq_df["Liquidity"] == 1]["Level"].dropna()
        lows  = liq_df[liq_df["Liquidity"] == -1]["Level"].dropna()

        if len(highs) > 0:
            signals.liquidity_high = float(highs.iloc[-1])
        if len(lows) > 0:
            signals.liquidity_low = float(lows.iloc[-1])

    def _extract_prev_hl(self, df: pd.DataFrame, signals: SMCSignals) -> None:
        prev_df = smc.previous_high_low(df, time_frame="1D")
        if prev_df is None or len(prev_df) == 0:
            return

        if "PreviousHigh" in prev_df.columns:
            ph = prev_df["PreviousHigh"].dropna()
            if len(ph) > 0:
                signals.prev_high = float(ph.iloc[-1])

        if "PreviousLow" in prev_df.columns:
            pl = prev_df["PreviousLow"].dropna()
            if len(pl) > 0:
                signals.prev_low = float(pl.iloc[-1])

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(self, df: pd.DataFrame, label: str = "") -> SMCSignals:
        """
        Run full SMC analysis on one OHLCV DataFrame.
        Returns SMCSignals (never raises; logs errors internally).
        """
        signals = SMCSignals()

        try:
            df = self._validate(df)
            if len(df) < 50:
                logger.warning(f"SMC [{label}] insufficient bars ({len(df)})")
                return signals

            current_price = float(df["close"].iloc[-1])

            swing_hl = self._extract_swing(df, signals)
            if swing_hl is None or len(swing_hl) == 0:
                logger.warning(f"SMC [{label}] swing_hl returned empty")
                return signals

            self._extract_bos_choch(df, swing_hl, signals)
            self._extract_fvg(df, current_price, signals)
            self._extract_ob(df, swing_hl, current_price, signals)
            self._extract_liquidity(df, swing_hl, signals)
            self._extract_prev_hl(df, signals)

            logger.debug(
                f"SMC [{label}] "
                f"BOS={signals.bos}({signals.bos_direction}) "
                f"CHOCH={signals.choch}({signals.choch_direction}) "
                f"FVG={signals.fvg}({signals.fvg_direction}) "
                f"OB={signals.ob}({signals.ob_direction}) "
                f"bias={signals.trend_bias}"
            )

        except Exception as exc:
            logger.error(f"SMC [{label}] error: {exc}", exc_info=True)

        return signals

    def analyze_mtf(self, ohlcv: dict[str, pd.DataFrame]) -> dict[str, SMCSignals]:
        """
        Multi-timeframe analysis.

        Parameters
        ----------
        ohlcv : {"h4": df, "h1": df, "m15": df}

        Returns
        -------
        {"h4": SMCSignals, "h1": SMCSignals, "m15": SMCSignals}
        """
        return {tf: self.analyze(df, label=tf.upper()) for tf, df in ohlcv.items()}
