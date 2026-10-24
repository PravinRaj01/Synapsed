"""The demo sandbox: its data file is consistent, and loading it gives a campaign every page can use.

The data checks need no database. The loading checks are skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set.
"""

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.demo import embedded_texts, load_definition, load_embeddings, text_key
from app.main import app

settings = get_settings()
needs_database = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin), reason="DATABASE_URL and DATABASE_URL_ADMIN are not set"
)


def test_every_quote_is_in_its_source_and_every_reference_resolves():
    d = load_definition()
    resources = {r["key"]: r for r in d["resources"]}
    themes = {t["key"] for t in d["themes"]}
    segments = {s["name"] for s in d["segments"]}
    assert len(resources) == len(d["resources"]) and len(themes) == len(d["themes"])
    for r in d["resources"]:
        assert r["segment"] is None or r["segment"] in segments
        assert r["source_type"] in ("transcript", "ticket", "survey") and r["language"] in ("en", "ms")
    for i in d["insights"]:
        assert i["quote"] in resources[i["resource"]]["content"], i["quote"]
        assert i["theme"] in themes and (i["segment"] is None or i["segment"] in segments)
        assert 1 <= i["severity"] <= 5 and i["sentiment"] in ("positive", "neutral", "negative") and i["kind"] in ("pain_point", "feature_request")
    assert all(any(i["theme"] == t for i in d["insights"]) for t in themes)  # no empty theme


def test_the_demo_covers_both_languages_all_three_segments_and_each_sentiment():
    d = load_definition()
    assert {r["language"] for r in d["resources"]} == {"en", "ms"}
    assert {i["segment"] for i in d["insights"]} >= {"Enterprise", "Mid-Market", "Free", None}
    assert {i["sentiment"] for i in d["insights"]} == {"positive", "neutral", "negative"}


def test_stored_embeddings_cover_every_text_and_have_the_right_size():
    stored = load_embeddings()
    for text in embedded_texts(load_definition()):
        assert len(stored[text_key(text)]) == 768, f"run scripts/build_demo_embeddings.py: missing a vector for {text[:40]!r}"


@pytest.fixture
def world():
    who = SimpleNamespace(id=uuid4(), workspaces=[])
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:
        client.who = who
        ws = client.post("/api/v1/workspaces", json={"name": "Demo test", "company": "Acme", "industry": "SaaS"}).json()
        who.workspaces.append(ws["id"])
        client.ws = ws
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = any(%s)", (who.workspaces,))


def new_campaign(client, **extra):
    r = client.post("/api/v1/campaigns", json={"workspace_id": client.ws["id"], "name": "Demo", **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@needs_database
def test_loading_the_demo_gives_a_finished_campaign(world):
    cid = new_campaign(world)
    r = world.post(f"/api/v1/campaigns/{cid}/demo")
    assert r.status_code == 201, r.text
    d = load_definition()
    assert r.json() == {"resources": len(d["resources"]), "insights": len(d["insights"]), "themes": len(d["themes"]),
                        "roadmap_items": sum(1 for t in d["themes"] if t.get("roadmap", True))}

    o = world.get(f"/api/v1/campaigns/{cid}/overview").json()
    assert o["resources"]["approved"] == len(d["resources"]) and o["resources"]["waiting_for_analysis"] == 0
    assert o["segments"] == 3 and o["sentiment"]["positive"] > 0 and o["sentiment"]["negative"] > 0
    assert o["trend"]["resources"]["current"] > 0 and o["trend"]["resources"]["previous"] > 0  # a past to compare with

    report = world.get(f"/api/v1/campaigns/{cid}/themes").json()
    assert len(report) == len(d["themes"]) and max(float(t["business_impact"]) for t in report) == 100.0
    roadmap = world.get(f"/api/v1/campaigns/{cid}/roadmap").json()
    assert {item["horizon"] for item in roadmap} == {"now", "next", "later"} and all(item["ice_score"] > 0 for item in roadmap)
    assert all(item["theme"] for item in roadmap)


@needs_database
def test_citations_point_at_the_quote_and_a_chunk(world):
    cid = new_campaign(world)
    world.post(f"/api/v1/campaigns/{cid}/demo")
    with psycopg.connect(settings.database_url_admin) as admin:
        rows = admin.execute(
            """select c.text_snippet, c.start_offset, c.end_offset, substring(r.content from c.start_offset + 1 for c.end_offset - c.start_offset),
                      c.chunk_id is not null
               from citations c join insights i on i.id = c.insight_id join resources r on r.id = c.resource_id
               where i.campaign_id = %s""", (cid,)).fetchall()
        embedded = admin.execute(
            "select count(*) filter (where embedding is not null), count(*) from resource_chunks c join resources r on r.id = c.resource_id "
            "where r.campaign_id = %s", (cid,)).fetchone()
    assert len(rows) == len(load_definition()["insights"])
    assert all(snippet == cut and has_chunk for snippet, _, _, cut, has_chunk in rows)
    assert embedded[0] == embedded[1] > 0


@needs_database
def test_search_works_on_the_demo(world):
    cid = new_campaign(world)
    world.post(f"/api/v1/campaigns/{cid}/demo")
    hits = world.get("/api/v1/search", params={"campaign_id": cid, "q": "bank feed duplicate transactions"})
    assert hits.status_code == 200, hits.text
    assert hits.json()


@needs_database
def test_the_demo_keeps_existing_segments_and_refuses_a_second_load(world):
    cid = new_campaign(world, segments=[{"name": "Enterprise", "tier": "enterprise", "weight": 5}])
    assert world.post(f"/api/v1/campaigns/{cid}/demo").status_code == 201
    segments = {s["name"]: float(s["weight"]) for s in world.get(f"/api/v1/campaigns/{cid}/segments").json()}
    assert segments == {"Enterprise": 5.0, "Mid-Market": 2.0, "Free": 1.0}  # the user's weight wins
    again = world.post(f"/api/v1/campaigns/{cid}/demo")
    assert again.status_code == 409 and "no sources" in again.json()["detail"]


@needs_database
def test_a_campaign_with_sources_is_refused_and_a_stranger_gets_404(world):
    cid = new_campaign(world)
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute(
            "insert into resources (campaign_id, title, source_type, content, content_hash) values (%s, 'Mine', 'ticket', 'Exports are slow.', %s)",
            (cid, uuid4().hex))
    refused = world.post(f"/api/v1/campaigns/{cid}/demo")
    assert refused.status_code == 409 and "no sources" in refused.json()["detail"]
    assert world.get(f"/api/v1/campaigns/{cid}/overview").json()["insights"] == 0  # nothing half-loaded
    world.who.id = uuid4()
    assert world.post(f"/api/v1/campaigns/{cid}/demo").status_code == 404
