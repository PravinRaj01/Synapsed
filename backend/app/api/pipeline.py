"""The analysis pipeline as data, for the Laboratory canvas and for the README / pitch diagram."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from fastapi.responses import PlainTextResponse

from ai_pipeline.analysis.diagram import describe
from app.core.auth import AuthUser, current_user

router = APIRouter(prefix="/api/v1", tags=["pipeline"])

# Trace events in agent_runs name these nodes; "run" brackets a whole run and is not a canvas node.
TRACE_NODES = ["select", "extract", "embed", "cluster", "decide", "name_themes", "score", "roadmap"]


class PipelineNodeOut(BaseModel):
    id: str
    label: str
    kind: str  # code | llm | agent | store
    description: str
    virtual: bool = False  # runs inside another node (the cluster step's agent)
    parent: str | None = None


class PipelineEdgeOut(BaseModel):
    source: str
    target: str
    conditional: bool  # may be skipped
    virtual: bool


class PipelineOut(BaseModel):
    nodes: list[PipelineNodeOut]
    edges: list[PipelineEdgeOut]
    mermaid: str
    trace_nodes: list[str]  # the node names that appear in run events


@router.get("/pipeline", response_model=PipelineOut)
def pipeline(user: AuthUser = Depends(current_user)):
    """Nodes (with what each does), edges (dotted = conditional) and the Mermaid text, read from the real graph."""
    return {**describe(), "trace_nodes": TRACE_NODES}


@router.get("/pipeline/diagram.mmd")
def pipeline_diagram(user: AuthUser = Depends(current_user)):
    """The diagram as a Mermaid file, for the README or a slide."""
    return PlainTextResponse(
        describe()["mermaid"], media_type="text/vnd.mermaid; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="synapsed-pipeline.mmd"'},
    )
