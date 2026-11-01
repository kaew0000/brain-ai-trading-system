# MIGRATION — Failed orders no longer journaled OPEN (V16 §96)

## Required
None. No schema, config or API change.

## What you will notice
- A trade whose execution failed now appears in the journal as `CANCELLED` (not `OPEN`, never `LOSS`).
- On the first monitor pass after upgrading, existing phantom `OPEN` rows with quantity 0 are converted to `CANCELLED`; the consecutive-loss streak drops accordingly
  (if the bot was blocked by `consecutive_losses` caused by failed orders, it unblocks).
- A failed emergency close logs CRITICAL and the trade error reads `NAKED POSITION STILL OPEN — manual close required`: act on it immediately on the exchange.

## Rollback
`git revert` the commit. Rows already healed to `CANCELLED` stay `CANCELLED` (they were never real positions).
