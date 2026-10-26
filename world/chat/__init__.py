"""world/chat — V16 §83. World chat + meetings (rule-based, no LLM).

Boundary: this package may read World state via `world.workspace.api`
and write ONLY its own chat store. It must never import execution/,
risk/, portfolio/, exchange/, or any trading module (enforced by
tests/test_world_chat.py::test_boundary_no_trading_imports).
"""
