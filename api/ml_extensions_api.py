"""
api/ml_extensions_api.py — V16 ML Extensions Integration Layer (observe-only)

REST read layer over whatever main.py's SystemIntegrator.wire_all()
produced, stored into api.app's generic get_state("ml_extensions", ...)
slot — the same convention api/app.py's _start_api_server() already
uses for agent_layer / training_lane_runner (set_state, a thread-safe
single-key store). This module is an APIRouter included into the
existing api/app.py singleton, the same pattern api/execution_api.py
and api/portfolio_api.py already establish.

Every endpoint returns 200 with an honest disabled/unavailable payload
when ML_EXTENSIONS_ENABLED=false or wiring failed — "unavailable is a
normal runtime state, not a server error", matching
api/execution_api.py's own documented convention. No POST endpoints:
this layer is read-only/observe-only this phase — see
ml/extensions_integration/ml_extensions_agent.py's module docstring for
why.

Routes live under /api/ml_extensions/*, so api/app.py's existing
prefix-generic _auth_middleware already covers them at the default
VIEWER role — no auth changes needed.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/ml_extensions", tags=["ml_extensions"])


def _ok(data: Any) -> JSONResponse:
    # Mirrors api/execution_api.py's own _ok() helper, reimplemented
    # locally for the same reason that module's is: avoid a circular
    # import back through api.app.
    return JSONResponse(content={"ok": True, "data": data})


def _components() -> dict:
    import api.app as _api_module
    return _api_module.get_state("ml_extensions", None) or {"enabled": False}


@router.get("/status")
async def ml_extensions_status():
    """Whether the integration layer is enabled and wired this run."""
    c = _components()
    return _ok({
        "enabled": bool(c.get("enabled", False)),
        "agent_registered": c.get("agent") is not None,
        "error": c.get("error"),
    })


@router.get("/rl/status")
async def rl_status():
    """RL (Stable-Baselines3) status, if a model has been trained or
    loaded into this process's ExtensionsOrchestrator."""
    c = _components()
    orch = c.get("orchestrator")
    if orch is None:
        return _ok({"ready": False, "reason": "not wired"})
    return _ok({
        "ready": orch.rl_adapter is not None,
        "algorithm": getattr(orch.rl_adapter, "algorithm_name", None) if orch.rl_adapter else None,
    })


@router.get("/online/metrics")
async def online_metrics():
    """River online-learner metrics, if online learning has been set up."""
    c = _components()
    orch = c.get("orchestrator")
    if orch is None or orch.online_learner is None:
        return _ok({"ready": False, "reason": "not wired"})
    try:
        if hasattr(orch.online_learner, "get_all_metrics"):
            metrics = orch.online_learner.get_all_metrics()  # MultiSymbolOnlineLearner
        else:
            metrics = orch.online_learner.get_metrics()  # OnlineLearner
    except Exception as exc:
        return _ok({"ready": True, "error": str(exc)})
    return _ok({"ready": True, "metrics": metrics})


@router.get("/hpo/status")
async def hpo_status():
    """Optuna HPO best params/score, if a study has been run this process."""
    c = _components()
    orch = c.get("orchestrator")
    hpo = orch.hpo_manager if orch is not None else None
    if hpo is None or hpo.study is None:
        return _ok({"ready": False, "reason": "not wired"})
    return _ok({
        "ready": True,
        "best_params": hpo.best_params,
        "best_score": hpo.study.best_value,
        "n_trials": len(hpo.study.trials),
    })


@router.get("/agent/last-report")
async def agent_last_report():
    """Most recent AgentReport from MLExtensionsAgent, if any. Purely
    observational — it does not reflect anything that affected a real
    trading decision (see ml_extensions_agent.py's module docstring)."""
    c = _components()
    agent = c.get("agent")
    last = agent.last_report if agent is not None else None
    if last is None:
        return _ok({"ready": False, "reason": "no report yet"})
    return _ok({"ready": True, "report": last.to_dict()})
