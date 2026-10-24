"""Assigning customer segments to sources, on a real Neon database (storage and the web are faked).
Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. The test workspace is deleted afterwards."""

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api import ingestion as ing
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.ingestion import web
from app.main import app

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

NOTE = "Maya said the monthly export takes ten minutes and often times out on big accounts. She exports every month. "
CSV = b"feedback,plan\nExport is slow every single month,Pro\nWe cannot find the metric definitions anywhere,\n"


@pytest.fixture
def world(monkeypatch):
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    objects = {}
    monkeypatch.setattr(ing.storage, "upload_bytes", lambda key, data, ct="": objects.update({key: data}) or key)
    monkeypatch.setattr(ing.storage, "delete_object", lambda key: objects.pop(key, None))
    monkeypatch.setattr(ing.storage, "object_size", lambda key: len(objects[key]) if key in objects else None)
    monkeypatch.setattr(ing.storage, "download_bytes", lambda key: objects[key])
    with TestClient(app) as client:
        with database.user_tx(who.id) as conn:
            ws = conn.execute("select create_workspace('Segment test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            other = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'Other') returning id", (ws,)).fetchone()["id"]
            seg = {n: conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, %s, %s, %s) returning id", (cid, n, t, w)).fetchone()["id"]
                   for n, t, w in (("Enterprise", "enterprise", 3), ("Free", "free", 0.5), ("Pro", "mid_market", 1.5))}
            foreign = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, 'Foreign', 'other', 1) returning id", (other,)).fetchone()["id"]
        client.world = SimpleNamespace(who=who, campaign=str(cid), other=str(other), seg={k: str(v) for k, v in seg.items()},
                                       foreign=str(foreign), objects=objects)
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def segment_of(world, resource_id):
    with database.user_tx(world.world.who.id) as conn:
        return conn.execute("select segment_id from resources where id = %s", (resource_id,)).fetchone()["segment_id"]


def ingest(world, name="note.txt", content=NOTE, **form):
    r = world.post("/api/v1/ingest", data={"campaign_id": world.world.campaign, **form}, files={"file": (name, content)})
    return r


# ---------------------------------------------------------------- on the way in

def test_a_file_can_be_tagged_with_a_segment_on_upload(world):
    w = world.world
    r = ingest(world, segment_id=w.seg["Enterprise"])
    assert r.status_code == 200, r.text
    assert str(segment_of(world, r.json()["resources"][0]["id"])) == w.seg["Enterprise"]
    untagged = ingest(world, content=NOTE + "A different note entirely about onboarding.")
    assert segment_of(world, untagged.json()["resources"][0]["id"]) is None


def test_a_spreadsheet_rows_own_segment_wins_over_the_upload_default(world):
    w = world.world
    r = ingest(world, "survey.csv", CSV, text_column="feedback", segment_column="plan", segment_id=w.seg["Free"])
    assert r.status_code == 200, r.text
    by_title = {x["title"]: str(segment_of(world, x["id"])) for x in r.json()["resources"]}
    assert by_title["survey.csv — Pro"] == w.seg["Pro"]  # the row named its segment
    assert by_title["survey.csv"] == w.seg["Free"]  # the row with no plan gets the default


def test_a_stored_upload_can_be_tagged_too(world):
    w = world.world
    ticket = world.post("/api/v1/uploads", json={"campaign_id": w.campaign, "filename": "late.txt", "size": len(NOTE)}).json()
    w.objects[ticket["key"]] = NOTE.encode()
    r = world.post("/api/v1/ingest/stored", json={"campaign_id": w.campaign, "key": ticket["key"], "segment_id": w.seg["Pro"]})
    assert r.status_code == 200, r.text
    assert str(segment_of(world, r.json()["resources"][0]["id"])) == w.seg["Pro"]


def test_web_research_results_can_be_tagged(world, monkeypatch):
    monkeypatch.setattr(web, "search_web", lambda q, n: [SimpleNamespace(url="https://example.org/a", title="A page")])
    monkeypatch.setattr(web, "fetch_page", lambda url: SimpleNamespace(url=url, title="A page", text=NOTE * 3))
    r = world.post("/api/v1/research", json={"campaign_id": world.world.campaign, "query": "export problems", "segment_id": world.world.seg["Free"]})
    assert r.status_code == 200, r.text
    assert str(segment_of(world, r.json()[0]["resource"]["id"])) == world.world.seg["Free"]


def test_a_segment_from_another_campaign_is_refused_on_every_path_and_nothing_is_stored(world, monkeypatch):
    w = world.world
    assert ingest(world, segment_id=w.foreign).status_code == 422
    assert ingest(world, segment_id=str(uuid4())).status_code == 422
    key = f"{w.campaign}/x/late.txt"
    w.objects[key] = NOTE.encode()
    assert world.post("/api/v1/ingest/stored", json={"campaign_id": w.campaign, "key": key, "segment_id": w.foreign}).status_code == 422
    assert world.post("/api/v1/research", json={"campaign_id": w.campaign, "query": "export problems", "segment_id": w.foreign}).status_code == 422
    assert world.get("/api/v1/resources", params={"campaign_id": w.campaign}).json() == []


def test_the_sources_list_shows_each_segment(world):
    w = world.world
    ingest(world, segment_id=w.seg["Enterprise"])
    ingest(world, content=NOTE + "Another note with different words about pricing and plans.")
    rows = {(r["segment"], str(r["segment_id"]) if r["segment_id"] else None) for r in world.get("/api/v1/resources", params={"campaign_id": w.campaign}).json()}
    assert rows == {("Enterprise", w.seg["Enterprise"]), (None, None)}


# ---------------------------------------------------------------- editing afterwards

def test_rename_and_set_or_clear_a_segment(world):
    w = world.world
    rid = ingest(world).json()["resources"][0]["id"]
    r = world.patch(f"/api/v1/resources/{rid}", json={"title": "  Maya   interview ", "segment_id": w.seg["Free"]})
    assert r.status_code == 200, r.text
    assert (r.json()["title"], r.json()["segment"], r.json()["rescored"]) == ("Maya interview", "Free", False)  # not analysed yet: nothing to rescore
    assert world.patch(f"/api/v1/resources/{rid}", json={"title": "Only the title"}).json()["segment"] == "Free"  # untouched
    cleared = world.patch(f"/api/v1/resources/{rid}", json={"segment_id": None}).json()
    assert cleared["segment_id"] is None and cleared["segment"] is None and cleared["title"] == "Only the title"


@pytest.mark.parametrize("body", [{}, {"title": ""}, {"title": None}])
def test_empty_changes_are_rejected(world, body):
    rid = ingest(world).json()["resources"][0]["id"]
    assert world.patch(f"/api/v1/resources/{rid}", json=body).status_code == 422


def test_unknown_sources_and_foreign_segments_are_refused(world):
    w = world.world
    rid = ingest(world).json()["resources"][0]["id"]
    assert world.patch(f"/api/v1/resources/{uuid4()}", json={"title": "x"}).status_code == 404
    assert world.patch(f"/api/v1/resources/{rid}", json={"segment_id": w.foreign}).status_code == 422
    assert segment_of(world, rid) is None


# ---------------------------------------------------------------- after analysis

@pytest.fixture
def analysed(world):
    """Three sources, two themes, one roadmap item each; no segments yet, so every insight weighs 1."""
    w = world.world
    with database.user_tx(w.who.id) as conn:
        def source(title):
            return conn.execute(
                "insert into resources (campaign_id, title, source_type, content, content_hash, status, analyzed_at) "
                "values (%s, %s, 'transcript', 'text', %s, 'approved', now()) returning id", (w.campaign, title, uuid4().hex)).fetchone()["id"]

        r1, r2, r3 = source("R1"), source("R2"), source("R3")
        t1 = conn.execute("insert into themes (campaign_id, label, color_code, frequency, business_impact) values (%s, 'Slow export', '#000', 2, 100) returning id", (w.campaign,)).fetchone()["id"]
        t2 = conn.execute("insert into themes (campaign_id, label, color_code, frequency, business_impact) values (%s, 'Onboarding', '#111', 1, 62.5) returning id", (w.campaign,)).fetchone()["id"]

        def insight(theme, severity, res):
            iid = conn.execute("insert into insights (campaign_id, theme_id, summary_text, severity) values (%s, %s, 'x', %s) returning id", (w.campaign, theme, severity)).fetchone()["id"]
            conn.execute("insert into citations (insight_id, resource_id, text_snippet, start_offset, end_offset) values (%s, %s, 'q', 0, 1)", (iid, res))
            return str(iid)

        insights = [insight(t1, 4, r1), insight(t1, 4, r2), insight(t2, 5, r3)]
        for theme, title, impact in ((t1, "Fix export", 10), (t2, "Explain metrics", 6)):
            conn.execute("insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score) "
                         "values (%s, %s, %s, 'd', 'now', %s, 5, 5)", (w.campaign, theme, title, impact))
    w.r = [str(r1), str(r2), str(r3)]
    w.insights = insights
    return world


def state(world):
    with database.user_tx(world.world.who.id) as conn:
        themes = {r["label"]: (float(r["business_impact"]), r["frequency"]) for r in conn.execute("select label, business_impact, frequency from themes").fetchall()}
        items = {r["title"]: (r["impact_score"], r["horizon"], r["ease_score"]) for r in conn.execute("select title, impact_score, horizon, ease_score from roadmap_items").fetchall()}
        segments = [str(r["segment_id"]) if r["segment_id"] else None for r in conn.execute(
            "select segment_id from insights where id = any(%s::uuid[]) order by severity, id", (world.world.insights,)).fetchall()]
    return themes, items, segments


def test_assigning_a_segment_to_an_analysed_source_updates_its_insights_and_every_dependent_score(analysed):
    w = analysed.world
    with database.user_tx(w.who.id) as conn:  # the PM has also moved one card and edited its ease
        conn.execute("update roadmap_items set horizon = 'later', ease_score = 2 where title = 'Explain metrics'")
    r = analysed.patch(f"/api/v1/resources/{w.r[2]}", json={"segment_id": w.seg["Enterprise"]})
    assert r.status_code == 200 and r.json()["rescored"] is True and r.json()["analyzed_at"] is not None
    themes, items, segments = state(analysed)
    # Onboarding: 1 insight x severity 5 x weight 3 = 15; Slow export: 2 x 4 x weight 1 = 8. Onboarding is now the strongest.
    assert themes["Onboarding"] == (100.0, 1) and themes["Slow export"] == pytest.approx((53.3, 2), abs=0.05)
    assert items["Explain metrics"] == (10, "later", 2) and items["Fix export"][0] == 5  # impact follows; the PM's horizon and ease stay
    assert segments.count(w.seg["Enterprise"]) == 1 and segments.count(None) == 2  # only the insight quoted from that source moved


def test_assigning_many_sources_at_once_recalculates_once(analysed):
    w = analysed.world
    r = analysed.post(f"/api/v1/campaigns/{w.campaign}/resources/segment", json={"resource_ids": [w.r[0], w.r[1], w.r[0]], "segment_id": w.seg["Free"]})
    assert r.status_code == 200 and r.json() == {"updated": 2, "segment_id": w.seg["Free"], "rescored": True}
    themes, items, _ = state(analysed)
    # Slow export: 2 x 4 x 0.5 = 4; Onboarding: 5 x 1 = 5 -> Onboarding leads
    assert themes["Onboarding"][0] == 100.0 and themes["Slow export"][0] == 80.0 and items["Fix export"][0] == 8
    cleared = analysed.post(f"/api/v1/campaigns/{w.campaign}/resources/segment", json={"resource_ids": [w.r[0], w.r[1]], "segment_id": None}).json()
    assert cleared["rescored"] is True and state(analysed)[0]["Slow export"][0] == 100.0


def test_bulk_assignment_checks_everything_before_changing_anything(analysed):
    w = analysed.world
    path = f"/api/v1/campaigns/{w.campaign}/resources/segment"
    assert analysed.post(path, json={"resource_ids": [w.r[0], str(uuid4())], "segment_id": w.seg["Free"]}).status_code == 422
    assert analysed.post(path, json={"resource_ids": [w.r[0]], "segment_id": w.foreign}).status_code == 422
    assert analysed.post(path, json={"resource_ids": []}).status_code == 422
    assert analysed.post(path, json={"resource_ids": [str(uuid4())] * 201}).status_code == 422
    assert state(analysed)[2] == [None, None, None]
    assert analysed.post(f"/api/v1/campaigns/{w.other}/resources/segment", json={"resource_ids": [w.r[0]], "segment_id": None}).status_code == 422  # sources of another campaign


def test_other_users_can_change_nothing(analysed):
    w = analysed.world
    w.who.id = uuid4()
    assert analysed.patch(f"/api/v1/resources/{w.r[0]}", json={"title": "Hijacked"}).status_code == 404
    assert analysed.post(f"/api/v1/campaigns/{w.campaign}/resources/segment", json={"resource_ids": [w.r[0]], "segment_id": None}).status_code == 404
    assert analysed.post("/api/v1/ingest", data={"campaign_id": w.campaign}, files={"file": ("a.txt", NOTE)}).status_code == 404
    assert state_titles(w) == {"R1", "R2", "R3"}


def state_titles(w):
    with psycopg.connect(settings.database_url_admin) as admin:
        return {r[0] for r in admin.execute("select title from resources where campaign_id = %s", (w.campaign,)).fetchall()}
