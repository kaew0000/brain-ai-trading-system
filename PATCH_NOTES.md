# PATCH NOTES — SMC Liquidity Sweep as a Real Condition

Branch: `feature/phase-smc-liquidity-sweep`
Stacked on: `feature/phase-smc-bos-symmetry` (phase 1, commit `f602916`) — merge phase 1 first.
Base: `main` @ `1904ccb`

## Root cause

1. `SMCEngine._extract_liquidity()` kept only **unswept** pools and threw
   away the library's `Swept` index, so a sweep was never observable
   downstream.
2. `SMCAnalyst` therefore had nothing to score: the "Liquidity" factor
   verdict was hardcoded `"NEUTRAL"` and CHoCH was scored independently
   of any sweep, unlike the SMC doc (sweep -> return -> CHoCH).
3. Found while testing: `_dir_verdict()` compared the signal (`LONG`/`SHORT`)
   with engine directions (`Bullish`/`Bearish`) directly, so BOS/CHoCH/FVG/OB
   factors showed `OPPOSES` even when supporting. Display-only (the
   causal explainer builds its own verdicts), now normalised.

## Changes

- `features/smc_engine.py`: new `SMCSignals` fields `sweep`,
  `sweep_direction`, `sweep_level`, `sweep_extreme`, `sweep_bars_ago`;
  new `_extract_sweep()` (reuses the single `smc.liquidity` call;
  `_extract_liquidity` now also returns the raw frame).
  Equal lows swept -> "Bullish"; equal highs swept -> "Bearish".
  Requires sweep within `SMC_SWEEP_LOOKBACK_BARS` and, by default, a
  close back across the level ("sweep, then return").
  `sweep_extreme` = wick extreme since the sweep (anchor for phase 3 SL).
- `intelligence/market_context_builder.py`: `_smc_to_dict` adds
  `sweep`, `sweep_dir`, `sweep_level`, `sweep_extreme`, `sweep_bars_ago`.
- `agents/smc_analyst.py`: Liquidity factor verdict reflects the sweep;
  `raw` exposes it; optional scoring and CHoCH gate (flags below);
  direction-name normalisation in `_dir_verdict`.
- `config/settings.py`: 4 new settings.
- `tests/test_smc_sweep.py`: 13 tests.

## Settings (all additive)

| Setting | Default | Effect |
|---|---|---|
| `SMC_SWEEP_LOOKBACK_BARS` | 20 | max age of a counted sweep |
| `SMC_SWEEP_REQUIRES_RECLAIM` | True | sweep counts only after price returns |
| `SMC_SWEEP_SCORING_ENABLED` | **False** | same-direction sweep = +1 point (max 8) |
| `SMC_CHOCH_REQUIRES_SWEEP` | **False** | M15 CHoCH scores only after same-direction sweep |

## Impact

With defaults, scoring and signals are unchanged. New fields are
informational and the Liquidity factor verdict now shows sweep support.
Behaviour-changing logic is opt-in because this runs against live capital.

## Limitations / follow-up

- Sweep is detected on whichever TF's frame is analysed; the analyst
  reads M15's. H1-zone / M5 sequencing is phase 4.
- "Sweep preceded CHoCH" is approximated as "recent same-direction
  sweep and CHoCH both present"; bar-order between them is not checked.
- Entry/SL/TP from the swept swing: phase 3.
