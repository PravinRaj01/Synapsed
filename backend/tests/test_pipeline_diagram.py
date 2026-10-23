import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_pipeline.analysis import diagram
from ai_pipeline.analysis.graph import build_graph
from app.api.pipeline import TRACE_NODES
from app.core.auth import AuthUser, current_user
from app.main import app

BACKEND = Path(__file__).resolve().parent.parent


def test_every_node_of_the_real_graph_is_described_so_the_diagram_cannot_drift():
    real = {diagram.ALIASES.get(n, n) for n in build_graph().get_graph().nodes}
    assert real <= set(diagram.NODE_INFO), f"describe these new graph nodes in diagram.NODE_INFO: {real - set(diagram.NODE_INFO)}"
    assert all(info["label"] and info["description"] and info["kind"] in ("code", "llm", "agent", "store") for info in diagram.NODE_INFO.values())


def test_nodes_come_in_pipeline_order_with_decide_next_to_cluster_and_the_dashboard_last():
    ids = [n["id"] for n in diagram.describe()["nodes"]]
    assert ids == ["source", "select", "extract", "embed", "cluster", "decide", "name_themes", "score", "roadmap", "dashboard"]


def test_edges_match_the_graph_and_mark_the_skip_aheads_as_conditional():
    edges = {(e["source"], e["target"]): e for e in diagram.describe()["edges"]}
    for pair in (("source", "select"), ("extract", "embed"), ("cluster", "name_themes"), ("name_themes", "score"), ("score", "roadmap"), ("roadmap", "dashboard")):
        assert pair in edges and not edges[pair]["conditional"] and not edges[pair]["virtual"], pair
    for pair in (("select", "extract"), ("select", "dashboard"), ("embed", "cluster"), ("embed", "dashboard")):
        assert edges[pair]["conditional"], pair  # nothing to analyse, or nothing new to place: the run can stop early
    assert edges[("cluster", "decide")]["virtual"] and edges[("decide", "cluster")]["virtual"]


def test_every_trace_node_is_on_the_canvas():
    ids = {n["id"] for n in diagram.describe()["nodes"]}
    assert set(TRACE_NODES) <= ids and "run" not in ids


def test_mermaid_text():
    text = diagram.describe()["mermaid"]
    assert text.startswith("flowchart LR\n") and text.endswith("\n")
    assert 'decide{"Decide (agent)"}' in text and 'extract(["Extract"])' in text and 'embed[("Embed")]' in text
    assert "source --> select" in text and "select -.-> extract" in text and "decide --> cluster" in text
    assert "class extract,name_themes,roadmap llm" in text and "class decide agent" in text


def test_the_export_script_prints_and_writes_the_same_diagram(tmp_path):
    printed = subprocess.run([sys.executable, str(BACKEND / "scripts" / "export_diagram.py")], capture_output=True, text=True, check=True, cwd=tmp_path)
    assert printed.stdout.strip() == diagram.describe()["mermaid"].strip()
    target = tmp_path / "pipeline.mmd"
    subprocess.run([sys.executable, str(BACKEND / "scripts" / "export_diagram.py"), str(target)], capture_output=True, text=True, check=True, cwd=tmp_path)
    assert target.read_text(encoding="utf-8") == diagram.describe()["mermaid"]


@pytest.fixture
def client():
    app.dependency_overrides[current_user] = lambda: AuthUser(id=uuid4())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_api_serves_the_pipeline_and_a_downloadable_diagram(client):
    body = client.get("/api/v1/pipeline").json()
    assert [n["id"] for n in body["nodes"]][0] == "source" and body["trace_nodes"] == TRACE_NODES and body["mermaid"].startswith("flowchart LR")
    assert {"source", "target", "conditional", "virtual"} <= set(body["edges"][0])
    download = client.get("/api/v1/pipeline/diagram.mmd")
    assert download.status_code == 200 and download.text == body["mermaid"]
    assert download.headers["content-disposition"] == 'attachment; filename="synapsed-pipeline.mmd"'
    assert download.headers["content-type"].startswith("text/vnd.mermaid")


def test_the_pipeline_needs_a_signed_in_user():
    app.dependency_overrides.clear()
    assert TestClient(app).get("/api/v1/pipeline").status_code in (401, 403)
