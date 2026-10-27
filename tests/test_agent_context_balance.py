"""V16 §87: agent-layer context must carry the real balance, not a 0.0 sentinel
(which RiskEngine's balance gate reports as 'Insufficient balance' on a funded account)."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

import main

pytestmark = pytest.mark.unit


def test_returns_real_balance():
    dp = MagicMock()
    dp.get_account_balance.return_value = 4614.02
    assert main._agent_context_balance(dp) == 4614.02


def test_falls_back_to_zero_on_error():
    dp = MagicMock()
    dp.get_account_balance.side_effect = RuntimeError("boom")
    assert main._agent_context_balance(dp) == 0.0


def test_no_zero_sentinel_left_in_agent_contexts():
    src = inspect.getsource(main)
    assert 'pos_info["balance"] = 0.0' not in src
    assert 'pos_info_live["balance"] = 0.0' not in src
