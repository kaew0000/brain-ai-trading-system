# PATCH NOTES — SMC Analyst H4 BOS Symmetry

Branch: `feature/phase-smc-bos-symmetry`
Base: `main` @ `1904ccb` (merge of PR #107)

## Root cause

`agents/smc_analyst.py::SMCAnalyst.analyse()` scored the H4 BOS as a bare
boolean (`h4_bos`) and added it to `bullish_pts` only. Consequences:

- A **bearish** H4 BOS added a point to the **bullish** side (wrong direction).
- `bearish_pts` had no H4 BOS term at all, so for mirrored inputs the
  bearish side maxed at 6 points while the bullish side maxed at 7.
- Confidence uses `pts / 7`, so SHORT confidence was structurally capped
  below LONG for otherwise identical setups.

## Fix

H4 BOS is now direction-aware, using `smc_h4["bos_dir"]` (already produced
by `_smc_to_dict`; no producer change). It adds one point to
`bullish_pts` when Bullish/LONG and one point to `bearish_pts` when
Bearish/SHORT. Same direction-matching convention as the M15 terms.

## Files changed

- `agents/smc_analyst.py` (+3 / -1)
- `tests/test_agents.py` (+`TestSMCAnalystH4BosSymmetry`, 3 tests)
- `PATCH_NOTES.md`, `MIGRATION.md`

## Impact

- LONG with bullish H4 BOS: unchanged.
- SHORT with bearish H4 BOS: +1 point (confidence up by 1/7 where it applies).
- Bearish H4 BOS no longer inflates LONG scoring.
- H4 BOS with empty/unknown direction now scores neither side
  (previously counted bullish).
- No public API, config, schema or EventBus change.

## Known follow-up (not in this phase)

From the SMC code-vs-document comparison:
1. Make liquidity sweep a real condition (verdict is hardcoded `NEUTRAL`).
2. Derive entry/SL/TP from the swept swing instead of fixed percentages
   (`main.py::_derive_levels`).
3. Add M5 fetch/analysis and sequential top-down gating
   (H1 zone -> M15 sweep+CHoCH -> M5 entry), including a hard skip when
   timeframes conflict. Largest change; touches config and APIs.
