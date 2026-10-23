"""Persona generation: the pure parts need no database; the endpoints run on Neon with the model faked.
Skipped (database parts) unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_pipeline import personas as lg
from ai_pipeline.providers import AllProvidersFailed, Completion
from app.api import personas as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
needs_db = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

SEGMENT = {"name": "Enterprise", "tier": "enterprise", "weight": 3, "description": None}
EVIDENCE = [
    {"n": 1, "summary": "Export times out", "severity": 5, "sentiment": "negative", "use_case": "monthly reporting", "theme": "Slow export",
     "quote": "The export times out on big accounts", "resource_id": "r1", "resource_title": "Maya interview", "start_offset": 10, "end_offset": 46},
    {"n": 2, "summary": "Manual CSV merging", "severity": 4, "sentiment": "negative", "use_case": None, "theme": None,
     "quote": "I stitch four CSV files together", "resource_id": "r2", "resource_title": "Tom ticket", "start_offset": 0, "end_offset": 32},
]


def persona_json(**overrides):
    data = {"name": "The Month-End Reporter", "description": "Finance staff who assemble monthly reports from large exports and lose a day to it.",
            "goals": ["Close the month on time", " Avoid manual merging "], "frustrations": ["Exports time out", "Four CSV files to merge", ""],
            "behaviours": ["Works in spreadsheets"], "typical_use_cases": ["monthly reporting"], "quote_refs": [2, 9, 2, 1]}
    return json.dumps({**data, **overrides})


def completion(text):
    return Completion(text, "gemini", "flash-lite", 700, 300, 2500)


def scripted(*replies):
    queue, calls = list(replies), []

    def llm(messages):
        calls.append(messages)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return completion(reply)

    llm.calls = calls
    return llm


# ---------------------------------------------------------------- pure

def test_the_prompt_asks_for_an_archetype_and_shows_the_segment_and_numbered_evidence():
    llm = scripted(persona_json())
    lg.generate(SEGMENT, EVIDENCE, llm)
    system, user = llm.calls[0]
    assert "ARCHETYPE" in system["content"] and "Never a person's name" in system["content"] and "Do not invent demographics" in system["content"]
    assert "SEGMENT: Enterprise (tier: enterprise, weight 3)" in user["content"]
    assert '[1] Export times out (severity 5/5, negative, use case: monthly reporting, theme: Slow export)' in user["content"]
    assert 'customer said: "I stitch four CSV files together"' in user["content"]


def test_the_reply_is_cleaned_and_quote_refs_are_limited_to_real_evidence():
    p = lg.generate(SEGMENT, EVIDENCE, scripted(persona_json()))
    assert p.goals == ["Close the month on time", "Avoid manual merging"] and p.frustrations == ["Exports time out", "Four CSV files to merge"]
    assert p.quote_refs == [2, 1]  # the invented 9 and the duplicate are gone, order kept


def test_a_malformed_reply_is_retried_once():
    llm = scripted("no json here", persona_json())
    assert lg.generate(SEGMENT, EVIDENCE, llm).name == "The Month-End Reporter"
    assert "did not match the required JSON shape" in llm.calls[1][-1]["content"]


def test_a_persona_that_stays_unusable_is_an_error():
    broken = persona_json(frustrations=[])
    with pytest.raises(ValueError, match="usable persona"):
        lg.generate(SEGMENT, EVIDENCE, scripted(broken, broken))
    with pytest.raises(AllProvidersFailed):
        lg.generate(SEGMENT, EVIDENCE, scripted(AllProvidersFailed(["gemini: HTTP 429"])))


def test_stored_attributes_carry_the_real_quotes_the_model_picked():
    p = lg.generate(SEGMENT, EVIDENCE, scripted(persona_json()))
    attrs = lg.attributes(p, EVIDENCE, insight_count=7)
    assert [q["quote"] for q in attrs["quotes"]] == ["I stitch four CSV files together", "The export times out on big accounts"]
    assert attrs["quotes"][0]["resource_title"] == "Tom ticket" and (attrs["quotes"][0]["start_offset"], attrs["quotes"][0]["end_offset"]) == (0, 32)
    assert attrs["generated"] is True and attrs["insight_count"] == 7 and attrs["evidence_used"] == 2


def test_a_persona_always_gets_at_least_one_quote():
    p = lg.generate(SEGMENT, EVIDENCE, scripted(persona_json(quote_refs=[])))
    assert [q["quote"] for q in lg.attributes(p, EVIDENCE, 2)["quotes"]] == [e["quote"] for e in EVIDENCE]


# ---------------------------------------------------------------- endpoints

@pytest.fixture
def world():
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:
        with database.user_tx(who.id) as conn:
            ws = conn.execute("select create_workspace('Persona test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            other = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'Other') returning id", (ws,)).fetchone()["id"]
            seg = {}
            for name, tier, weight in (("Enterprise", "enterprise", 3), ("Free", "free", 0.5), ("Lonely", "other", 1)):
                seg[name] = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, %s, %s, %s) returning id", (cid, name, tier, weight)).fetchone()["id"]
            foreign_segment = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, 'Foreign', 'other', 1) returning id", (other,)).fetchone()["id"]
            text = "Maya: the export times out on big accounts. I stitch four CSV files together. Onboarding is a mess."
            res = conn.execute("insert into resources (campaign_id, title, source_type, content, content_hash, status) values (%s, 'Maya interview', 'transcript', %s, 'h', 'approved') returning id", (cid, text)).fetchone()["id"]

            def insight(segment, summary, quote, sev):
                iid = conn.execute("insert into insights (campaign_id, segment_id, summary_text, severity, sentiment) values (%s, %s, %s, %s, 'negative') returning id", (cid, segment, summary, sev)).fetchone()["id"]
                start = text.index(quote)
                conn.execute("insert into citations (insight_id, resource_id, text_snippet, start_offset, end_offset) values (%s, %s, %s, %s, %s)", (iid, res, quote, start, start + len(quote)))

            insight(seg["Enterprise"], "Export times out", "the export times out on big accounts", 5)
            insight(seg["Enterprise"], "Manual CSV merging", "I stitch four CSV files together", 4)
            insight(seg["Free"], "Onboarding is confusing", "Onboarding is a mess", 3)
            insight(seg["Free"], "Export times out too", "the export times out on big accounts", 2)
            insight(seg["Lonely"], "One lonely complaint", "Onboarding is a mess", 3)  # only one insight: not enough for a persona
        client.world = SimpleNamespace(who=who, campaign=str(cid), seg={k: str(v) for k, v in seg.items()}, foreign=str(foreign_segment), text=text)
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def generate(world, **body):
    return world.post(f"/api/v1/campaigns/{world.world.campaign}/personas/generate", json=body or None)


@needs_db
def test_a_persona_is_written_for_each_segment_with_enough_insights(world, monkeypatch):
    w = world.world
    llm = scripted(persona_json(), persona_json(name="The Newcomer Struggling to Onboard"))
    monkeypatch.setattr(api, "call_llm", llm)
    r = generate(world)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["segment"] for p in body["personas"]] == ["Enterprise", "Free"]
    assert body["skipped"] == [{"segment": "Lonely", "reason": "needs at least 2 analysed insights with quotes"}] and body["failed"] == []
    enterprise = body["personas"][0]
    assert enterprise["name"] == "The Month-End Reporter" and enterprise["tier"] == "enterprise"
    quotes = enterprise["attributes"]["quotes"]
    assert [q["quote"] for q in quotes] == ["I stitch four CSV files together", "the export times out on big accounts"]  # evidence 2 then 1
    for q in quotes:
        assert w.text[q["start_offset"]:q["end_offset"]] == q["quote"] and q["resource_title"] == "Maya interview"
    assert enterprise["attributes"]["insight_count"] == 2 and enterprise["attributes"]["generated"] is True
    assert "SEGMENT: Free" in llm.calls[1][1]["content"] and "Onboarding is a mess" in llm.calls[1][1]["content"]
    with database.user_tx(w.who.id) as conn:
        assert conn.execute("select count(*) as n from telemetry_logs where action_type = 'persona'").fetchone()["n"] == 2


@needs_db
def test_regenerating_replaces_generated_personas_but_never_hand_made_ones(world, monkeypatch):
    w = world.world
    manual = world.post(f"/api/v1/campaigns/{w.campaign}/personas", json={"name": "Our CFO", "description": "Signs off on every renewal.", "segment_id": w.seg["Enterprise"]})
    assert manual.status_code == 201 and manual.json()["attributes"] == {"generated": False}
    monkeypatch.setattr(api, "call_llm", scripted(*[persona_json(), persona_json()] * 2))
    generate(world)
    second = generate(world, segment_ids=[w.seg["Enterprise"]]).json()
    assert len(second["personas"]) == 1 and second["skipped"] == []
    listed = world.get(f"/api/v1/campaigns/{w.campaign}/personas").json()
    assert sorted((p["segment"], p["name"]) for p in listed) == [("Enterprise", "Our CFO"), ("Enterprise", "The Month-End Reporter"), ("Free", "The Month-End Reporter")]


@needs_db
def test_one_segment_failing_does_not_stop_the_others(world, monkeypatch):
    monkeypatch.setattr(api, "call_llm", scripted(persona_json(), AllProvidersFailed(["gemini: HTTP 429"])))
    body = generate(world).json()
    assert [p["segment"] for p in body["personas"]] == ["Enterprise"]
    assert [f["segment"] for f in body["failed"]] == ["Free"] and "Try again" in body["failed"][0]["error"]
    monkeypatch.setattr(api, "call_llm", scripted("junk", "junk"))
    assert [f["segment"] for f in generate(world, segment_ids=[world.world.seg["Free"]]).json()["failed"]] == ["Free"]
    assert [p["segment"] for p in world.get(f"/api/v1/campaigns/{world.world.campaign}/personas").json()] == ["Enterprise"]


@needs_db
def test_segments_from_another_campaign_are_refused(world, monkeypatch):
    monkeypatch.setattr(api, "call_llm", scripted(persona_json()))
    assert generate(world, segment_ids=[world.world.foreign]).status_code == 422
    assert generate(world, segment_ids=[str(uuid4())]).status_code == 422


@needs_db
def test_edit_and_delete_personas(world):
    w = world.world
    made = world.post(f"/api/v1/campaigns/{w.campaign}/personas", json={"name": " Our   CFO ", "description": "Signs off."}).json()
    assert made["name"] == "Our CFO" and made["segment"] is None
    patched = world.patch(f"/api/v1/personas/{made['id']}", json={"description": "Signs off on every renewal."})
    assert patched.status_code == 200 and patched.json()["description"] == "Signs off on every renewal." and patched.json()["name"] == "Our CFO"
    for bad in ({}, {"name": None}, {"name": ""}):
        assert world.patch(f"/api/v1/personas/{made['id']}", json=bad).status_code == 422
    assert world.post(f"/api/v1/campaigns/{w.campaign}/personas", json={"name": "x", "description": "y", "segment_id": w.foreign}).status_code == 422
    assert world.delete(f"/api/v1/personas/{made['id']}").status_code == 204
    assert world.delete(f"/api/v1/personas/{made['id']}").status_code == 404
    assert world.patch(f"/api/v1/personas/{uuid4()}", json={"name": "x"}).status_code == 404


@needs_db
def test_other_users_see_and_change_nothing(world, monkeypatch):
    w = world.world
    monkeypatch.setattr(api, "call_llm", scripted(persona_json(), persona_json()))
    persona_id = generate(world).json()["personas"][0]["id"]
    owner = w.who.id
    w.who.id = uuid4()
    assert world.get(f"/api/v1/campaigns/{w.campaign}/personas").status_code == 404
    assert generate(world).status_code == 404
    assert world.post(f"/api/v1/campaigns/{w.campaign}/personas", json={"name": "x", "description": "y"}).status_code == 404
    assert world.patch(f"/api/v1/personas/{persona_id}", json={"name": "Hijacked"}).status_code == 404
    assert world.delete(f"/api/v1/personas/{persona_id}").status_code == 404
    w.who.id = owner
    assert len(world.get(f"/api/v1/campaigns/{w.campaign}/personas").json()) == 2
