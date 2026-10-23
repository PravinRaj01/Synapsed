"""The analysis graph: select -> extract -> embed (clustering and scoring join in later steps).

LangGraph supplies the control flow, streaming and diagram export. The nodes call our own
provider layer, so no LangChain model wrappers are involved.
"""

from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ai_pipeline.analysis.nodes import embed_node, extract_node, select_node
from ai_pipeline.analysis.state import Deps, RunState
from ai_pipeline.analysis.trace import DbTrace
from ai_pipeline.embedder import embed_texts
from ai_pipeline.providers import chain_for, complete


def build_graph():
    graph = StateGraph(RunState)
    graph.add_node("select", select_node)
    graph.add_node("extract", extract_node)
    graph.add_node("embed", embed_node)
    graph.add_edge(START, "select")
    # Nothing to analyse: stop here instead of running empty steps. The targets are listed
    # so the exported diagram shows both branches.
    graph.add_conditional_edges(
        "select",
        lambda state: "extract" if state.get("resource_ids") else END,
        {"extract": "extract", END: END},
    )
    graph.add_edge("extract", "embed")
    graph.add_edge("embed", END)
    return graph.compile()


def default_deps(user_id: str, campaign_id: str, run_id: str) -> Deps:
    return Deps(
        llm=lambda messages, language: complete(messages, chain_for(language), max_tokens=1500),
        embed=embed_texts,
        trace=DbTrace(user_id, campaign_id, run_id),
    )


def initial_state(user_id: str, campaign_id: str, run_id: str, resource_ids: list[str] | None) -> RunState:
    return {"user_id": str(user_id), "campaign_id": str(campaign_id), "run_id": run_id,
            "only_resources": resource_ids, "errors": []}


def run_analysis(
    user_id, campaign_id, *, resource_ids: list[str] | None = None, deps: Deps | None = None,
    run_id: str | None = None,
) -> RunState:
    """Analyse the campaign's approved, not-yet-analysed resources and return the final state."""
    run_id = run_id or str(uuid4())
    deps = deps or default_deps(str(user_id), str(campaign_id), run_id)
    state = initial_state(user_id, campaign_id, run_id, resource_ids)
    return build_graph().invoke(state, config={"configurable": {"deps": deps}})
