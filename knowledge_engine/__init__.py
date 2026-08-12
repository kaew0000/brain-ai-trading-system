"""
knowledge_engine — V16 Phase 4C Step 8: Persistent Trading Knowledge Layer.

Architectural reference: Andrej Karpathy's "LLM Wiki" pattern
(immutable raw sources -> a maintained, cross-linked Markdown wiki ->
an append-only log), adapted to Brain Bot's existing Track A data
(journal_v2.py, Phase 4C Step 7C's signal-ID attribution bridge)
rather than copied literally.

RAW SOURCES (raw/)  ->  KNOWLEDGE EXTRACTION (this package)  ->
PERSISTENT WIKI (knowledge/)  ->  CROSS-REFERENCED KNOWLEDGE  ->
future AI/agent reasoning (out of scope for this phase — this phase
builds the layer, not a consumer of it).

== SAFETY BOUNDARY (informational / analytical ONLY) ==

This package MUST NEVER place trades, modify orders, modify SL/TP,
change risk limits, override RiskEngine, override execution policy,
change execution mode, change paper/live/testnet configuration, bypass
Commander authorization, modify START/STOP lifecycle state, or modify
a trading decision directly. It has exactly one kind of side effect:
writing Markdown files under raw/ and knowledge/.

Enforced structurally, not just by convention: every module in this
package imports ONLY from the Python standard library and
journal.journal_v2 (read-only query methods — get_trades(),
get_trade_attribution(), get_agent_performance(); this package never
calls a save_*() method). Nothing here imports from execution/, risk/,
decision/, agents/, portfolio/, commander/, or any Binance/exchange
client. tests/test_knowledge_safety.py asserts this via static AST
inspection of every file in this package, not a grep.
"""
