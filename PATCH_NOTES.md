# PATCH NOTES — SMC Top-Down Confirmation, M5 Timeframe, Conflict Block

Branch: `feature/phase-smc-m5-gating`
Stacked on: phase 3 (`d1be45c`) -> phase 2 (`80d2d7f`) -> phase 1 (`f602916`). Merge in order.
Base: `main` @ `1904ccb`

## Root cause

The live path (`main.py` -> `MarketContextBuilder` -> `ConfidenceEngine`) only
ever saw H4/H1/M15, picked a direction by trend-bias voting, and scored all
SMC factors independently. There was no M5 data, no ordering
(zone -> sweep -> CHoCH -> entry trigger), and `mtf_aligned=False` never
stopped a trade, unlike the SMC doc (confirm top-down, skip on conflict).

## Changes

- `features/smc_topdown.py` (new, pure logic): `evaluate_topdown()` state machine
  BIAS (H4 matches, H1 not opposing) -> ZONE (price in H1 OB/FVG) ->
  CONFIRM (M15 sweep AND CHoCH, same direction) -> ENTRY (M5 CHoCH + FVG/OB;
  skipped with `m5_used=False` when no M5). `CONFLICT` when any analysed TF bias,
  or an M5 CHoCH, opposes the direction.
- `data/binance_provider.py`: `_ohlcv_timeframes()` helper (h4/h1/m15 unchanged)
  and best-effort `_fetch_optional_m5()` called from both
  `get_all_market_data()` and `get_market_data_for()`. M5 failure is logged
  and non-fatal (h4/h1/m15 failures still raise as before).
- `intelligence/market_context_builder.py`: adds `smc_m5` (`{}` when absent) and
  `topdown` to the context. Existing keys untouched.
- `decision/confidence_engine.py::_check_blocks`: two opt-in hard blocks
  (`TF_CONFLICT ...`, `TOPDOWN_<state>`) using the existing block mechanism.
- `config/settings.py`: `M5_TIMEFRAME`, `SMC_M5_ENABLED`, `SMC_TOPDOWN_GATE_ENABLED`,
  `SMC_TF_CONFLICT_BLOCKS_TRADE`, `SMC_ZONE_TOLERANCE_PCT`.
- `tests/test_smc_topdown.py`: 24 tests (state machine, blocks, M5 fetch,
  real `MarketContextBuilder.build()` with and without M5).

## Impact

All new flags default off, so existing behaviour is unchanged; the context
just carries two extra informational keys. `SMCEngine.analyze_mtf` already
handles any timeframe keys, and no code iterates all timeframes.
With `SMC_M5_ENABLED` there is one extra klines call per symbol per cycle.

## Limitations / follow-up

- M5 is used for the entry *trigger* only; entry price and SL/TP still come from
  M15 OB / sweep (phase 3). Anchoring entry to the M5 FVG/OB is not done.
- The gate evaluates the single M15-bias direction; it does not search the
  opposite direction.
- `BrainDecisionEngine` (legacy v1) and `smc_oi_regime_multi` strategy do not
  consult `topdown`; the gate applies on the ConfidenceEngine path
  (main loop, portfolio signal provider).
- Thresholds (zone tolerance, "conflict = any opposing TF") are first-cut; validate on paper/testnet.
