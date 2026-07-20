"""
api/execution_api.py — V16 Phase 2E: Execution Wiring & Live Orchestrator

REST read layer over execution/execution_state.py's process-wide
ExecutionState singleton and execution/execution_metrics.py's pure
computation over it. Additive: an APIRouter included into the existing
api/app.py singleton, same pattern api/portfolio_api.py already
established in Phase 2C — not a second FastAPI app, no changes to any
existing /api/portfolio/* route.

No exchange calls, no ExecutionOrchestrator.execute() calls — this
module only ever reads whatever the live ExecutionOrchestrator instance
(wherever a future scheduler phase constructs and runs one) has already
recorded into the shared get_execution_state() singleton. If nothing
has ever been recorded (no orchestrator running yet, or it hasn't
executed anything), every endpoint returns 200 with an honest
all-zeros/empty payload — same "unavailable is a normal, expected
runtime state, not a server error" convention api/portfolio_api.py's
own module docstring already documents.

Auth: routes are under /api/execution/*, so the existing
_auth_middleware in api/app.py already covers them at the default
VIEWER role — nothing in api/auth.py needed changing (identical
reasoning to api/portfolio_api.py's own module docstring).
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from execution.execution_metrics import compute_metrics
from execution.execution_state import ExecutionStatus, get_execution_state

router = APIRouter(prefix="/api/execution", tags=["execution"])


def _ok(data) -> JSONResponse:
    # Mirrors api/portfolio_api.py's own _ok() exactly, reimplemented
    # locally for the same reason that module's does: avoid a circular
    # import back through api.app.
    return JSONResponse(content={"ok": True, "data": data})


@router.get("/metrics")
async def execution_metrics():
    """Process-wide, cumulative execution metrics — see
    execution/execution_metrics.py's module docstring for how this
    differs from a single batch's ExecutionSummary (which isn't exposed
    over REST; it's returned directly from
    ExecutionOrchestrator.execute() to whatever in-process caller
    invoked it)."""
    snapshot = compute_metrics(get_execution_state())
    return _ok(snapshot.to_dict())


@router.get("/status")
async def execution_status():
    """Current in-flight/finished counts — the same summary
    ExecutionState.to_dict() already exposes, surfaced over REST for the
    dashboard."""
    return _ok(get_execution_state().to_dict())


@router.get("/executions")
async def execution_list(
    status: str = Query(default=None, description="Filter by PENDING/RUNNING/COMPLETED/FAILED/CANCELLED"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Recent execution records, newest-first, optionally filtered by
    status. `limit` caps the response size — ExecutionState itself is
    already ring-buffer-bounded (see its own module docstring), this is
    an additional page-size cap on top of that."""
    state = get_execution_state()
    if status is not None:
        try:
            status_enum = ExecutionStatus(status.upper())
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={"ok": False, "error": f"invalid status '{status}'; expected one of "
                                                 f"{[s.value for s in ExecutionStatus]}"},
            )
        records = state.by_status(status_enum)
    else:
        records = state.all_records()

    records = sorted(records, key=lambda r: r.created_at, reverse=True)[:limit]
    return _ok([r.to_dict() for r in records])


@router.get("/executions/{execution_id}")
async def execution_detail(execution_id: str):
    """A single execution record by id, or an honest 200/null (not a
    404) when it isn't found — matches api/portfolio_api.py's own
    "empty/null payload, not a server error" convention for a state that
    simply hasn't happened yet or has aged out of the ring buffer."""
    record = get_execution_state().get(execution_id)
    return _ok(record.to_dict() if record else None)
