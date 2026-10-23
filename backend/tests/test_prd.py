"""PRD generation, Markdown export and Jira. The pure parts need no database; the endpoints run on Neon with the
model and Jira faked. Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_pipeline import prd as prd_logic
from ai_pipeline.providers import AllProvidersFailed, Completion
from app.api import prds as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import Settings, get_settings
from app.integrations import jira
from app.main import app

settings = get_settings()
needs_db = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

ITEM = {"title": "Fix export", "description": "Make export fast", "horizon": "now", "impact_score": 10,
        "confidence_score": 5, "ease_score": 4, "ice_score": 200}
THEME = {"label": "Slow export", "description": "Exports time out"}
EVIDENCE = [
    {"n": 1, "insight_id": "i1", "summary": "Export times out on large accounts", "severity": 5, "sentiment": "negative",
     "segment": "Enterprise", "quote": "The export also times out on big accounts", "resource_id": "r1",
     "resource_title": "Maya interview", "start_offset": 100, "end_offset": 141},
    {"n": 2, "insight_id": "i2", "summary": "Monthly reports need manual CSV merging", "severity": 4, "sentiment": "negative",
     "segment": None, "quote": "I stitch four CSV files together", "resource_id": "r1",
     "resource_title": "Maya interview", "start_offset": 10, "end_offset": 42},
]


def prd_json(**overrides):
    data = {
        "title": "Reliable large exports",
        "context": "Enterprise teams export monthly reports and hit timeouts on big accounts.",
        "problem": "Exports fail or take most of a day, forcing manual CSV merging.",
        "goals": ["Exports of 10,000+ rows complete", "  Remove manual merging  ", ""],
        "user_stories": [
            {"as_a": "finance analyst", "i_want": "to export a full account in one go", "so_that": "I can skip manual merging", "evidence": [2, 1, 9, 1]},
            {"as_a": "account admin", "i_want": "exports to finish without errors", "so_that": "month-end is not blocked", "evidence": []},
        ],
        "acceptance_criteria": ["An account with 50,000 rows exports without a timeout", "The export arrives as one file"],
        "out_of_scope": ["Scheduled exports"],
        "success_metrics": ["Export timeout rate below 1%"],
    }
    return json.dumps({**data, **overrides})


def completion(text):
    return Completion(text, "gemini", "flash-lite", 800, 400, 3000)


def scripted(*replies):
    queue = list(replies)
    calls = []

    def llm(messages):
        calls.append(messages)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return completion(reply)

    llm.calls = calls
    return llm


# ---------------------------------------------------------------- generation and rendering (pure)

def test_a_valid_reply_becomes_a_cleaned_prd_with_only_real_evidence_references():
    prd = prd_logic.generate(ITEM, THEME, EVIDENCE, scripted(prd_json()))
    assert prd.goals == ["Exports of 10,000+ rows complete", "Remove manual merging"]  # blank lines dropped, spaces tidied
    assert prd.user_stories[0].evidence == [1, 2]  # sorted, de-duplicated, the invented [9] removed


def test_the_prompt_numbers_the_evidence_and_includes_the_item():
    llm = scripted(prd_json())
    prd_logic.generate(ITEM, THEME, EVIDENCE, llm)
    system, user = llm.calls[0]
    assert "ONLY the evidence" in system["content"]
    assert "ROADMAP ITEM: Fix export" in user["content"] and "[1] Export times out" in user["content"]
    assert 'customer said: "The export also times out on big accounts"' in user["content"] and "segment: Enterprise" in user["content"]
    assert "impact 10/10" in user["content"] and "horizon now" in user["content"]


def test_a_bad_first_reply_is_retried_once_with_the_problem_named():
    llm = scripted("this is not json", prd_json())
    seen = []
    prd = prd_logic.generate(ITEM, THEME, EVIDENCE, llm, seen.append)
    assert prd.title == "Reliable large exports" and len(llm.calls) == 2 and len(seen) == 2
    assert "did not match the required JSON shape" in llm.calls[1][-1]["content"]


def test_a_reply_missing_required_parts_is_retried_and_then_given_up_on():
    broken = prd_json(user_stories=[])
    llm = scripted(broken, broken)
    with pytest.raises(ValueError, match="usable PRD"):
        prd_logic.generate(ITEM, THEME, EVIDENCE, llm)
    assert len(llm.calls) == 2 and "user_stories" in llm.calls[1][-1]["content"]


def test_all_providers_failing_is_not_swallowed():
    with pytest.raises(AllProvidersFailed):
        prd_logic.generate(ITEM, THEME, EVIDENCE, scripted(AllProvidersFailed(["gemini: HTTP 429"])))


def test_markdown_has_every_section_and_a_traceable_evidence_list():
    prd = prd_logic.generate(ITEM, THEME, EVIDENCE, scripted(prd_json()))
    md = prd_logic.render_markdown(prd, EVIDENCE, ITEM)
    for heading in ("# Reliable large exports", "## Context", "## Problem", "## Goals", "## User stories",
                    "## Acceptance criteria", "## Out of scope", "## Success metrics", "## Evidence traces"):
        assert heading in md
    assert "_Roadmap: Now · Impact 10/10 · Confidence 5/10 · Ease 4/10 · ICE 200_" in md
    assert "As a **finance analyst**, I want to export a full account in one go, so that I can skip manual merging. _(E1, E2)_" in md
    assert "- [ ] An account with 50,000 rows exports without a timeout" in md
    assert "**E1** · Export times out on large accounts · severity 5/5 · Enterprise\n> The export also times out on big accounts\n> — Maya interview, characters 100–141" in md
    assert "**E2** · Monthly reports need manual CSV merging · severity 4/5\n>" in md  # no segment, no dangling separator
    assert md.endswith("\n") and "As a **account admin**" in md and "_(E" not in md.split("As a **account admin**")[1].split("\n")[0]


def test_empty_optional_sections_say_so():
    prd = prd_logic.generate(ITEM, THEME, EVIDENCE, scripted(prd_json(out_of_scope=[], success_metrics=[])))
    md = prd_logic.render_markdown(prd, EVIDENCE, ITEM)
    assert "- Nothing explicitly excluded." in md and "- To be defined with the team." in md


# ---------------------------------------------------------------- Jira document conversion (pure)

def test_markdown_becomes_an_atlassian_document():
    md = "# Title\n_Roadmap: Now_\n\n## Goals\n- one\n- **two**\n\n## Criteria\n- [ ] check it\n\n> quoted text\n> — Maya, characters 1–2\n\nPlain **text** here."
    doc = jira.markdown_to_adf(md)
    assert doc["type"] == "doc" and doc["version"] == 1
    kinds = [b["type"] for b in doc["content"]]
    assert kinds == ["heading", "paragraph", "heading", "bulletList", "heading", "bulletList", "blockquote", "paragraph"]
    assert doc["content"][0]["attrs"] == {"level": 1} and doc["content"][2]["attrs"] == {"level": 2}
    items = doc["content"][3]["content"]
    assert [i["content"][0]["content"][0]["text"] for i in items] == ["one", "two"]
    assert doc["content"][5]["content"][0]["content"][0]["content"][0]["text"] == "check it"
    assert doc["content"][6]["content"][0]["content"][0]["text"] == "quoted text — Maya, characters 1–2"
    assert doc["content"][7]["content"][0]["text"] == "Plain text here."
    assert jira.markdown_to_adf("") == {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]}


def test_a_real_prd_converts_without_empty_text_nodes():
    prd = prd_logic.generate(ITEM, THEME, EVIDENCE, scripted(prd_json()))
    doc = jira.markdown_to_adf(prd_logic.render_markdown(prd, EVIDENCE, ITEM))

    def texts(node):
        if node.get("type") == "text":
            yield node["text"]
        for child in node.get("content", []):
            yield from texts(child)

    assert all(t for t in texts(doc))


JIRA = Settings(jira_base_url="https://team.atlassian.net/", jira_email="a@b.c", jira_api_token="tok", jira_project_key="SYN")


def test_jira_is_only_configured_when_every_setting_is_present():
    assert jira.configured(JIRA) and not jira.configured(Settings(jira_base_url="https://x", jira_email="a"))
    assert not jira.configured(Settings())


def test_jira_issue_request_shape_and_result(monkeypatch):
    sent = {}

    def post(url, json, auth, timeout):
        sent.update(url=url, json=json, auth=auth)
        return httpx.Response(201, json={"id": "1", "key": "SYN-42"})

    monkeypatch.setattr(jira.httpx, "post", post)
    assert jira.create_issue(JIRA, "  Fix   export ", "# T\n- a") == ("SYN-42", "https://team.atlassian.net/browse/SYN-42")
    assert sent["url"] == "https://team.atlassian.net/rest/api/3/issue" and sent["auth"] == ("a@b.c", "tok")
    fields = sent["json"]["fields"]
    assert fields["project"] == {"key": "SYN"} and fields["summary"] == "Fix export" and fields["issuetype"] == {"name": "Task"}
    assert fields["description"]["type"] == "doc"


@pytest.mark.parametrize("response,message", [
    (httpx.Response(401, json={}), "rejected the credentials"),
    (httpx.Response(403, json={}), "rejected the credentials"),
    (httpx.Response(400, json={"errors": {"issuetype": "Issue type is invalid"}}), "Issue type is invalid"),
    (httpx.Response(404, json={"errorMessages": ["Project not found"]}), "Project not found"),
    (httpx.Response(500, text="<html>oops</html>"), "HTTP 500"),
    (httpx.Response(201, json={}), "without an issue key"),
    (httpx.ConnectError("down"), "could not be reached"),
])
def test_jira_failures_become_readable_errors(monkeypatch, response, message):
    def post(url, json, auth, timeout):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(jira.httpx, "post", post)
    with pytest.raises(jira.JiraError, match=message):
        jira.create_issue(JIRA, "x", "y")


def test_unconfigured_jira_refuses_before_any_request():
    with pytest.raises(jira.JiraError, match="not configured"):
        jira.create_issue(Settings(), "x", "y")


# ---------------------------------------------------------------- endpoints

@pytest.fixture
def world():
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:
        with database.user_tx(who.id) as conn:
            ws = conn.execute("select create_workspace('PRD test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            seg = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, 'Enterprise', 'enterprise', 3) returning id", (cid,)).fetchone()["id"]
            text = "Maya: Every month I stitch four CSV files together. The export also times out on big accounts."
            res = conn.execute(
                "insert into resources (campaign_id, title, source_type, content, content_hash, status) "
                "values (%s, 'Maya interview', 'transcript', %s, 'h', 'approved') returning id", (cid, text)).fetchone()["id"]
            theme = conn.execute("insert into themes (campaign_id, label, description, color_code, frequency, business_impact) "
                                 "values (%s, 'Slow export', 'Exports time out', '#6366f1', 2, 100) returning id", (cid,)).fetchone()["id"]
            empty_theme = conn.execute("insert into themes (campaign_id, label, color_code) values (%s, 'No evidence', '#000') returning id", (cid,)).fetchone()["id"]
            for summary, quote, sev, segment in (("Export times out on large accounts", "The export also times out on big accounts", 5, seg),
                                                ("Monthly reports need manual CSV merging", "Every month I stitch four CSV files together", 3, None)):
                iid = conn.execute(
                    "insert into insights (campaign_id, theme_id, segment_id, summary_text, severity, sentiment) "
                    "values (%s, %s, %s, %s, %s, 'negative') returning id", (cid, theme, segment, summary, sev)).fetchone()["id"]
                start = text.index(quote)
                conn.execute("insert into citations (insight_id, resource_id, text_snippet, start_offset, end_offset) values (%s, %s, %s, %s, %s)",
                             (iid, res, quote, start, start + len(quote)))

            def item(title, theme_id):
                return conn.execute(
                    "insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score) "
                    "values (%s, %s, %s, 'Make export fast', 'now', 10, 5, 4) returning id", (cid, theme_id, title)).fetchone()["id"]

            client.world = SimpleNamespace(who=who, campaign=str(cid), item=str(item("Fix export", theme)), no_theme=str(item("Manual item", None)),
                                           no_evidence=str(item("Nothing yet", empty_theme)), text=text)
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


@pytest.fixture
def llm(monkeypatch):
    fake = scripted(*[prd_json()] * 5)
    monkeypatch.setattr(api, "call_llm", fake)
    return fake


@needs_db
def test_generate_store_list_read_and_export(world, llm):
    w = world.world
    r = world.post(f"/api/v1/roadmap/{w.item}/prd")
    assert r.status_code == 201, r.text
    stored = r.json()
    assert stored["roadmap_item_id"] == w.item and stored["jira_issue_key"] is None
    evidence = stored["content"]["evidence"]
    assert [e["summary"] for e in evidence] == ["Export times out on large accounts", "Monthly reports need manual CSV merging"]  # severity x weight order
    first = evidence[0]
    assert w.text[first["start_offset"]:first["end_offset"]] == first["quote"] == "The export also times out on big accounts"
    assert first["segment"] == "Enterprise" and first["resource_title"] == "Maya interview"
    assert stored["content"]["prd"]["user_stories"][0]["evidence"] == [1, 2]
    assert "**E1** · Export times out on large accounts" in stored["markdown"] and "ICE 200" in stored["markdown"]

    again = world.post(f"/api/v1/roadmap/{w.item}/prd").json()  # a second call is a new version
    listed = world.get(f"/api/v1/roadmap/{w.item}/prds").json()
    assert [p["id"] for p in listed] == [again["id"], stored["id"]] and listed[0]["title"] == "Reliable large exports"
    assert world.get(f"/api/v1/prds/{stored['id']}").json()["markdown"] == stored["markdown"]

    export = world.get(f"/api/v1/prds/{stored['id']}/markdown")
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/markdown")
    assert export.headers["content-disposition"] == 'attachment; filename="reliable-large-exports.md"'
    assert export.text == stored["markdown"]
    with database.user_tx(w.who.id) as conn:
        assert conn.execute("select count(*) as n from telemetry_logs where action_type = 'prd'").fetchone()["n"] == 2

    assert world.delete(f"/api/v1/prds/{stored['id']}").status_code == 204
    assert world.delete(f"/api/v1/prds/{stored['id']}").status_code == 404
    assert world.get(f"/api/v1/prds/{stored['id']}").status_code == 404


@needs_db
def test_items_without_evidence_cannot_get_a_prd(world, llm):
    w = world.world
    assert world.post(f"/api/v1/roadmap/{w.no_theme}/prd").status_code == 422
    assert world.post(f"/api/v1/roadmap/{w.no_evidence}/prd").status_code == 422
    assert world.post(f"/api/v1/roadmap/{uuid4()}/prd").status_code == 404
    assert llm.calls == []


@needs_db
def test_generation_failures_are_502s_and_store_nothing(world, monkeypatch):
    w = world.world
    monkeypatch.setattr(api, "call_llm", scripted(AllProvidersFailed(["gemini: HTTP 429"])))
    assert world.post(f"/api/v1/roadmap/{w.item}/prd").status_code == 502
    monkeypatch.setattr(api, "call_llm", scripted("junk", "more junk"))
    r = world.post(f"/api/v1/roadmap/{w.item}/prd")
    assert r.status_code == 502 and "unusable" in r.json()["detail"]
    assert world.get(f"/api/v1/roadmap/{w.item}/prds").json() == []


@needs_db
def test_integrations_and_jira_flow(world, llm, monkeypatch):
    w = world.world
    prd_id = world.post(f"/api/v1/roadmap/{w.item}/prd").json()["id"]

    assert world.get("/api/v1/integrations").json() == {"jira": {"configured": False, "project_key": None}}
    assert world.post(f"/api/v1/prds/{prd_id}/jira").status_code == 503

    monkeypatch.setattr(api, "get_settings", lambda: JIRA)
    assert world.get("/api/v1/integrations").json() == {"jira": {"configured": True, "project_key": "SYN"}}
    monkeypatch.setattr(jira.httpx, "post", lambda url, json, auth, timeout: httpx.Response(201, json={"key": "SYN-7"}))
    sent = world.post(f"/api/v1/prds/{prd_id}/jira")
    assert sent.status_code == 200 and sent.json() == {"jira_issue_key": "SYN-7", "url": "https://team.atlassian.net/browse/SYN-7"}
    assert world.get(f"/api/v1/prds/{prd_id}").json()["jira_issue_key"] == "SYN-7"
    again = world.post(f"/api/v1/prds/{prd_id}/jira")
    assert again.status_code == 409 and "SYN-7" in again.json()["detail"]


@needs_db
def test_a_jira_failure_is_a_502_and_leaves_the_prd_unsent(world, llm, monkeypatch):
    prd_id = world.post(f"/api/v1/roadmap/{world.world.item}/prd").json()["id"]
    monkeypatch.setattr(api, "get_settings", lambda: JIRA)
    monkeypatch.setattr(jira.httpx, "post", lambda url, json, auth, timeout: httpx.Response(401, json={}))
    r = world.post(f"/api/v1/prds/{prd_id}/jira")
    assert r.status_code == 502 and "credentials" in r.json()["detail"]
    assert world.get(f"/api/v1/prds/{prd_id}").json()["jira_issue_key"] is None


@needs_db
def test_other_users_cannot_generate_read_or_send(world, llm, monkeypatch):
    w = world.world
    prd_id = world.post(f"/api/v1/roadmap/{w.item}/prd").json()["id"]
    owner = w.who.id
    w.who.id = uuid4()
    monkeypatch.setattr(api, "get_settings", lambda: JIRA)
    assert world.post(f"/api/v1/roadmap/{w.item}/prd").status_code == 404
    assert world.get(f"/api/v1/roadmap/{w.item}/prds").status_code == 404
    for path in (f"/api/v1/prds/{prd_id}", f"/api/v1/prds/{prd_id}/markdown"):
        assert world.get(path).status_code == 404
    assert world.post(f"/api/v1/prds/{prd_id}/jira").status_code == 404
    assert world.delete(f"/api/v1/prds/{prd_id}").status_code == 404
    w.who.id = owner
    assert world.get(f"/api/v1/prds/{prd_id}").status_code == 200
