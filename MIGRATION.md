# MIGRATION — V16 Phase 4C §51: HFT Flow Enabling-for-Live Switch (HFT-6b)

## Do you need to do anything?

**Only if you want the feature active.** This patch is purely additive
and off by default — `HFT_FLOW_LIVE_ENABLED` defaults to `False`, so
`resolve_confidence_weights()` returns the exact same `DEFAULT_WEIGHTS`
object as before. An existing `.env` with none of the new keys sees
byte-identical behavior after updating.

To activate on this `EXECUTION_MODE=paper` deployment, add to `.env`
and restart:
```
HFT_WS_ENABLED=true
HFT_FLOW_LIVE_ENABLED=true
HFT_FLOW_CONTRADICTION_ENABLED=true
```
`HFT_FLOW_LIVE_WEIGHT` already defaults to `5.0` — add it only if a
different value is wanted.

## What to expect after activating

- Startup log will show `[5/9] HFT flow LIVE weight active: hft_flow=5.0
  (contradiction_enabled=True, ws_enabled=True)`.
- The Binance WS depth/trade client (`data/binance_ws_client.py`) starts
  connecting on boot — one additional persistent WebSocket connection
  per traded symbol, same connection pattern already used for the
  existing dashboard broadcast task (no new thread/process).
- `/api/signals`' `raw_features`/breakdown surface will start showing a
  non-zero `"hft_flow"` entry in `ConfidenceResult.breakdown` whenever
  real WS depth data is present with `feature_confidence > 0`. Before
  that data is present (e.g. briefly after a fresh boot/reconnect), the
  key is simply absent — same fail-safe behavior as before this patch.
- Confidence weights auto-rescale to sum to 100
  (`_normalise_weights()` divides proportionally) — smc/volume/oi/funding/regime
  each shrink by roughly 4.5% relative to their current share (a 105→100
  rescale), not zero out. `hft_flow` itself lands at roughly 4.8% of
  total confidence, matching the "~5%" design intent documented on
  `HFT_FLOW_LIVE_WEIGHT`.
- The contradiction mechanism can now reduce confidence, or — only on a
  strongly extreme opposing reading — force a hard `BLOCKED` action.
  Watch the dashboard's Signal Panel block-reason field for this new
  possible reason alongside the existing `FUTURES_BLOCK_LONG/SHORT` and
  `FUNDING_BLOCK_LONG/SHORT` ones.
- If `HFT_WS_ENABLED=true` but the WS client can't connect or sync
  (network issue, Binance-side outage), `feature_confidence` stays `0`
  and `hft_flow` silently contributes nothing — the pre-existing
  fail-safe from HFT-1 through HFT-4, unchanged by this patch.

## Rollback

Set `HFT_FLOW_LIVE_ENABLED=false` (and/or `HFT_FLOW_CONTRADICTION_ENABLED=false`)
and restart — reverts to byte-identical pre-patch decision behavior. No
code rollback or database change needed either way; nothing in this
patch touches the database.
