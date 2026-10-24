"""Start an analysis run and watch it.

The run executes inside the request and streams its trace as Server-Sent Events, because a
serverless function stops working once the response ends. A request takes one batch of resources
(settings.analyze_batch_size); the closing summary says how many approved resources still wait, so
the client calls again until none remain. Every event is also written to agent_runs, which is what
the replay endpoints read.
"""

import json
import logging
import queue
import threading
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai_pipeline.analysis.graph import default_deps, run_analysis
from ai_pipeline.analysis.state import Deps
from app.api.common import require_campaign
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.core.rate_limit import limited
from app.core.database import user_tx

logger = logging.getLogger("synapsed.runs")

router = APIRouter(prefix="/api/v1", tags=["runs"])

KEEPALIVE_SECONDS = 10
MAX_EVENT_TEXT = 1000  # outputs in the stream are cut; the replay endpoint has the stored version
RUN_NODE = "run"


class AnalyzeRequest(BaseModel):
    campaign_id: UUID
    resource_ids: list[UUID] | None = Field(None, max_length=200)  # default: every approved, unanalysed resource


def make_deps(user_id: str, campaign_id: str, run_id: str) -> Deps:
    """The real model and embedding calls; tests replace this."""
    return default_deps(user_id, campaign_id, run_id)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _trim(value):
    if isinstance(value, str):
        return value[:MAX_EVENT_TEXT]
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    return value


class TeeTrace:
    """Writes each event to the database trace and also hands it to the open stream."""

    def __init__(self, inner, sink: "queue.Queue"):
        self.inner, self.sink = inner, sink

    def __call__(self, node: str, status: str, **details) -> None:
        self.inner(node, status, **details)
        event = {"node": node, "status": status, **{
            k: _trim(details[k]) for k in ("model_used", "input", "output", "tokens", "latency_ms") if details.get(k) is not None
        }}
        self.sink.put(("trace", event))


def _run_in_progress(user_id: UUID, campaign_id: UUID) -> bool:
    with user_tx(user_id) as conn:
        return conn.execute(
            """select 1 from agent_runs s
               where s.campaign_id = %s and s.node = %s and s.status = 'running'
                 and s.created_at > now() - make_interval(mins => %s)
                 and not exists (select 1 from agent_runs e where e.run_id = s.run_id and e.node = %s
                                 and e.status in ('done', 'error'))
               limit 1""",
            (campaign_id, RUN_NODE, get_settings().analyze_stale_minutes, RUN_NODE),
        ).fetchone() is not None


def _waiting(user_id: UUID, campaign_id: UUID) -> int:
    with user_tx(user_id) as conn:
        return conn.execute(
            "select count(*) as n from resources where campaign_id = %s and status = 'approved' and analyzed_at is null",
            (campaign_id,),
        ).fetchone()["n"]


def summarize(state: dict, remaining: int) -> dict:
    return {
        "selected": len(state.get("resource_ids", [])),
        "analysed": len(state.get("extracted_resources", [])),
        "insights": len(state.get("insight_ids", [])),
        "themed": state.get("themed_insights", 0),
        "new_themes": len(state.get("new_themes", [])),
        "how_themes_were_chosen": state.get("cluster_methods", {}),
        "roadmap_created": state.get("roadmap_created", 0),
        "roadmap_updated": state.get("roadmap_updated", 0),
        "failed": len(state.get("errors", [])),
        "errors": state.get("errors", [])[:10],
        "remaining": remaining,
    }


@router.post("/analyze")
def analyze(req: AnalyzeRequest, user: AuthUser = Depends(limited("analyze"))) -> StreamingResponse:
    """Analyse one batch of the campaign's approved resources and stream the run as it happens.

    Events: `run` (the run id), `trace` (one per graph step, model call or agent tool call),
    then `summary` (or `error`). Call again while `summary.remaining` is above zero.
    """
    require_campaign(user.id, req.campaign_id)
    if _run_in_progress(user.id, req.campaign_id):
        raise HTTPException(409, "An analysis is already running for this campaign")

    run_id = str(uuid4())
    sink: queue.Queue = queue.Queue()
    deps = make_deps(str(user.id), str(req.campaign_id), run_id)
    deps.trace = TeeTrace(deps.trace, sink)
    resource_ids = [str(r) for r in req.resource_ids] if req.resource_ids else None
    batch = get_settings().analyze_batch_size

    def work() -> None:
        deps.trace(RUN_NODE, "running", input={"resource_ids": resource_ids, "batch_size": batch})
        try:
            state = run_analysis(
                user.id, req.campaign_id, resource_ids=resource_ids, deps=deps, run_id=run_id, max_resources=batch
            )
            summary = summarize(state, _waiting(user.id, req.campaign_id))
            deps.trace(RUN_NODE, "done", output=summary)
            sink.put(("summary", summary))
        except Exception as exc:
            logger.exception("Analysis run %s failed", run_id)
            deps.trace(RUN_NODE, "error", output={"error": str(exc)[:500]})
            sink.put(("error", {"message": "The analysis failed. Resources that were not finished will be picked up by the next run."}))
        finally:
            sink.put(None)

    threading.Thread(target=work, daemon=True, name=f"analysis-{run_id[:8]}").start()

    def stream():
        yield sse("run", {"run_id": run_id, "campaign_id": str(req.campaign_id), "batch_size": batch})
        while True:
            try:
                item = sink.get(timeout=KEEPALIVE_SECONDS)
            except queue.Empty:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                return
            yield sse(*item)

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _status(last_run_event: str | None, last_event_age_minutes: float) -> str:
    """running | done | error | stale (no end event and silent for too long) | unknown (no run marker)."""
    if last_run_event is None:
        return "unknown"
    if last_run_event == "running" and last_event_age_minutes > get_settings().analyze_stale_minutes:
        return "stale"
    return last_run_event


class RunSummaryOut(BaseModel):
    run_id: UUID
    started_at: datetime
    last_event_at: datetime
    tokens: int
    events: int
    status: str  # running | done | error | stale | unknown


class RunEventOut(BaseModel):
    node: str
    status: Literal["running", "done", "error"]
    model_used: str | None
    prompt: str | None
    input: Any
    output: Any
    tokens: int | None
    latency_ms: int | None
    created_at: datetime


class RunDetailOut(BaseModel):
    run_id: UUID
    status: str
    tokens: int
    events: list[RunEventOut]


@router.get("/runs", response_model=list[RunSummaryOut])
def list_runs(campaign_id: UUID, user: AuthUser = Depends(current_user)):
    """The campaign's most recent runs, newest first."""
    require_campaign(user.id, campaign_id)
    with user_tx(user.id) as conn:
        rows = conn.execute(
            """select run_id, min(created_at) as started_at, max(created_at) as last_event_at,
                      coalesce(sum(tokens), 0) as tokens, count(*) as events,
                      (array_agg(status order by created_at desc) filter (where node = %s))[1] as run_status,
                      extract(epoch from (now() - max(created_at))) / 60 as idle_minutes
               from agent_runs where campaign_id = %s
               group by run_id order by min(created_at) desc limit 20""",
            (RUN_NODE, campaign_id),
        ).fetchall()
    return [
        {"run_id": r["run_id"], "started_at": r["started_at"], "last_event_at": r["last_event_at"],
         "tokens": r["tokens"], "events": r["events"], "status": _status(r["run_status"], float(r["idle_minutes"]))}
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: UUID, user: AuthUser = Depends(current_user)):
    """Every stored event of a run, oldest first, with the prompts: what the Laboratory canvas replays."""
    with user_tx(user.id) as conn:
        events = conn.execute(
            """select node, status, model_used, prompt, input, output, tokens, latency_ms, created_at
               from agent_runs where run_id = %s order by created_at, id""",
            (run_id,),
        ).fetchall()
        idle = conn.execute(
            "select extract(epoch from (now() - max(created_at))) / 60 as m from agent_runs where run_id = %s", (run_id,)
        ).fetchone()["m"]
    if not events:
        raise HTTPException(404, "Run not found")
    last_marker = next((e["status"] for e in reversed(events) if e["node"] == RUN_NODE), None)
    return {"run_id": run_id, "status": _status(last_marker, float(idle)), "tokens": sum(e["tokens"] or 0 for e in events),
            "events": events}
