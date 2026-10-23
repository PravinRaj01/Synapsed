"""The analyze / runs endpoints against a real Neon database, with the model and embeddings faked.

Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. Test workspaces are deleted afterwards.
"""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_pipeline.analysis.state import Deps
from ai_pipeline.analysis.trace import DbTrace
from app.api import runs as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import Settings, get_settings
from app.main import app
from tests.test_analysis_graph import INTERVIEW, MALAY, UNIT, FakeLlm, no_agent, q, world  # noqa: F401

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


@pytest.fixture
def client(world, monkeypatch):  # noqa: F811
    app.dependency_overrides[current_user] = lambda: AuthUser(id=world.user)

    def fake_deps(user_id, campaign_id, run_id):
        return Deps(llm=FakeLlm(), embed=lambda texts: [UNIT for _ in texts],
                    trace=DbTrace(user_id, campaign_id, run_id), llm_tools=no_agent)

    monkeypatch.setattr(api, "make_deps", fake_deps)
    yield TestClient(app)  # no `with`: the fixture already opened the connection pool
    app.dependency_overrides.clear()


def analyze(client, campaign, **extra):
    """POST /analyze and return (status, [(event, data), ...])."""
    events = []
    with client.stream("POST", "/api/v1/analyze", json={"campaign_id": campaign, **extra}) as response:
        if response.status_code != 200:
            response.read()
            return response.status_code, response.json()
        name = None
        for line in response.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return 200, events


def kinds(events):
    return [e for e, _ in events]


def test_a_run_streams_its_trace_then_a_summary(world, client):
    world.resource(INTERVIEW, segment=world.segment)
    status, events = analyze(client, world.campaign)

    assert status == 200 and kinds(events)[0] == "run" and kinds(events)[-1] == "summary"
    run_id = events[0][1]["run_id"]
    trace = [d for e, d in events if e == "trace"]
    nodes = [(d["node"], d["status"]) for d in trace]
    assert nodes[0] == ("run", "running") and nodes[-1] == ("run", "done")
    for node in ("select", "extract", "embed", "cluster", "name_themes", "score", "roadmap"):
        assert (node, "running") in nodes and (node, "done") in nodes
    assert nodes.index(("select", "done")) < nodes.index(("extract", "running")) < nodes.index(("roadmap", "done"))
    call = next(d for d in trace if d["node"] == "extract" and d.get("model_used"))
    assert call["model_used"] == "gemini:flash-lite" and call["tokens"] == 520 and "prompt" not in call  # prompts stay out of the stream

    summary = events[-1][1]
    assert (summary["selected"], summary["analysed"], summary["insights"], summary["themed"], summary["new_themes"]) == (1, 1, 2, 2, 1)
    assert summary["roadmap_created"] == 1 and summary["failed"] == 0 and summary["remaining"] == 0

    # replay: the stored run has the same steps, with prompts
    replay = client.get(f"/api/v1/runs/{run_id}").json()
    assert replay["status"] == "done" and replay["tokens"] > 0
    assert [(e["node"], e["status"]) for e in replay["events"]] == nodes
    assert any(e["prompt"] and e["prompt"].startswith("TEXT:") for e in replay["events"])
    listed = client.get("/api/v1/runs", params={"campaign_id": world.campaign}).json()
    assert [r["run_id"] for r in listed] == [run_id] and listed[0]["status"] == "done"


def test_each_request_takes_one_batch_and_reports_what_is_left(world, client, monkeypatch):
    world.resource(INTERVIEW)
    world.resource(MALAY, language="id")
    monkeypatch.setattr(api, "get_settings", lambda: Settings(analyze_batch_size=1))

    first = analyze(client, world.campaign)[1][-1][1]
    assert (first["selected"], first["analysed"], first["remaining"]) == (1, 1, 1)
    second = analyze(client, world.campaign)[1][-1][1]
    assert (second["selected"], second["analysed"], second["remaining"]) == (1, 1, 0)
    third = analyze(client, world.campaign)[1][-1][1]
    assert (third["selected"], third["insights"], third["remaining"]) == (0, 0, 0)
    assert len(client.get("/api/v1/runs", params={"campaign_id": world.campaign}).json()) == 3


def test_specific_resources_can_be_requested(world, client):
    world.resource(INTERVIEW)
    wanted = world.resource(MALAY, language="id")
    summary = analyze(client, world.campaign, resource_ids=[wanted])[1][-1][1]
    assert summary["selected"] == 1 and summary["remaining"] == 1


def test_only_one_run_at_a_time_per_campaign(world, client):
    world.resource(INTERVIEW)
    run_id = str(uuid4())
    marker = "insert into agent_runs (campaign_id, run_id, node, status, created_at) values (%s, %s, 'run', %s, now() - make_interval(mins => %s))"
    with database.user_tx(world.user) as conn:
        conn.execute(marker, (world.campaign, run_id, "running", 1))
    status, body = analyze(client, world.campaign)
    assert status == 409 and "already running" in body["detail"]

    with database.user_tx(world.user) as conn:  # the run ends: a new one may start
        conn.execute(marker, (world.campaign, run_id, "done", 0))
    assert analyze(client, world.campaign)[0] == 200


def test_a_run_that_never_finished_is_treated_as_dead_after_a_while(world, client):
    world.resource(INTERVIEW)
    run_id = str(uuid4())
    with database.user_tx(world.user) as conn:
        conn.execute(
            "insert into agent_runs (campaign_id, run_id, node, status, created_at) values (%s, %s, 'run', 'running', now() - interval '30 minutes')",
            (world.campaign, run_id),
        )
    assert analyze(client, world.campaign)[0] == 200
    stale = next(r for r in client.get("/api/v1/runs", params={"campaign_id": world.campaign}).json() if str(r["run_id"]) == run_id)
    assert stale["status"] == "stale"


def test_a_crashing_run_ends_with_an_error_event_and_frees_the_campaign(world, client, monkeypatch):
    world.resource(INTERVIEW)

    def boom(*args, **kwargs):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(api, "run_analysis", boom)
    status, events = analyze(client, world.campaign)
    assert status == 200 and kinds(events)[-1] == "error" and "database exploded" not in json.dumps(events[-1][1])
    run_id = events[0][1]["run_id"]
    replay = client.get(f"/api/v1/runs/{run_id}").json()
    assert replay["status"] == "error" and "database exploded" in json.dumps(replay["events"][-1]["output"])
    monkeypatch.undo()  # the next request may run
    assert not api._run_in_progress(world.user, world.campaign)


def test_other_users_and_unknown_campaigns_get_404(world, client):
    world.resource(INTERVIEW)
    assert analyze(client, str(uuid4()))[0] == 404
    run_id = analyze(client, world.campaign)[1][0][1]["run_id"]

    app.dependency_overrides[current_user] = lambda: AuthUser(id=uuid4())
    assert analyze(client, world.campaign)[0] == 404
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404
    assert client.get("/api/v1/runs", params={"campaign_id": world.campaign}).status_code == 404
    assert q(world.user, "select count(*) as n from agent_runs where run_id = %s", run_id)[0]["n"] > 0


def test_unknown_run_is_a_404(world, client):
    assert client.get(f"/api/v1/runs/{uuid4()}").status_code == 404


def test_event_formatting_and_trimming():
    assert api.sse("trace", {"a": 1}) == 'event: trace\ndata: {"a": 1}\n\n'
    assert len(api._trim("x" * 5000)) == api.MAX_EVENT_TEXT
    assert len(api._trim({"text": "y" * 5000})["text"]) == api.MAX_EVENT_TEXT
