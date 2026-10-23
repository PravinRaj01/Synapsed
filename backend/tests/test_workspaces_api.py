"""Workspace, campaign and segment endpoints against a real Neon database.

Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. Test workspaces are deleted afterwards.
"""

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


@pytest.fixture
def world():
    """A client that acts as `who.id`; switch `who.id` to act as someone else. Cleans up what it created."""
    who = SimpleNamespace(id=uuid4(), workspaces=[])
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:  # runs the lifespan, which opens the connection pool
        client.who = who
        yield client
    app.dependency_overrides.clear()
    if who.workspaces:
        with psycopg.connect(settings.database_url_admin) as admin:
            admin.execute("delete from workspaces where id = any(%s)", (who.workspaces,))


def workspace(client, name="Acme workspace"):
    r = client.post("/api/v1/workspaces", json={"name": name, "company": "Acme", "industry": "SaaS"})
    assert r.status_code == 201, r.text
    client.who.workspaces.append(r.json()["id"])
    return r.json()


def campaign(client, ws, **extra):
    r = client.post("/api/v1/campaigns", json={"workspace_id": ws["id"], "name": "Q4 research", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_list_workspaces(world):
    ws = workspace(world)
    assert ws["role"] == "owner" and ws["campaigns"] == 0
    listed = world.get("/api/v1/workspaces").json()
    assert [w["id"] for w in listed] == [ws["id"]] and listed[0]["company"] == "Acme" and listed[0]["role"] == "owner"


def test_workspace_needs_all_fields(world):
    assert world.post("/api/v1/workspaces", json={"name": "x", "company": "", "industry": "SaaS"}).status_code == 422
    assert world.post("/api/v1/workspaces", json={"name": "x"}).status_code == 422


def test_campaign_with_starting_segments_and_counts(world):
    ws = workspace(world)
    c = campaign(world, ws, goal="Why do enterprise users churn?", segments=[
        {"name": "Enterprise", "tier": "enterprise", "weight": 3}, {"name": "  Free   tier ", "tier": "free", "weight": 0.5}])
    assert c["goal"].startswith("Why") and (c["resources"], c["staged"], c["insights"], c["themes"]) == (0, 0, 0, 0)
    assert sorted((s["name"], s["tier"], float(s["weight"])) for s in c["segments"]) == [
        ("Enterprise", "enterprise", 3.0), ("Free tier", "free", 0.5)]
    fetched = world.get(f"/api/v1/campaigns/{c['id']}").json()
    assert len(fetched["segments"]) == 2 and fetched["name"] == "Q4 research"
    assert world.get("/api/v1/campaigns", params={"workspace_id": ws["id"]}).json()[0]["id"] == c["id"]
    assert world.get("/api/v1/workspaces").json()[0]["campaigns"] == 1


def test_duplicate_starting_segments_are_rejected_before_anything_is_created(world):
    ws = workspace(world)
    r = world.post("/api/v1/campaigns", json={"workspace_id": ws["id"], "name": "C", "segments": [
        {"name": "Enterprise"}, {"name": "enterprise"}]})
    assert r.status_code == 422
    assert world.get("/api/v1/campaigns").json() == []


def test_campaign_counts_follow_the_data(world):
    ws = workspace(world)
    c = campaign(world, ws)
    with database.user_tx(world.who.id) as conn:
        conn.execute(
            "insert into resources (campaign_id, title, source_type, content, content_hash, status) "
            "values (%s, 't', 'transcript', 'x', 'h1', 'staged'), (%s, 't2', 'transcript', 'y', 'h2', 'approved')",
            (c["id"], c["id"]),
        )
    got = world.get(f"/api/v1/campaigns/{c['id']}").json()
    assert (got["resources"], got["staged"]) == (2, 1)


def test_update_campaign(world):
    c = campaign(world, workspace(world))
    r = world.patch(f"/api/v1/campaigns/{c['id']}", json={"name": "Renamed", "goal": None})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["goal"] is None
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={"goal": "New goal"}).json()["name"] == "Renamed"
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={}).status_code == 422
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={"name": None}).status_code == 422


def test_segment_crud(world):
    c = campaign(world, workspace(world))
    cid = c["id"]
    made = world.post(f"/api/v1/campaigns/{cid}/segments", json={"name": "Mid market", "tier": "mid_market", "weight": 1.56})
    assert made.status_code == 201 and float(made.json()["weight"]) == 1.6  # stored with one decimal
    sid = made.json()["id"]
    assert world.post(f"/api/v1/campaigns/{cid}/segments", json={"name": "MID MARKET"}).status_code == 409

    patched = world.patch(f"/api/v1/segments/{sid}", json={"weight": 2, "description": "50-500 seats"})
    assert patched.status_code == 200 and float(patched.json()["weight"]) == 2.0 and patched.json()["name"] == "Mid market"
    other = world.post(f"/api/v1/campaigns/{cid}/segments", json={"name": "Free", "tier": "free"}).json()
    assert world.patch(f"/api/v1/segments/{other['id']}", json={"name": "mid market"}).status_code == 409
    assert world.patch(f"/api/v1/segments/{other['id']}", json={"name": "Free"}).status_code == 200  # renaming to itself is fine

    listed = world.get(f"/api/v1/campaigns/{cid}/segments").json()
    assert [s["name"] for s in listed] == ["Free", "Mid market"] and listed[0]["resources"] == 0

    assert world.delete(f"/api/v1/segments/{sid}").status_code == 204
    assert world.delete(f"/api/v1/segments/{sid}").status_code == 404
    assert [s["name"] for s in world.get(f"/api/v1/campaigns/{cid}/segments").json()] == ["Free"]


@pytest.mark.parametrize("body", [
    {"name": "x", "weight": 0}, {"name": "x", "weight": -1}, {"name": "x", "weight": 21},
    {"name": "x", "weight": 0.04}, {"name": "x", "tier": "vip"}, {"name": "   "}, {"name": ""},
])
def test_bad_segments_are_rejected(world, body):
    c = campaign(world, workspace(world))
    assert world.post(f"/api/v1/campaigns/{c['id']}/segments", json=body).status_code == 422


@pytest.mark.parametrize("body", [{"weight": 0}, {"tier": "vip"}, {"name": None}, {"weight": None}, {}])
def test_bad_segment_changes_are_rejected(world, body):
    c = campaign(world, workspace(world, "bad changes"))
    sid = world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "Keep"}).json()["id"]
    assert world.patch(f"/api/v1/segments/{sid}", json=body).status_code == 422


def test_deleting_a_segment_keeps_its_insights_and_resources(world):
    c = campaign(world, workspace(world))
    sid = world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "Enterprise", "weight": 3}).json()["id"]
    with database.user_tx(world.who.id) as conn:
        rid = conn.execute(
            "insert into resources (campaign_id, title, source_type, content, content_hash, segment_id) "
            "values (%s, 't', 'transcript', 'x', 'h', %s) returning id", (c["id"], sid)).fetchone()["id"]
    assert world.get(f"/api/v1/campaigns/{c['id']}/segments").json()[0]["resources"] == 1
    assert world.delete(f"/api/v1/segments/{sid}").status_code == 204
    with database.user_tx(world.who.id) as conn:
        assert conn.execute("select segment_id from resources where id = %s", (rid,)).fetchone()["segment_id"] is None


def test_segment_limit(world):
    c = campaign(world, workspace(world), segments=[{"name": f"S{i}"} for i in range(20)])
    assert world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "One too many"}).status_code == 409


def test_users_cannot_see_or_touch_each_others_data(world):
    ws = workspace(world)
    c = campaign(world, ws, segments=[{"name": "Enterprise"}])
    sid = c["segments"][0]["id"]

    world.who.id = uuid4()  # someone else
    assert world.get("/api/v1/workspaces").json() == []
    assert world.get("/api/v1/campaigns").json() == []
    assert world.get(f"/api/v1/campaigns/{c['id']}").status_code == 404
    assert world.patch(f"/api/v1/campaigns/{c['id']}", json={"name": "Hijacked"}).status_code == 404
    assert world.get(f"/api/v1/campaigns/{c['id']}/segments").status_code == 404
    assert world.post(f"/api/v1/campaigns/{c['id']}/segments", json={"name": "Spy"}).status_code == 404
    assert world.patch(f"/api/v1/segments/{sid}", json={"weight": 9}).status_code == 404
    assert world.delete(f"/api/v1/segments/{sid}").status_code == 404
    assert world.post("/api/v1/campaigns", json={"workspace_id": ws["id"], "name": "Intruder"}).status_code == 404
