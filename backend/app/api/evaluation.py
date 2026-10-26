from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool

from app.context import AppContext
from app.errors import NotFoundError
from app.evaluation.runner import run_evaluation
from app.security import get_ctx, get_owner, rate_limit

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


def _report_path(ctx: AppContext):
    return ctx.settings.data_dir / "eval" / "latest.json"


@router.get("/report")
def latest_report(ctx: AppContext = Depends(get_ctx), _: str = Depends(get_owner)) -> dict[str, Any]:
    path = _report_path(ctx)
    if not path.exists():
        raise NotFoundError("No evaluation report yet. Run the evaluation first.", code="no_report")
    return json.loads(path.read_text())


@router.post("/run", dependencies=[Depends(rate_limit)])
async def run(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Runs the deterministic (offline-generator) evaluation against the bundled sample PDF in an isolated workspace."""

    def work() -> dict[str, Any]:
        with ctx.lock:  # serialise with other evaluation runs; uses the already-loaded embedding model
            report = run_evaluation(embedder=ctx.embedder, generator="offline", base_settings=ctx.settings)
        path = _report_path(ctx)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2))
        return report

    return await run_in_threadpool(work)
