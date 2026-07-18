"""
Futures Intelligence Engine (Layer 6)

Extracts signals from crypto-futures-specific data that does not exist in
spot or traditional markets: Open Interest, Funding Rate, Long/Short Ratio,
Taker Buy/Sell Ratio, Liquidations.

Future extension points are defined as abstract interfaces (Protocol) and
raise NotImplementedError so the dashboard's debug panel can report which
features are live vs. stub, without breaking the pipeline.

Extension interfaces (DEFINED, NOT YET IMPLEMENTED)
-----------------------------------------------------
- orderbook_imbalance  : bid/ask delta from level-2 order book
- cvd                  : cumulative volume delta (buy vs sell volume)
- liquidation_heatmap  : liquidation cluster levels from open interest profile

Currently implemented
---------------------
- funding              : rate, annualised, extreme-flag, bias
- open_interest        : delta%, trend, institutional pressure signal
- long_short_ratio     : crowd sentiment, contrarian signal
- taker_ratio          : aggressor side dominance
- liquidation          : recent event detection from OI + price divergence

Output: FuturesIntelResult
--------------------------
{
  "signal":       "LONG" | "SHORT" | "NEUTRAL",
  "condition":    "SQUEEZE" | "SHORT_COVERING" | "LONG_LIQUIDATION" | "ORGANIC_LONG" |
                  "ORGANIC_SHORT" | "NEUTRAL",
  "confidence":   float 0-1,
  "funding":      { rate, annualised, extreme, bias },
  "open_interest":{ delta_pct, trend, pressure },
  "long_short":   { ratio, crowd_bias, contrarian_signal },
  "taker":        { buy_ratio, sell_ratio, aggressor },
  "liquidation":  { detected, type, severity },
  "extensions":   { "orderbook_imbalance": "NOT_IMPLEMENTED",
                    "cvd": "NOT_IMPLEMENTED",
                    "liquidation_heatmap": "NOT_IMPLEMENTED" }
}

API surface: GET /api/funding  (includes funding + oi + l/s + taker subkeys)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Thresholds (override via config profile) ──────────────────────────────────
FUNDING_EXTREME_THRESHOLD  = 0.0005    # |rate| > 0.05% per 8h → extreme
FUNDING_BIAS_THRESHOLD     = 0.0001    # |rate| > 0.01% → slight bias
OI_STRONG_DELTA            = 0.01      # >1% OI delta in window = strong move
OI_WEAK_DELTA              = 0.003     # >0.3% = weak move
LS_CROWD_LONG              = 1.20      # ratio > 1.2 → longs crowded
LS_CROWD_SHORT             = 0.80      # ratio < 0.8 → shorts crowded
TAKER_DOMINANT_THRESHOLD   = 0.55      # >55% one side = aggressor dominance


# ──────────────────────────────────────────────────────────────────────────────
# Sub-result dataclasses
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FundingSignal:
    rate:        float = 0.0
    annualised:  float = 0.0    # rate * 3 * 365 * 100  (%)
    extreme:     bool  = False
    bias:        str   = "NEUTRAL"   # "LONG_PAYING" | "SHORT_PAYING" | "NEUTRAL"


@dataclass
class OISignal:
    delta_pct:  float = 0.0
    trend:      str   = "FLAT"       # "RISING" | "FALLING" | "FLAT"
    pressure:   str   = "NEUTRAL"    # "BUY_PRESSURE" | "SELL_PRESSURE" | "NEUTRAL"


@dataclass
class LongShortSignal:
    ratio:             float = 1.0
    crowd_bias:        str   = "NEUTRAL"   # "LONG_CROWDED" | "SHORT_CROWDED" | "NEUTRAL"
    contrarian_signal: str   = "NONE"      # "FADE_LONGS" | "FADE_SHORTS" | "NONE"


@dataclass
class TakerSignal:
    buy_ratio:  float = 0.5
    sell_ratio: float = 0.5
    aggressor:  str   = "BALANCED"   # "BUYERS" | "SELLERS" | "BALANCED"


@dataclass
class LiquidationSignal:
    detected: bool  = False
    liq_type: str   = "NONE"      # "LONG_SQUEEZE" | "SHORT_SQUEEZE" | "NONE"
    severity: str   = "NONE"      # "HIGH" | "MEDIUM" | "LOW" | "NONE"


# ──────────────────────────────────────────────────────────────────────────────
# Main result
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FuturesIntelResult:
    signal:        str  = "NEUTRAL"  # LONG | SHORT | NEUTRAL
    condition:     str  = "NEUTRAL"  # see module docstring
    confidence:    float = 0.0

    funding:       FundingSignal    = field(default_factory=FundingSignal)
    open_interest: OISignal         = field(default_factory=OISignal)
    long_short:    LongShortSignal  = field(default_factory=LongShortSignal)
    taker:         TakerSignal      = field(default_factory=TakerSignal)
    liquidation:   LiquidationSignal = field(default_factory=LiquidationSignal)

    # Not-yet-implemented extension slots
    extensions: dict = field(default_factory=lambda: {
        "orderbook_imbalance":  "NOT_IMPLEMENTED",
        "cvd":                  "NOT_IMPLEMENTED",
        "liquidation_heatmap":  "NOT_IMPLEMENTED",
    })

    def to_dict(self) -> dict:
        d = asdict(self)
        # Flatten sub-dicts for JSON readability; keep extensions at top level
        d["liquidation"]["liq_type"] = d["liquidation"].pop("liq_type", "NONE")
        # Round floats
        def _round(obj):
            if isinstance(obj, dict):
                return {k: _round(v) for k, v in obj.items()}
            if isinstance(obj, float):
                return round(obj, 6)
            return obj
        return _round(d)

    # Convenience shortcuts used by DecisionEngine / ConfidenceEngine
    def blocks_long(self) -> bool:
        """Return True if futures data should BLOCK a LONG entry."""
        return (
            self.funding.extreme and self.funding.bias == "LONG_PAYING"
            or self.condition == "SHORT_COVERING"
            or self.liquidation.liq_type == "LONG_SQUEEZE"
        )

    def blocks_short(self) -> bool:
        """Return True if futures data should BLOCK a SHORT entry."""
        return (
            self.funding.extreme and self.funding.bias == "SHORT_PAYING"
            or self.condition == "LONG_LIQUIDATION"
            or self.liquidation.liq_type == "SHORT_SQUEEZE"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class FuturesIntelEngine:
    """
    Stateless analyser. Call analyse(market_data) after each data fetch cycle.

    market_data is the dict returned by BinanceDataProvider.get_all_market_data():
      {
        "mark_price":       float,
        "funding_rate":     float,
        "oi_delta":         float,    # pct change since last period
        "open_interest":    float,    # current OI (contracts)
        "long_short_ratio": dict,     # {"longShortRatio": "1.15", ...}
        "taker_ratio":      dict,     # {"buySellRatio": "1.05", ...}
        ...
      }
    """

    def __init__(self) -> None:
        logger.info("FuturesIntelEngine ready")

    # ── Public ────────────────────────────────────────────────────────────────

    def analyse(self, market_data: dict) -> FuturesIntelResult:
        result = FuturesIntelResult()

        if not market_data:
            logger.warning("FuturesIntelEngine: empty market_data")
            return result

        result.funding       = self._analyse_funding(market_data)
        result.open_interest = self._analyse_oi(market_data)
        result.long_short    = self._analyse_long_short(market_data)
        result.taker         = self._analyse_taker(market_data)
        result.liquidation   = self._analyse_liquidation(market_data)

        # Extension stubs — always NOT_IMPLEMENTED until wired
        result.extensions = self._extension_stubs(market_data)

        result.signal, result.condition, result.confidence = self._determine_signal(result)

        logger.debug(
            f"FuturesIntel | signal={result.signal} condition={result.condition} "
            f"conf={result.confidence:.2f} funding={result.funding.rate:.5f} "
            f"oi_delta={result.open_interest.delta_pct:.4f} "
            f"ls_ratio={result.long_short.ratio:.3f}"
        )
        return result

    # ── Funding ───────────────────────────────────────────────────────────────

    @staticmethod
    def _analyse_funding(md: dict) -> FundingSignal:
        sig = FundingSignal()
        rate = float(md.get("funding_rate", 0.0))
        if not _is_valid(rate):
            return sig

        sig.rate        = rate
        sig.annualised  = round(rate * 3 * 365 * 100, 4)   # %
        sig.extreme     = abs(rate) >= FUNDING_EXTREME_THRESHOLD

        if rate > FUNDING_BIAS_THRESHOLD:
            sig.bias = "LONG_PAYING"    # longs pay shorts → bearish pressure
        elif rate < -FUNDING_BIAS_THRESHOLD:
            sig.bias = "SHORT_PAYING"   # shorts pay longs → bullish pressure
        else:
            sig.bias = "NEUTRAL"

        return sig

    # ── Open Interest ─────────────────────────────────────────────────────────

    @staticmethod
    def _analyse_oi(md: dict) -> OISignal:
        sig = OISignal()
        delta = float(md.get("oi_delta", 0.0))
        if not _is_valid(delta):
            return sig

        sig.delta_pct = delta

        if delta > OI_WEAK_DELTA:
            sig.trend    = "RISING"
            sig.pressure = "BUY_PRESSURE"
        elif delta < -OI_WEAK_DELTA:
            sig.trend    = "FALLING"
            sig.pressure = "SELL_PRESSURE"
        else:
            sig.trend    = "FLAT"
            sig.pressure = "NEUTRAL"

        return sig

    # ── Long / Short Ratio ────────────────────────────────────────────────────

    @staticmethod
    def _analyse_long_short(md: dict) -> LongShortSignal:
        sig = LongShortSignal()
        ls_data = md.get("long_short_ratio", {})
        if not ls_data:
            return sig

        try:
            ratio = float(ls_data.get("longShortRatio", ls_data.get("longAccount", 1.0)))
        except (TypeError, ValueError):
            return sig

        if not _is_valid(ratio):
            return sig

        sig.ratio = ratio

        if ratio > LS_CROWD_LONG:
            sig.crowd_bias        = "LONG_CROWDED"
            sig.contrarian_signal = "FADE_LONGS"   # crowd is long → smart money shorts
        elif ratio < LS_CROWD_SHORT:
            sig.crowd_bias        = "SHORT_CROWDED"
            sig.contrarian_signal = "FADE_SHORTS"  # crowd is short → smart money longs
        else:
            sig.crowd_bias        = "NEUTRAL"
            sig.contrarian_signal = "NONE"

        return sig

    # ── Taker Ratio ───────────────────────────────────────────────────────────

    @staticmethod
    def _analyse_taker(md: dict) -> TakerSignal:
        sig = TakerSignal()
        taker_data = md.get("taker_ratio", {})
        if not taker_data:
            return sig

        try:
            buy_sell = float(taker_data.get("buySellRatio", 1.0))
        except (TypeError, ValueError):
            return sig

        if not _is_valid(buy_sell):
            return sig

        # buySellRatio > 1 → more buy takers
        total = buy_sell + 1.0
        buy_r  = buy_sell / total
        sell_r = 1.0 / total

        sig.buy_ratio  = round(buy_r,  4)
        sig.sell_ratio = round(sell_r, 4)

        if buy_r >= TAKER_DOMINANT_THRESHOLD:
            sig.aggressor = "BUYERS"
        elif sell_r >= TAKER_DOMINANT_THRESHOLD:
            sig.aggressor = "SELLERS"
        else:
            sig.aggressor = "BALANCED"

        return sig

    # ── Liquidation (OI-divergence heuristic) ────────────────────────────────

    @staticmethod
    def _analyse_liquidation(md: dict) -> LiquidationSignal:
        """
        Heuristic: liquidation cascade is inferred from the combination of
        price direction + OI direction without a dedicated liquidation feed.

        LONG_SQUEEZE  : price ↓ fast + OI ↓ fast  (longs blown out)
        SHORT_SQUEEZE : price ↑ fast + OI ↓ fast  (shorts blown out)

        When a proper liquidation WebSocket feed is available, replace this
        with real data (extension: liquidation_heatmap).
        """
        sig = LiquidationSignal()
        oi_delta = float(md.get("oi_delta", 0.0))
        mark     = float(md.get("mark_price", 0.0))
        prev     = float(md.get("prev_mark_price", 0.0))

        if not _is_valid(oi_delta) or mark <= 0 or prev <= 0:
            return sig

        price_chg = (mark - prev) / prev if prev else 0.0
        oi_drop   = oi_delta < -0.005          # OI fell > 0.5%
        price_up   = price_chg >  0.005        # price rose > 0.5%
        price_down = price_chg < -0.005        # price fell > 0.5%

        if oi_drop and price_down:
            sig.detected = True
            sig.liq_type = "LONG_SQUEEZE"
            sig.severity = "HIGH" if abs(oi_delta) > 0.02 else "MEDIUM"
        elif oi_drop and price_up:
            sig.detected = True
            sig.liq_type = "SHORT_SQUEEZE"
            sig.severity = "HIGH" if abs(oi_delta) > 0.02 else "MEDIUM"
        else:
            sig.detected = False
            sig.liq_type = "NONE"
            sig.severity = "NONE"

        return sig

    # ── Extension stubs ───────────────────────────────────────────────────────

    @staticmethod
    def _extension_stubs(md: dict) -> dict:
        """
        Placeholder for future extensions.
        Each key maps to "NOT_IMPLEMENTED" until the real analysis is wired.

        orderbook_imbalance : requires Level-2 order book WebSocket
        cvd                 : requires tick-level aggressor data
        liquidation_heatmap : requires Binance liquidation WebSocket
        """
        return {
            "orderbook_imbalance": "NOT_IMPLEMENTED",   # TODO: L2 orderbook
            "cvd":                 "NOT_IMPLEMENTED",   # TODO: tick CVD
            "liquidation_heatmap": "NOT_IMPLEMENTED",   # TODO: liq WebSocket
        }

    # ── Signal determination ──────────────────────────────────────────────────

    @staticmethod
    def _determine_signal(r: FuturesIntelResult) -> tuple[str, str, float]:
        """
        Combine sub-signals into a single directional signal + condition label.

        Priority (hard blocks first):
        1. Extreme funding → block direction that pays; set condition
        2. Liquidation squeeze → set condition
        3. Short covering (price up + OI down, not squeeze) → NEUTRAL
        4. Long liquidation (price down + OI up) → SHORT bias
        5. OI + taker alignment → LONG or SHORT with confidence score
        6. Default → NEUTRAL
        """
        fund = r.funding
        oi   = r.open_interest
        ls   = r.long_short
        tak  = r.taker
        liq  = r.liquidation

        # ── Squeeze conditions (override everything) ──────────────────────────
        if liq.detected:
            if liq.liq_type == "LONG_SQUEEZE":
                return "SHORT", "LONG_LIQUIDATION", 0.80
            if liq.liq_type == "SHORT_SQUEEZE":
                return "LONG", "SQUEEZE", 0.75

        # ── Score system (max 6) ──────────────────────────────────────────────
        long_score  = 0
        short_score = 0

        # Funding: SHORT_PAYING = longs being rewarded → bullish
        if fund.bias == "SHORT_PAYING":  long_score  += 1
        elif fund.bias == "LONG_PAYING": short_score += 1

        # OI rising with buy pressure
        if oi.pressure == "BUY_PRESSURE":   long_score  += 2
        elif oi.pressure == "SELL_PRESSURE": short_score += 2

        # Taker aggressor
        if tak.aggressor == "BUYERS":   long_score  += 1
        elif tak.aggressor == "SELLERS": short_score += 1

        # L/S contrarian
        if ls.contrarian_signal == "FADE_SHORTS": long_score  += 1
        elif ls.contrarian_signal == "FADE_LONGS": short_score += 1

        # Extreme funding blocks the paid direction
        if fund.extreme and fund.bias == "LONG_PAYING":
            long_score = max(0, long_score - 2)
        if fund.extreme and fund.bias == "SHORT_PAYING":
            short_score = max(0, short_score - 2)

        max_score = 5  # max achievable without squeeze bonus
        leading   = max(long_score, short_score)
        conf      = round(min(leading / max_score, 1.0), 4)

        if long_score >= 3 and long_score > short_score:
            # Detect short covering (price up + oi down) vs organic
            if oi.trend == "FALLING":
                return "NEUTRAL", "SHORT_COVERING", conf
            return "LONG", "ORGANIC_LONG", conf

        if short_score >= 3 and short_score > long_score:
            if oi.trend == "FALLING":
                return "NEUTRAL", "LONG_LIQUIDATION", conf
            return "SHORT", "ORGANIC_SHORT", conf

        return "NEUTRAL", "NEUTRAL", conf


# ── Utility ───────────────────────────────────────────────────────────────────

def _is_valid(val: float) -> bool:
    import math
    return not (math.isnan(val) or math.isinf(val))
