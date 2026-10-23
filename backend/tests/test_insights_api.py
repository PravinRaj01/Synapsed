"""Insights Studio: chart specs, the chart engine, prompt-to-spec and the opportunity matrix. The pure parts need no
database; the rest run on Neon. Skipped (database parts) unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_pipeline import charts as ch
from ai_pipeline.providers import AllProvidersFailed, Completion
from app.api import insights as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
needs_db = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


# ---------------------------------------------------------------- spec validation (pure)

def test_a_minimal_spec_gets_sensible_defaults():
    spec = ch.ChartSpec(x="theme")
    assert (spec.type, spec.y, spec.split_by, spec.limit, spec.filters) == ("bar", "insights", None, 12, [])


@pytest.mark.parametrize("data", [
    {"x": "password"}, {"x": "theme", "y": "revenue"}, {"x": "theme", "type": "radar"}, {"x": "theme", "limit": 0},
    {"x": "theme", "limit": 31}, {"x": "theme", "split_by": "theme"}, {"x": "theme", "type": "stacked_bar"},
    {"x": "theme", "filters": [{"field": "created_at", "values": ["x"]}]}, {"x": "theme", "filters": [{"field": "theme", "values": []}]},
    {"x": "theme", "filters": [{"field": "theme", "values": ["a"]}] * 6}, {},
])
def test_anything_outside_the_whitelists_is_rejected(data):
    with pytest.raises(ValidationError):
        ch.ChartSpec.model_validate(data)


def test_pies_ignore_a_split_and_extra_keys_never_matter():
    spec = ch.ChartSpec.model_validate({"type": "pie", "x": "segment", "split_by": "sentiment", "sql": "drop table insights", "where": "1=1"})
    assert spec.split_by is None and not hasattr(spec, "sql")


def test_filter_values_are_tidied_and_lowercased():
    spec = ch.ChartSpec(x="segment", filters=[{"field": "sentiment", "values": ["  Negative ", "", "NEUTRAL"]}])
    assert spec.filters[0].values == ["negative", "neutral"]


# ---------------------------------------------------------------- prompt to spec (pure)

def completion(text):
    return Completion(text, "gemini", "flash-lite", 300, 60, 600)


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


GOOD = json.dumps({"type": "stacked_bar", "x": "segment", "split_by": "sentiment", "title": "Sentiment by segment"})


def test_a_valid_reply_becomes_a_spec_and_the_prompt_names_real_themes_and_segments():
    llm = scripted(GOOD)
    spec = ch.spec_from_prompt("show sentiment by segment", ["Slow export"], ["Enterprise", "Free"], llm)
    assert (spec.type, spec.x, spec.split_by) == ("stacked_bar", "segment", "sentiment")
    system, user = llm.calls[0]
    assert "whitelist" not in system["content"] and '"stacked_bar"' in system["content"]
    assert "Themes in this campaign: Slow export" in user["content"] and "Customer segments: Enterprise, Free" in user["content"]
    assert user["content"].endswith("Request: show sentiment by segment")


def test_an_invalid_first_reply_is_retried_with_the_problem_named():
    llm = scripted(json.dumps({"x": "salary"}), GOOD)
    spec = ch.spec_from_prompt("q", [], [], llm)
    assert spec.x == "segment" and len(llm.calls) == 2 and "not a valid chart specification" in llm.calls[1][-1]["content"]


def test_two_invalid_replies_give_up_with_a_friendly_message():
    with pytest.raises(ch.ChartRefused, match="Try rephrasing"):
        ch.spec_from_prompt("q", [], [], scripted("nonsense", json.dumps({"type": "bar"})))


def test_the_model_can_say_a_request_cannot_be_charted():
    with pytest.raises(ch.ChartRefused, match="no revenue data"):
        ch.spec_from_prompt("revenue by month", [], [], scripted(json.dumps({"error": "There is no revenue data."})))


def test_a_spec_with_an_error_key_but_real_fields_is_still_a_spec():
    spec = ch.spec_from_prompt("q", [], [], scripted(json.dumps({"x": "theme", "error": "none"})))
    assert spec.x == "theme"


def test_provider_failure_is_not_swallowed():
    with pytest.raises(AllProvidersFailed):
        ch.spec_from_prompt("q", [], [], scripted(AllProvidersFailed(["gemini: HTTP 429"])))


# ---------------------------------------------------------------- opportunity matrix (pure)

def theme(label, freq, impact, ice=None):
    return {"id": label, "label": label, "color": "#000", "frequency": freq, "business_impact": impact, "ice_score": ice, "horizon": "now"}


def test_themes_fall_into_quadrants_by_impact_and_frequency():
    m = ch.opportunity_matrix([theme("A", 10, 90), theme("B", 2, 80), theme("C", 9, 20), theme("D", 1, 10), theme("E", 8, 70)])
    assert m["impact_line"] == 50.0 and m["frequency_line"] == 8  # the median
    quadrant = {p["label"]: p["quadrant"] for p in m["points"]}
    assert quadrant == {"A": "priority", "B": "high_stakes", "C": "common_annoyance", "D": "monitor", "E": "priority"}
    assert {q["key"] for q in m["quadrants"]} == {"priority", "high_stakes", "common_annoyance", "monitor"}


def test_matrix_edge_cases():
    assert ch.opportunity_matrix([])["points"] == [] and ch.opportunity_matrix([])["frequency_line"] == 1
    only = ch.opportunity_matrix([theme("Solo", 0, 0)])["points"][0]
    assert only["quadrant"] == "monitor"  # a theme with no insights is never "frequent"


# ---------------------------------------------------------------- the engine and endpoints (database)

@pytest.fixture
def world():
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:
        with database.user_tx(who.id) as conn:
            ws = conn.execute("select create_workspace('Charts test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            empty = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'Empty') returning id", (ws,)).fetchone()["id"]
            ent = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, 'Enterprise', 'enterprise', 3) returning id", (cid,)).fetchone()["id"]
            free = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, 'Free', 'free', 0.5) returning id", (cid,)).fetchone()["id"]

            def resource(title, source_type, language):
                return conn.execute(
                    "insert into resources (campaign_id, title, source_type, content, content_hash, status, language) "
                    "values (%s, %s, %s, 'text', %s, 'approved', %s) returning id", (cid, title, source_type, uuid4().hex, language)).fetchone()["id"]

            res_a, res_b = resource("A", "transcript", "en"), resource("B", "ticket", "ms")
            t1 = conn.execute("insert into themes (campaign_id, label, color_code, frequency, business_impact) values (%s, 'Slow export', '#6366f1', 3, 100) returning id", (cid,)).fetchone()["id"]
            t2 = conn.execute("insert into themes (campaign_id, label, color_code, frequency, business_impact) values (%s, 'Onboarding', '#ec4899', 1, 10) returning id", (cid,)).fetchone()["id"]

            def insight(theme_id, seg, use_case, sev, sentiment, kind, res, when):
                iid = conn.execute(
                    "insert into insights (campaign_id, theme_id, segment_id, use_case, summary_text, severity, sentiment, kind, created_at) "
                    "values (%s, %s, %s, %s, 'x', %s, %s, %s, %s) returning id", (cid, theme_id, seg, use_case, sev, sentiment, kind, when)).fetchone()["id"]
                if res:
                    conn.execute("insert into citations (insight_id, resource_id, text_snippet, start_offset, end_offset) values (%s, %s, 'q', 0, 1)", (iid, res))

            at = lambda day: datetime(2026, 10, day, 12, tzinfo=timezone.utc)  # Mondays: 5, 12, 19
            insight(t1, ent, "reporting", 5, "negative", "pain_point", res_a, at(5))
            insight(t1, ent, "reporting", 4, "negative", "pain_point", res_a, at(6))
            insight(t1, free, "export", 2, "neutral", "feature_request", res_b, at(14))
            insight(t2, None, "onboarding", 3, "positive", "pain_point", res_a, at(14))
            insight(None, free, None, 1, "neutral", "pain_point", None, at(20))
            conn.execute("insert into roadmap_items (campaign_id, theme_id, title, description, horizon, impact_score, confidence_score, ease_score) "
                         "values (%s, %s, 'Fix export', 'd', 'now', 10, 5, 4)", (cid, t1))
        client.world = SimpleNamespace(who=who, campaign=str(cid), empty=str(empty), t1=str(t1), conn=None)
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def run(world, campaign=None, **spec):
    r = world.post(f"/api/v1/campaigns/{campaign or world.world.campaign}/charts/run", json={"spec": spec})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def series(result, name=None):
    s = next(s for s in result["series"] if name is None or s["name"] == name)
    return dict(zip(result["x"], s["values"]))


@needs_db
@pytest.mark.parametrize("x,measure,expected", [
    ("theme", "insights", {"Slow export": 3, "Onboarding": 1, "Unthemed": 1}),
    ("theme", "impact", {"Slow export": 28.0, "Onboarding": 3.0, "Unthemed": 0.5}),  # 3x5 + 3x4 + 0.5x2
    ("segment", "insights", {"Enterprise": 2, "Free": 2, "No segment": 1}),
    ("segment", "avg_severity", {"Enterprise": 4.5, "Free": 1.5, "No segment": 3.0}),
    ("sentiment", "insights", {"negative": 2, "neutral": 2, "positive": 1}),
    ("kind", "insights", {"pain_point": 4, "feature_request": 1}),
    ("severity", "insights", {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}),
    ("use_case", "insights", {"reporting": 2, "export": 1, "onboarding": 1, "Unspecified": 1}),
    ("source_type", "insights", {"transcript": 3, "ticket": 1, "unknown": 1}),
    ("source_type", "resources", {"transcript": 1, "ticket": 1, "unknown": 0}),
    ("language", "insights", {"en": 3, "ms": 1, "unknown": 1}),
    ("week", "insights", {"2026-10-05": 2, "2026-10-12": 2, "2026-10-19": 1}),
])
def test_every_dimension_and_measure_gives_the_right_numbers(world, x, measure, expected):
    result = run(world, x=x, y=measure, limit=30)
    assert series(result) == pytest.approx(expected)


@needs_db
def test_ordering_big_first_but_time_and_severity_read_in_order(world):
    assert run(world, x="theme")["x"][0] == "Slow export"
    assert run(world, x="severity")["x"] == ["1", "2", "3", "4", "5"]
    assert run(world, x="week")["x"] == ["2026-10-05", "2026-10-12", "2026-10-19"]
    assert run(world, x="week", limit=2)["x"] == ["2026-10-12", "2026-10-19"]  # the latest weeks
    assert len(run(world, x="theme", limit=2)["x"]) == 2


@needs_db
def test_stacked_charts_pivot_into_series(world):
    result = run(world, type="stacked_bar", x="segment", split_by="sentiment")
    assert set(result["x"]) == {"Enterprise", "Free", "No segment"}
    assert series(result, "negative") == {"Enterprise": 2, "Free": 0, "No segment": 0}
    assert series(result, "neutral") == {"Enterprise": 0, "Free": 2, "No segment": 0}
    assert series(result, "positive")["No segment"] == 1


@needs_db
def test_filters_are_case_insensitive_and_combine(world):
    assert series(run(world, x="segment", filters=[{"field": "sentiment", "values": ["Negative"]}])) == {"Enterprise": 2}
    assert series(run(world, x="theme", filters=[{"field": "segment", "values": ["ENTERPRISE"]}, {"field": "kind", "values": ["pain_point"]}])) == {"Slow export": 2}
    assert run(world, x="theme", filters=[{"field": "theme", "values": ["nope"]}])["x"] == []


@needs_db
def test_filter_values_are_parameters_never_sql(world):
    nasty = "x'); drop table insights; --"
    assert run(world, x="theme", filters=[{"field": "theme", "values": [nasty]}])["x"] == []
    assert run(world, x="theme")["x"]  # the table is still there


@needs_db
def test_an_empty_campaign_gives_an_empty_chart(world):
    assert run(world, campaign=world.world.empty, x="theme") == {"x": [], "series": [{"name": ch.MEASURE_LABELS["insights"], "values": []}], "measure": ch.MEASURE_LABELS["insights"]}


@needs_db
def test_the_preset_dashboard_runs_every_chart(world):
    presets = world.get(f"/api/v1/campaigns/{world.world.campaign}/charts/presets").json()
    assert [p["key"] for p in presets] == [k for k, _ in ch.PRESETS] and len(presets) == 7
    for p in presets:
        assert p["title"] and p["spec"]["x"] and set(p["result"]) == {"x", "series", "measure"}
        assert all(len(s["values"]) == len(p["result"]["x"]) for s in p["result"]["series"])
    assert series(presets[0]["result"]) == {"Slow export": 28.0, "Onboarding": 3.0, "Unthemed": 0.5}


@needs_db
def test_bad_specs_are_rejected_by_the_endpoint(world):
    path = f"/api/v1/campaigns/{world.world.campaign}/charts/run"
    for spec in ({"x": "password"}, {"x": "theme", "y": "revenue"}, {"type": "stacked_bar", "x": "theme"}, {}):
        assert world.post(path, json={"spec": spec}).status_code == 422


@needs_db
def test_charts_from_a_prompt(world, monkeypatch):
    llm = scripted(json.dumps({"type": "stacked_bar", "x": "segment", "split_by": "sentiment",
                               "filters": [{"field": "sentiment", "values": ["negative"]}], "title": "Negative sentiment by segment"}))
    monkeypatch.setattr(api, "call_llm", llm)
    r = world.post(f"/api/v1/campaigns/{world.world.campaign}/charts", json={"prompt": "show negative sentiment by segment as a stacked bar"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "Negative sentiment by segment" and body["spec"]["type"] == "stacked_bar" and body["tokens"] == 360
    assert body["result"]["x"] == ["Enterprise"] and series(body["result"], "negative") == {"Enterprise": 2}
    assert "Slow export" in llm.calls[0][1]["content"] and "Enterprise" in llm.calls[0][1]["content"]  # grounded in this campaign
    with database.user_tx(world.world.who.id) as conn:
        assert conn.execute("select count(*) as n from telemetry_logs where action_type = 'chart'").fetchone()["n"] == 1


@needs_db
def test_prompt_failures_are_clear(world, monkeypatch):
    path = f"/api/v1/campaigns/{world.world.campaign}/charts"
    monkeypatch.setattr(api, "call_llm", scripted(json.dumps({"error": "There is no revenue data."})))
    refused = world.post(path, json={"prompt": "revenue by month"})
    assert refused.status_code == 422 and "no revenue data" in refused.json()["detail"]
    monkeypatch.setattr(api, "call_llm", scripted(AllProvidersFailed(["gemini: HTTP 429"])))
    assert world.post(path, json={"prompt": "sentiment by segment"}).status_code == 502
    assert world.post(path, json={"prompt": "hi"}).status_code == 422  # too short


@needs_db
def test_opportunity_matrix_endpoint_includes_ice(world):
    m = world.get(f"/api/v1/campaigns/{world.world.campaign}/opportunity-matrix").json()
    points = {p["label"]: p for p in m["points"]}
    assert points["Slow export"]["ice_score"] == 200 and points["Slow export"]["horizon"] == "now" and points["Onboarding"]["ice_score"] is None
    assert points["Slow export"]["quadrant"] == "priority" and points["Onboarding"]["quadrant"] == "monitor"


@needs_db
def test_other_users_get_404_everywhere(world):
    w = world.world
    w.who.id = uuid4()
    for path in (f"/api/v1/campaigns/{w.campaign}/opportunity-matrix", f"/api/v1/campaigns/{w.campaign}/charts/presets"):
        assert world.get(path).status_code == 404
    assert world.post(f"/api/v1/campaigns/{w.campaign}/charts/run", json={"spec": {"x": "theme"}}).status_code == 404
    assert world.post(f"/api/v1/campaigns/{w.campaign}/charts", json={"prompt": "themes by impact"}).status_code == 404
