"""Report, viewer, roadmap and overview endpoints against a real Neon database.

Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. The test workspace is deleted afterwards.
"""

from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.api.report import build_theme_rows
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

TEXT_A = (
    "Maya: Every month I export four CSV files and stitch them together, which takes most of a day. "
    "The export also times out on big accounts. New hires cannot find what each metric means."
)
Q_STITCH = "Every month I export four CSV files and stitch them together"
Q_TIMEOUT = "The export also times out on big accounts"
Q_METRIC = "New hires cannot find what each metric means"
TEXT_B = "Tom: I just export a few rows now and then and it is slow."
Q_SLOW = "I just export a few rows now and then and it is slow"


def cite(text, quote):
    start = text.index(quote)
    return start, start + len(quote)


@pytest.fixture
def world():
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:
        user = who.id
        with database.user_tx(user) as conn:
            ws = conn.execute("select create_workspace('Report test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            seg = {}
            for name, tier, weight in (("Enterprise", "enterprise", 3), ("Free", "free", 0.5)):
                seg[name] = conn.execute(
                    "insert into segments (campaign_id, name, tier, weight) values (%s, %s, %s, %s) returning id",
                    (cid, name, tier, weight)).fetchone()["id"]

            def resource(title, text, status="approved", analyzed=True):
                return conn.execute(
                    """insert into resources (campaign_id, title, source_type, content, content_hash, status, language,
                                              analyzed_at, pii_note)
                       values (%s, %s, 'transcript', %s, %s, %s, 'en', case when %s then now() end, 'check names')
                       returning id""", (cid, title, text, uuid4().hex, status, analyzed)).fetchone()["id"]

            def theme(label, freq, impact, color):
                return conn.execute(
                    "insert into themes (campaign_id, label, description, color_code, frequency, business_impact) "
                    "values (%s, %s, %s, %s, %s, %s) returning id", (cid, label, f"About {label}", color, freq, impact)).fetchone()["id"]

            def insight(th, summary, seg_id, use_case, severity, sentiment, kind, res, text, quote):
                iid = conn.execute(
                    """insert into insights (campaign_id, theme_id, segment_id, use_case, summary_text, severity, sentiment, kind)
                       values (%s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                    (cid, th, seg_id, use_case, summary, severity, sentiment, kind)).fetchone()["id"]
                start, end = cite(text, quote)
                conn.execute(
                    "insert into citations (insight_id, resource_id, text_snippet, start_offset, end_offset) values (%s, %s, %s, %s, %s)",
                    (iid, res, quote, start, end))
                return iid

            res_a, res_b = resource("Maya interview", TEXT_A), resource("Tom ticket", TEXT_B)
            staged = resource("Pending upload", "Nothing analysed yet.", status="staged", analyzed=False)
            t_export, t_onboard = theme("Slow export", 3, 100, "#6366f1"), theme("Onboarding gaps", 1, 30, "#ec4899")
            i1 = insight(t_export, "Monthly reports need manual CSV merging", seg["Enterprise"], "monthly reporting", 4, "negative", "pain_point", res_a, TEXT_A, Q_STITCH)
            i2 = insight(t_export, "Export times out on large accounts", seg["Enterprise"], "monthly reporting", 5, "negative", "pain_point", res_a, TEXT_A, Q_TIMEOUT)
            i3 = insight(t_export, "Exports feel slow even for small data", seg["Free"], "ad hoc export", 2, "neutral", "feature_request", res_b, TEXT_B, Q_SLOW)
            i4 = insight(t_onboard, "New staff cannot find what metrics mean", None, "onboarding", 3, "positive", "pain_point", res_a, TEXT_A, Q_METRIC)
            r1 = conn.execute(
                "insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score) "
                "values (%s, %s, 'Fix export', 'Make export fast', 'now', 10, 5, 4) returning id", (cid, t_export)).fetchone()["id"]
            r2 = conn.execute(
                "insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score) "
                "values (%s, %s, 'Metric glossary', 'Explain metrics', 'later', 3, 4, 6) returning id", (cid, t_onboard)).fetchone()["id"]
            conn.execute("insert into telemetry_logs (campaign_id, model_used, tokens_processed, latency_ms, action_type, fallback_from) "
                         "values (%s, 'groq:a', 500, 900, 'extraction', null), (%s, 'gemini:b', 300, 700, 'clustering', 'groq: 429')", (cid, cid))
            conn.execute("insert into agent_runs (campaign_id, run_id, node, status) values (%s, %s, 'run', 'running'), (%s, %s, 'run', 'done')",
                         (cid, uuid4(), cid, uuid4()))
        client.world = SimpleNamespace(
            who=who, campaign=str(cid), seg=seg, res_a=str(res_a), res_b=str(res_b), staged=str(staged),
            t_export=str(t_export), t_onboard=str(t_onboard), i=[str(x) for x in (i1, i2, i3, i4)], r1=str(r1), r2=str(r2))
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def test_problem_space_report_rows(world):
    w = world.world
    rows = world.get(f"/api/v1/campaigns/{w.campaign}/themes").json()
    assert [r["label"] for r in rows] == ["Slow export", "Onboarding gaps"]  # strongest first
    export, onboard = rows
    assert (export["frequency"], float(export["business_impact"]), export["color"]) == (3, 100.0, "#6366f1")
    assert export["sentiment"] == "negative" and export["sentiment_counts"] == {"positive": 0, "neutral": 1, "negative": 2}
    assert export["average_severity"] == 3.7 and export["kinds"] == {"pain_point": 2, "feature_request": 1}
    assert export["sources"] == 2  # two different resources back it
    assert {(s["name"], s["tier"], s["insights"]) for s in export["segments"]} == {("Enterprise", "enterprise", 2), ("Free", "free", 1)}
    assert export["segments"][0]["name"] == "Enterprise"  # most affected group first
    assert export["use_cases"] == [{"use_case": "monthly reporting", "insights": 2}, {"use_case": "ad hoc export", "insights": 1}]
    assert onboard["sentiment"] == "positive" and onboard["segments"] == [{"segment_id": None, "name": "No segment", "tier": None, "insights": 1}]


def test_report_row_for_a_theme_without_insights_and_for_an_unknown_segment():
    themes = [{"id": "t1", "label": "Empty", "description": None, "color_code": "#000", "frequency": 0, "business_impact": 0}]
    row = build_theme_rows(themes, [], {}, {})[0]
    assert (row["average_severity"], row["sentiment"], row["segments"], row["sources"]) == (None, "neutral", [], 0)
    stray = [{"theme_id": "t1", "segment_id": "gone", "use_case": None, "sentiment": "negative", "severity": 3, "kind": "pain_point"}]
    assert build_theme_rows(themes, stray, {}, {})[0]["segments"] == []  # a segment deleted mid-read is skipped, not a crash


def test_theme_detail_has_insights_with_their_quotes(world):
    w = world.world
    theme = world.get(f"/api/v1/themes/{w.t_export}").json()
    assert theme["label"] == "Slow export" and theme["color"] == "#6366f1"
    assert [i["severity"] for i in theme["insights"]] == [5, 4, 2]  # worst first
    first = theme["insights"][0]
    assert first["segment"] == "Enterprise" and first["summary_text"].startswith("Export times out")
    quote = first["citations"][0]
    assert quote["text_snippet"] == Q_TIMEOUT and TEXT_A[quote["start_offset"]:quote["end_offset"]] == Q_TIMEOUT
    assert quote["resource_title"] == "Maya interview" and quote["resource_id"] == w.res_a
    assert world.get(f"/api/v1/themes/{uuid4()}").status_code == 404


def test_resource_viewer_returns_text_and_coloured_highlights(world):
    w = world.world
    r = world.get(f"/api/v1/resources/{w.res_a}").json()
    assert r["content"] == TEXT_A and r["title"] == "Maya interview" and r["pii_note"] == "check names"
    assert [h["text_snippet"] for h in r["highlights"]] == [Q_STITCH, Q_TIMEOUT, Q_METRIC]  # in reading order
    for h in r["highlights"]:
        assert TEXT_A[h["start_offset"]:h["end_offset"]] == h["text_snippet"]
    assert [(h["theme"], h["color"]) for h in r["highlights"]] == [
        ("Slow export", "#6366f1"), ("Slow export", "#6366f1"), ("Onboarding gaps", "#ec4899")]
    assert world.get(f"/api/v1/resources/{w.staged}").json()["highlights"] == []
    assert world.get(f"/api/v1/resources/{uuid4()}").status_code == 404


def test_roadmap_board_and_moving_a_card(world):
    w = world.world
    items = world.get(f"/api/v1/campaigns/{w.campaign}/roadmap").json()
    assert [(i["title"], i["horizon"], i["ice_score"], i["theme"]) for i in items] == [
        ("Fix export", "now", 200, "Slow export"), ("Metric glossary", "later", 72, "Onboarding gaps")]
    moved = world.patch(f"/api/v1/roadmap/{w.r1}", json={"horizon": "next"}).json()
    assert moved["horizon"] == "next" and moved["ice_score"] == 200 and moved["color"] == "#6366f1"
    rescored = world.patch(f"/api/v1/roadmap/{w.r1}", json={"ease_score": 8, "title": "  Make   export fast ", "description": "Cache it"}).json()
    assert (rescored["ease_score"], rescored["ice_score"], rescored["title"], rescored["description"]) == (8, 400, "Make export fast", "Cache it")
    assert world.get(f"/api/v1/campaigns/{w.campaign}/roadmap").json()[0]["horizon"] == "next"


@pytest.mark.parametrize("body", [
    {}, {"horizon": "soon"}, {"horizon": None}, {"ease_score": 0}, {"impact_score": 11}, {"confidence_score": 2.5},
    {"title": ""}, {"title": None}, {"description": ""},
])
def test_bad_roadmap_changes_are_rejected(world, body):
    assert world.patch(f"/api/v1/roadmap/{world.world.r1}", json=body).status_code == 422
    assert world.get(f"/api/v1/campaigns/{world.world.campaign}/roadmap").json()[0]["ice_score"] == 200  # nothing changed


def test_unknown_roadmap_item_is_a_404(world):
    assert world.patch(f"/api/v1/roadmap/{uuid4()}", json={"horizon": "now"}).status_code == 404


def test_dashboard_overview(world):
    w = world.world
    o = world.get(f"/api/v1/campaigns/{w.campaign}/overview").json()
    assert o["resources"] == {"total": 3, "staged": 1, "approved": 2, "rejected": 0, "waiting_for_analysis": 0}
    assert (o["insights"], o["themes"], o["roadmap_items"], o["segments"]) == (4, 2, 2, 2)
    assert o["sentiment"] == {"positive": 1, "neutral": 1, "negative": 2}
    assert [t["label"] for t in o["top_themes"]] == ["Slow export", "Onboarding gaps"]
    assert {r["title"] for r in o["recent_resources"]} == {"Maya interview", "Tom ticket", "Pending upload"}  # same-transaction inserts tie on time
    assert o["telemetry"]["calls"] == 2 and o["telemetry"]["tokens"] == 800 and o["telemetry"]["fallbacks"] == 1
    assert {m["model_used"] for m in o["telemetry"]["by_model"]} == {"groq:a", "gemini:b"}
    assert o["last_run"]["status"] in ("running", "done")


def test_overview_of_an_empty_campaign(world):
    c = world.post("/api/v1/campaigns", json={"workspace_id": world.get("/api/v1/workspaces").json()[0]["id"], "name": "Empty"}).json()
    o = world.get(f"/api/v1/campaigns/{c['id']}/overview").json()
    assert o["resources"]["total"] == 0 and o["top_themes"] == [] and o["last_run"] is None
    assert o["telemetry"] == {"calls": 0, "tokens": 0, "fallbacks": 0, "by_model": []}
    assert world.get(f"/api/v1/campaigns/{c['id']}/themes").json() == []
    assert world.get(f"/api/v1/campaigns/{c['id']}/roadmap").json() == []


def test_other_users_see_nothing(world):
    w = world.world
    owner = w.who.id
    w.who.id = uuid4()
    for path in (f"/api/v1/campaigns/{w.campaign}/themes", f"/api/v1/campaigns/{w.campaign}/roadmap",
                 f"/api/v1/campaigns/{w.campaign}/overview", f"/api/v1/themes/{w.t_export}", f"/api/v1/resources/{w.res_a}"):
        assert world.get(path).status_code == 404, path
    assert world.patch(f"/api/v1/roadmap/{w.r1}", json={"horizon": "later"}).status_code == 404
    w.who.id = owner  # and the owner's board is untouched
    assert world.get(f"/api/v1/campaigns/{w.campaign}/roadmap").json()[0]["horizon"] == "now"
