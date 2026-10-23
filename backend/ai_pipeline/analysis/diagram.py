"""The analysis pipeline as data: nodes, edges and a Mermaid diagram, read from the compiled graph.

Reading the real graph means the diagram cannot drift from the code. The `decide` step is not a graph node
(it runs inside `cluster`), but it has its own trace events and its own place on the Laboratory canvas, so
it is added as a virtual node with a loop to and from `cluster`.
"""

from functools import lru_cache

from ai_pipeline.analysis.graph import build_graph

# kind: how the step works. code = plain code, llm = one model call, agent = a tool-calling loop, store = database
NODE_INFO: dict[str, dict] = {
    "source": {"label": "Data source", "kind": "code", "description": "Approved interviews, tickets, surveys and scraped pages."},
    "select": {"label": "Select", "kind": "store", "description": "Picks approved resources that have not been analysed yet, one batch at a time."},
    "extract": {"label": "Extract", "kind": "llm", "description": "A model finds pain points and feature requests; every quote is checked against the source text."},
    "embed": {"label": "Embed", "kind": "store", "description": "Embeds each pain point and stores it with its citation."},
    "cluster": {"label": "Cluster", "kind": "code", "description": "Places each pain point in a theme: by similarity in code, or by the agent when it is a close call."},
    "decide": {"label": "Decide (agent)", "kind": "agent", "virtual": True, "parent": "cluster",
               "description": "A tool-calling agent for close calls: search themes, append to one, or create a new one (at most 4 steps)."},
    "name_themes": {"label": "Name themes", "kind": "llm", "description": "One model call names and describes the themes created in this run."},
    "score": {"label": "Score", "kind": "code", "description": "Frequency and Business Impact for every theme (customer weight x severity)."},
    "roadmap": {"label": "Roadmap", "kind": "llm", "description": "One ICE-scored roadmap item per theme; a model estimates ease; Now / Next / Later by tercile."},
    "dashboard": {"label": "Dashboard", "kind": "code", "description": "Themes, scores and roadmap items shown in the app."},
}
START, END = "__start__", "__end__"
ALIASES = {START: "source", END: "dashboard"}


@lru_cache
def describe() -> dict:
    """{"nodes": [...], "edges": [...]} in pipeline order, plus the Mermaid text."""
    graph = build_graph().get_graph()
    names = [ALIASES.get(n, n) for n in graph.nodes]
    edges = [{"source": ALIASES.get(e.source, e.source), "target": ALIASES.get(e.target, e.target),
              "conditional": bool(e.conditional), "virtual": False} for e in graph.edges]

    # decide lives inside cluster: a loop out and back
    edges += [{"source": "cluster", "target": "decide", "conditional": True, "virtual": True},
              {"source": "decide", "target": "cluster", "conditional": False, "virtual": True}]
    order, queue = [], ["source"]
    while queue:  # pipeline order, following the real edges
        node = queue.pop(0)
        if node in order:
            continue
        order.append(node)
        queue += [e["target"] for e in edges if e["source"] == node and not e["virtual"]]
        if node == "cluster":
            order.append("decide")
    if "dashboard" in order:  # the end of the pipeline is always last, however early a skip-ahead edge reaches it
        order.remove("dashboard")
        order.append("dashboard")
    unknown = [n for n in names if n not in NODE_INFO]
    nodes = [{"id": n, **NODE_INFO.get(n, {"label": n, "kind": "code", "description": ""})} for n in order]
    nodes += [{"id": n, **NODE_INFO.get(n, {"label": n, "kind": "code", "description": ""})} for n in unknown if n not in order]
    return {"nodes": nodes, "edges": edges, "mermaid": to_mermaid(nodes, edges)}


def to_mermaid(nodes: list[dict], edges: list[dict]) -> str:
    """A left-to-right flowchart. Dotted arrows are conditional (they may be skipped); agent and model steps are styled."""
    shape = {"llm": '(["{}"])', "agent": '{{"{}"}}', "store": '[("{}")]', "code": '["{}"]'}
    lines = ["flowchart LR"]
    for n in nodes:
        lines.append(f"    {n['id']}{shape.get(n['kind'], shape['code']).format(n['label'])}")
    for e in edges:
        lines.append(f"    {e['source']} {'-.->' if e['conditional'] else '-->'} {e['target']}")
    lines += [
        "    classDef llm fill:#ecfdf5,stroke:#10b981",
        "    classDef agent fill:#fef3c7,stroke:#f59e0b",
        "    class " + ",".join(n["id"] for n in nodes if n["kind"] == "llm") + " llm",
        "    class " + ",".join(n["id"] for n in nodes if n["kind"] == "agent") + " agent",
    ]
    return "\n".join(lines) + "\n"
