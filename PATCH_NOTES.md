# PATCH NOTES — Entry/SL/TP Anchored to the Swept Swing

Branch: `feature/phase-smc-sweep-levels`
Stacked on: `feature/phase-smc-liquidity-sweep` (phase 2, `80d2d7f`) -> phase 1 (`f602916`). Merge in order.
Base: `main` @ `1904ccb`

## Root cause

`main.py::_derive_levels()` always used fixed percentages (SL 1.8%, TP 5.4%,
OB max distance 3%) hardcoded in the function. SL/TP never reflected where
liquidity was actually taken, contrary to the SMC doc (SL beyond the swept
swing, TP at opposite liquidity). The values were also hardcoded, against
the project's config rule.

## Changes

- `main.py`: new `_sweep_levels()`; `_derive_levels()` keeps its signature
  and entry logic, reads the three formerly hardcoded values from settings,
  and overrides SL/TP only when `_sweep_levels()` returns a result.
  - LONG: SL = sweep low extreme x (1 - buffer); TP = `liquidity_high` if RR >= min,
    else entry + fallback_RR x risk.
  - SHORT: mirrored with `sweep_extreme` (high) and `liquidity_low`.
  - Falls back to fixed percentages when: flag off, no sweep, opposite-direction
    sweep, missing/invalid extreme, SL on the wrong side of entry, or risk > max.
- `config/settings.py`: `LEVEL_SL_PCT`, `LEVEL_TP_PCT`, `LEVEL_OB_MAX_DIST_PCT`
  (same defaults as the old constants) and `SMC_SWEEP_LEVELS_ENABLED`
  (default **False**), `SMC_SWEEP_SL_BUFFER_PCT` 0.001, `SMC_SWEEP_MAX_SL_PCT` 0.05,
  `SMC_SWEEP_MIN_RR` 1.5, `SMC_SWEEP_FALLBACK_RR` 3.0.
- `tests/test_derive_levels_sweep.py`: 11 tests.

## Impact

Default behaviour is byte-for-byte the same output. Both call sites in
`main.py` and `execution/portfolio_signal_provider.py` (imports
`_derive_levels`) are unaffected. When enabled, stops are tighter or wider
than 1.8% depending on the sweep; position sizing derives from SL distance
elsewhere, so size changes accordingly (capped by `SMC_SWEEP_MAX_SL_PCT`).

## Limitations / follow-up

- Uses M15 sweep data only. Entry price still comes from the M15 OB or market
  price, not an M5 FVG/OB (phase 4).
- Spread/slippage is not modelled in the stop buffer.
