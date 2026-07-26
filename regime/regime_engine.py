"""
Regime Layer: Live Market Regime Classifier
Based on: akash-kumar5/Live-Market-Regime-Classifier

Classifies one of four regimes:
  TREND    – directional move, high ADX
  RANGE    – mean-reverting, low ADX, moderate BB width
  VOLATILE – wide, erratic swings (high ATR + wide BB)
  SQUEEZE  – compressed volatility, very tight BB (pre-breakout)

Method
------
Primary  : Rule-based (ADX · BB Width · normalised ATR)
Secondary: 3-state Gaussian HMM blended 30 / 70 with rule output

This engine ONLY classifies. It never generates trade signals.

Output
------
RegimeResult.regime      : str  ("TREND" | "RANGE" | "VOLATILE" | "SQUEEZE")
RegimeResult.confidence  : float  0–1
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import warnings

import ta
from hmmlearn import hmm
from sklearn.preprocessing import StandardScaler

from utils.logger import get_logger

logger = get_logger(__name__)

# silence convergence / precision warnings from hmmlearn
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)


# ──────────────────────────────────────────────────────────────────────────────
# Data container
# ──────────────────────────────────────────────────────────────────────────────

class RegimeResult:
    REGIMES = ("TREND", "RANGE", "VOLATILE", "SQUEEZE")

    def __init__(self) -> None:
        self.regime: str = "RANGE"
        self.confidence: float = 0.5
        self.adx: float = 0.0
        self.bb_width: float = 0.0
        self.atr_normalized: float = 0.0
        self.probabilities: dict[str, float] = {}

    def to_dict(self) -> dict:
        return {
            "regime":         self.regime,
            "confidence":     round(self.confidence, 4),
            "adx":            round(self.adx, 2),
            "bb_width":       round(self.bb_width, 6),
            "atr_normalized": round(self.atr_normalized, 6),
            "probabilities":  {k: round(v, 4) for k, v in self.probabilities.items()},
        }


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class RegimeEngine:
    """
    Regime classification engine.

    Parameters
    ----------
    use_hmm : bool
        If True, fit a Gaussian HMM per symbol on that symbol's first
        call to classify(), and blend with the rule-based output.
        (Phase 4B Step 3A: previously fit once, globally, on whichever
        symbol's data reached classify() first, and silently reused for
        every other symbol — see self.models in __init__.)
    hmm_n_components : int
        Number of hidden states (3 recommended).
    """

    # ── Rule thresholds ───────────────────────────────────────────────────
    ADX_TREND_THRESHOLD   = 25.0
    ADX_STRONG_TREND      = 40.0
    BB_SQUEEZE_THRESHOLD  = 0.02    # very tight
    BB_RANGE_THRESHOLD    = 0.04
    BB_VOLATILE_THRESHOLD = 0.08
    ATR_VOLATILE_THRESHOLD = 0.015  # 1.5 % of price

    def __init__(self, use_hmm: bool = True, hmm_n_components: int = 3) -> None:
        self.use_hmm         = use_hmm
        self.hmm_n_components = hmm_n_components
        self._scaler          = StandardScaler()
        # Phase 4B Step 3A: one fitted HMM per symbol, keyed by the
        # `symbol` argument classify() now accepts. Presence of a key
        # means "fitted for that symbol" — replaces the old single
        # self._hmm_model/self._fitted pair, which meant a model fit on
        # whichever symbol's data reached classify() first was silently
        # reused forever for every other symbol (the audit finding this
        # bundle addresses — see docs/architecture.md's Phase 4B Step 3A
        # section for the empirical reproduction).
        #
        # Callers that don't pass `symbol` to classify() (every existing
        # caller as of this commit — main.py's legacy single-symbol loop,
        # execution/portfolio_signal_provider.py) all map to the same
        # _DEFAULT_MODEL_KEY, reproducing the exact prior one-shared-model
        # behavior byte-for-byte. This intentionally does NOT yet fix
        # cross-symbol contamination for those callers — wiring an actual
        # `symbol=` argument through them is explicitly out of scope for
        # this bundle (see PATCH_NOTES.md's "Known limitation" section);
        # this class only builds the capability.
        self.models: dict[str, hmm.GaussianHMM] = {}
        logger.info(f"RegimeEngine | use_hmm={use_hmm} components={hmm_n_components}")

    _DEFAULT_MODEL_KEY = "_default"

    # ── Feature engineering ───────────────────────────────────────────────

    @staticmethod
    def _compute_features(df: pd.DataFrame) -> pd.DataFrame:
        """Compute ADX, BB width, normalised ATR, and log-returns."""
        df = df.copy()

        adx_ind = ta.trend.ADXIndicator(
            high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True
        )
        df["adx"] = adx_ind.adx()

        bb_ind = ta.volatility.BollingerBands(
            close=df["close"], window=20, window_dev=2, fillna=True
        )
        bb_hi  = bb_ind.bollinger_hband()
        bb_lo  = bb_ind.bollinger_lband()
        bb_mid = bb_ind.bollinger_mavg()
        df["bb_width"] = (bb_hi - bb_lo) / bb_mid.replace(0, np.nan)

        atr_ind = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=14, fillna=True
        )
        df["atr"] = atr_ind.average_true_range()
        df["atr_normalized"] = df["atr"] / df["close"].replace(0, np.nan)

        df["log_ret"] = np.log(df["close"] / df["close"].shift(1))

        return df.dropna()

    # ── Rule-based classification ─────────────────────────────────────────

    def _rule_regime(
        self, adx: float, bb_width: float, atr_norm: float
    ) -> tuple[str, float]:
        """
        Priority order: SQUEEZE → VOLATILE → TREND → RANGE.
        Returns (regime_name, confidence 0–1).
        """
        # SQUEEZE
        if bb_width < self.BB_SQUEEZE_THRESHOLD and adx < self.ADX_TREND_THRESHOLD:
            conf = min(1.0, (self.BB_SQUEEZE_THRESHOLD - bb_width) / self.BB_SQUEEZE_THRESHOLD + 0.4)
            return "SQUEEZE", float(np.clip(conf, 0.55, 0.95))

        # VOLATILE
        if atr_norm > self.ATR_VOLATILE_THRESHOLD and bb_width > self.BB_VOLATILE_THRESHOLD:
            conf = min(1.0, (atr_norm / self.ATR_VOLATILE_THRESHOLD) * 0.55)
            return "VOLATILE", float(np.clip(conf, 0.55, 0.95))

        # TREND
        if adx >= self.ADX_TREND_THRESHOLD:
            conf = (adx - self.ADX_TREND_THRESHOLD) / max(
                self.ADX_STRONG_TREND - self.ADX_TREND_THRESHOLD, 1e-9
            )
            return "TREND", float(np.clip(conf, 0.55, 0.95))

        # RANGE (default)
        conf = (self.ADX_TREND_THRESHOLD - adx) / max(self.ADX_TREND_THRESHOLD, 1e-9)
        return "RANGE", float(np.clip(conf, 0.45, 0.90))

    # ── HMM ──────────────────────────────────────────────────────────────

    def _fit_hmm(self, X: np.ndarray, symbol_key: str) -> None:
        try:
            model = hmm.GaussianHMM(
                n_components=self.hmm_n_components,
                covariance_type="diag",
                n_iter=100,
                random_state=42,
                verbose=False,
            )
            model.fit(X)
            self.models[symbol_key] = model
            logger.info(f"HMM fitted | symbol={symbol_key} states={self.hmm_n_components}")
        except Exception as exc:
            logger.warning(f"HMM fit failed ({exc}); using rule-based only")
            self.use_hmm = False

    def _hmm_probabilities(self, X: np.ndarray, symbol_key: str) -> dict[str, float]:
        model = self.models.get(symbol_key)
        if model is None:
            return {}
        try:
            _, posteriors = model.score_samples(X)
            probs = posteriors[-1]                    # shape (n_components,)

            # Map HMM states → regime names by variance ordering
            # "diag" covars_ shape: (n_components, n_features)
            state_var = [float(np.mean(model.covars_[i]))
                         for i in range(self.hmm_n_components)]
            order = np.argsort(state_var)             # lowest → highest variance

            label_map: dict[int, str] = {}
            n = self.hmm_n_components
            if n >= 4:
                label_map[order[0]] = "SQUEEZE"
                label_map[order[1]] = "RANGE"
                label_map[order[2]] = "TREND"
                label_map[order[3]] = "VOLATILE"
            elif n == 3:
                label_map[order[0]] = "SQUEEZE"
                label_map[order[1]] = "RANGE"
                label_map[order[2]] = "VOLATILE"
            else:
                label_map[order[0]] = "RANGE"
                label_map[order[1]] = "VOLATILE"

            return {label_map.get(i, f"S{i}"): float(p)
                    for i, p in enumerate(probs)}
        except Exception as exc:
            logger.warning(f"HMM score failed: {exc}")
            return {}

    # ── Public API ────────────────────────────────────────────────────────

    def classify(self, df: pd.DataFrame, symbol: str | None = None) -> RegimeResult:
        """
        Classify current market regime from OHLCV data.

        Recommended input: H1 or H4 OHLCV DataFrame.

        Parameters
        ----------
        symbol : which symbol this OHLCV data is for. Optional — omit for
            the existing single-symbol callers (main.py's legacy loop,
            execution/portfolio_signal_provider.py as of this commit),
            which all fall back to one shared model key, identical to
            this class's behavior before Phase 4B Step 3A. Passing an
            explicit symbol gives that symbol its own independently-fit
            HMM, never reused for a different symbol (see self.models's
            docstring in __init__ for the audit finding this addresses).

        Returns
        -------
        RegimeResult (never raises; falls back to RANGE on error)
        """
        result = RegimeResult()
        symbol_key = symbol or self._DEFAULT_MODEL_KEY

        try:
            if len(df) < 50:
                logger.warning(f"RegimeEngine: insufficient bars ({len(df)})")
                return result

            feat_df = self._compute_features(df)
            if len(feat_df) < 20:
                return result

            latest  = feat_df.iloc[-1]
            adx     = float(latest["adx"])
            bb_w    = float(latest["bb_width"])
            atr_n   = float(latest["atr_normalized"])

            result.adx            = adx
            result.bb_width       = bb_w
            result.atr_normalized = atr_n

            rule_regime, rule_conf = self._rule_regime(adx, bb_w, atr_n)

            if self.use_hmm:
                feat_cols = [c for c in ("log_ret", "adx", "bb_width", "atr_normalized")
                             if c in feat_df.columns]
                X_raw  = feat_df[feat_cols].values
                X_scaled = self._scaler.fit_transform(X_raw)

                if symbol_key not in self.models:
                    self._fit_hmm(X_scaled, symbol_key)

                if symbol_key in self.models:
                    hmm_probs = self._hmm_probabilities(X_scaled, symbol_key)
                    result.probabilities = hmm_probs

                    if hmm_probs:
                        top_hmm  = max(hmm_probs, key=hmm_probs.get)   # type: ignore[arg-type]
                        top_conf = hmm_probs[top_hmm]

                        if top_hmm == rule_regime:
                            # Agreement: blend
                            result.regime     = rule_regime
                            result.confidence = 0.7 * rule_conf + 0.3 * top_conf
                        else:
                            # Disagreement: rule wins, confidence penalised
                            result.regime     = rule_regime
                            result.confidence = rule_conf * 0.80
                    else:
                        result.regime     = rule_regime
                        result.confidence = rule_conf
                else:
                    result.regime     = rule_regime
                    result.confidence = rule_conf
            else:
                result.regime     = rule_regime
                result.confidence = rule_conf

            # Build default probability dict when HMM unavailable
            if not result.probabilities:
                others = (1.0 - result.confidence) / max(len(RegimeResult.REGIMES) - 1, 1)
                result.probabilities = {
                    r: (result.confidence if r == result.regime else others)
                    for r in RegimeResult.REGIMES
                }

            logger.info(
                f"Regime={result.regime} conf={result.confidence:.2f} "
                f"ADX={adx:.1f} BB_W={bb_w:.4f} ATR%={atr_n:.4f}"
            )

        except Exception as exc:
            logger.error(f"RegimeEngine error: {exc}", exc_info=True)

        return result
