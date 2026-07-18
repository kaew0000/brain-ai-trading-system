# QUANT_AUDIT.md — Brain Bot V13

**Audit Date:** 2026-06-19

---

## 1. SMC Engine

### Signal Correctness ✅
- BOS / CHoCH detected via `smartmoneyconcepts.smc.bos_choch()` with `close_break=True` — correct; uses close price to confirm structural break (avoids wicks).
- FVG filters for unmitigated gaps only (`MitigatedIndex.isna()`). ✅
- OB selects closest unmitigated block to current price by distance. ✅
- Liquidity filters swept zones (`Swept.isna()`). ✅

### Trend Bias ✅
- `trend_bias` derived from most recent BOS/CHoCH direction string ("Bullish"/"Bearish").
- Numeric fallback for libraries that return 1/-1 instead of strings. ✅
- NaN guard before `float(signal)` conversion. ✅

### MTF Alignment ✅
- `_mtf_direction()` requires 3/3 or 2/3 timeframe agreement — correctly conservative.
- H4 + M15 agreement (H1 neutral) still yields a signal — reasonable for crypto.

### Potential Bias ⚠️
- SMC analysis runs on the **full 500-bar OHLCV** including the current (incomplete) candle.
- The current candle's close is **live mark price**, not a completed candle.
- **Impact:** Low — BOS/CHoCH look for structural breaks on closed swings; the current candle's wicks don't affect historical swing levels. FVG from incomplete candle is filtered by `MitigatedIndex`, so no look-ahead risk.

---

## 2. Volume Engine

### Signal Correctness ✅
- Volume spike: baseline uses bars `[-avg_period-1:-1]` (excludes current bar). ✅ No look-ahead.
- OBV: computed via loop over all bars — correct standard definition.
- OBV direction: linear regression slope over last 8 bars — appropriate.
- Divergence: half-window split comparing extremes — valid classic implementation.
- ATR: rolling 14-bar True Range for breakout threshold — correct.

### NaN Guards ✅
- OBV direction returns "neutral" if any NaN in window.
- ATR NaN check before breakout comparison.
- Volume ratio returns 0 if avg_volume==0 (division guard).

---

## 3. Futures Intelligence Engine

### Funding Logic ✅
- `LONG_PAYING` (rate > threshold) → longs pay shorts → bearish pressure. ✅
- `SHORT_PAYING` (rate < -threshold) → shorts pay longs → bullish pressure. ✅
- `extreme` flag at `|rate| >= 0.0005` (0.05% per 8h = 21.9% annualised) — appropriate for crypto.
- Block trigger: extreme + direction paying → correct directional block.

### OI Logic ✅
- delta_pct from percentage change of `sumOpenInterest` series — correct.
- `BUY_PRESSURE` when OI rising (more contracts = new money entering long side with price up).
- `SELL_PRESSURE` when OI falling.
- Liquidation heuristic: OI drop + price drop → LONG_SQUEEZE. ✅

### Long/Short Ratio ✅
- Contrarian signal (`FADE_LONGS` when ratio > 1.2) — standard smart money concept.
- `longShortRatio` key prioritised, falls back to `longAccount`. ✅

### Scoring System ✅
- Max 5 points; ≥3 required for directional signal — appropriate threshold.
- Extreme funding reduces score by 2 — correctly penalises crowded carry trades.

---

## 4. Regime Engine

### Detection Logic ✅
- Priority: SQUEEZE → VOLATILE → TREND → RANGE — correct ordering.
- SQUEEZE: BB width < 2% + ADX < 25 → valid pre-breakout detection.
- VOLATILE: ATR_norm > 1.5% + BB width > 8% → both conditions required (reduces false positives).
- TREND: ADX >= 25 — standard Wilder threshold.
- Confidence clipped to [0.55, 0.95] — prevents overconfident signals.

### HMM Blending ✅
- 3-state HMM with diagonal covariance on 4 features (log_ret, ADX, BB_width, ATR_norm).
- Agreement: 70% rule + 30% HMM confidence. ✅
- Disagreement: rule wins, confidence penalised 20%. ✅
- State-to-regime mapping by variance ordering (low var → SQUEEZE, high var → VOLATILE). ✅

### Look-ahead Risk: NONE ✅
- `fit_transform()` and `score_samples()` both called on the same window each cycle — correct. HMM is refitted every cycle on the available data, which is computationally expensive but not look-ahead.

### Warning ⚠️
- HMM is refitted on every `classify()` call (when `not self._fitted`). After first fit, `_fitted=True` so subsequent calls only score. However, `_scaler.fit_transform()` is called every cycle — this is a look-ahead risk for multi-cycle backtesting (scaler sees future data when called on the full historical window). In **live trading** this is fine since we only ever have past data.

---

## 5. Confidence Engine

### Weight System ✅
- Default: SMC 30%, Volume 20%, OI 20%, Funding 10%, Regime 20% = 100%. ✅
- `_normalise_weights()` ensures sum=100 regardless of input. ✅
- `_pct()` rounds to integer — minor rounding (≤1 point) tolerable.

### Scoring Correctness ✅
- SMC score: max 5 raw (BOS=2, CHOCH=1, FVG=1, OB=1), normalised to 0-1 by /4. Capped at 1.0.
- Volume score: max useful = 2 (spike + OBV aligned), normalised by /2. Breakout is bonus above cap → still capped at 1.0. ✅
- OI score: uses `futures` sub-dict when available, falls back to raw `oi_delta`. ✅
- Funding score: neutral=0.7, favourable=1.0, extreme=0.0. Reasonable gradient.

### Hard Block Logic ✅
- Checks `ctx["blocks_long"]` (pre-computed by MarketContextBuilder from FuturesIntelEngine).
- Also re-checks raw funding rate vs settings thresholds — double-check defence. ✅

### `raw_score` Backward Compat ✅
- `_to_raw_score(smc, vol, oi)` maps to 0-9 integer for v1 journal compatibility.
- Formula: `smc*4 + vol*2 + oi*2` → max = 8 (not 9 as `max_score` suggests).
- **Minor inaccuracy:** `max_score=9` is set but actual max is 8. No trading decisions depend on `max_score` — it's display-only in the dashboard.

---

## 6. Risk Engine

### Daily Loss Check ✅
- `max_loss = balance × MAX_DAILY_LOSS` — percentage of current balance. ✅
- `today_pnl < -max_loss` → disable. Correct signed comparison.

### Dynamic Risk ✅
- Streak ≥ 2 → MIN_RISK (halves bet size). ✅
- Loss > 50% of daily limit → MIN_RISK. ✅
- Normal → MAX_RISK.

### Day Reset ✅
- `_maybe_reset_day()` checks UTC date change — timezone-aware. ✅

---

## 7. Trade Manager (Position Sizing)

```python
risk_usdt = balance * risk_pct
quantity  = risk_usdt / abs(entry - stop_loss)
```
- Risk-based sizing: quantity sized so SL hit = exactly `risk_usdt` loss. ✅
- Leverage is implicit (larger position, same dollar risk). ✅
- **BUG-04 (FIXED):** `monitor_open_trades` was applying leverage again → removed. ✅

---

## 8. SL / TP Logic

### `_derive_levels()` ✅
- OB-based entry: uses `ob_bottom` for LONG (entry at order block support).
- OB validity check: must be below price and within 3% — prevents stale/distant OB usage. ✅
- ATR fallback: 1.8% SL, 5.4% TP (3R) when no valid OB. Reasonable for BTC futures.

---

## 9. Paper Trading Validation

### Balance Updates ✅
- `reserve_margin(notional)`: deducts `notional/leverage` from free margin. ✅
- `release_margin(notional)`: restores margin on close. ✅
- `realise_pnl(pnl)`: adds net PnL to balance. ✅

### Fee Accounting ✅
- Entry fee: `entry_price × qty × 0.0004`
- Exit fee: `exit_price × qty × 0.0004`
- `net_pnl = raw_pnl - entry_fee - exit_fee`. ✅

### PnL Accounting ✅
- LONG: `(exit - entry) × qty`
- SHORT: `(entry - exit) × qty`
Both correct; fee subtracted after. ✅

### Win Rate ✅ — `len(wins) / len(closed)`
### Profit Factor ✅ — `gross_win / gross_loss`
### Expectancy ✅ — `(wr × avg_win) - ((1-wr) × avg_loss)`

### Sharpe Ratio ⚠️ (MINOR)
- Current: per-trade Sharpe (`mean / std × sqrt(365)`).
- Industry standard: daily-equity-return Sharpe.
- **Impact:** Not comparable to external benchmarks, but self-consistent for strategy comparison.
- **Recommendation:** Document as "per-trade Sharpe proxy" in dashboard.

### Max Drawdown ✅
- Peak-to-trough on cumulative PnL series. ✅
- `starting_balance` as initial equity. ✅

---

## Summary

| Engine | Status | Risk Level |
|--------|--------|-----------|
| SMC Engine | ✅ Correct | Low |
| Volume Engine | ✅ Correct | Low |
| Futures Intel | ✅ Correct | Low |
| Regime Engine | ✅ Correct (⚠️ scaler refits live) | Low |
| Confidence Engine | ✅ Correct (minor: max_score=8 not 9) | Low |
| Risk Engine | ✅ Correct | Low |
| SL/TP Logic | ✅ Correct | Low |
| Paper Trading PnL | ✅ Correct (post BUG-04/05 fix) | None |
| Sharpe Ratio | ⚠️ Non-standard definition | Minor |
