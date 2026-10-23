"""Forecast, what-if and narrative. The maths need no database; the endpoints run on Neon with the model faked.
Skipped (database parts) unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from ai_pipeline import forecast as fc
from ai_pipeline import narrative as nv
from ai_pipeline.providers import AllProvidersFailed, Completion
from app.api import scenario as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
needs_db = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

TODAY = date(2026, 10, 24)  # a Saturday; its week starts Monday 19 October


# ---------------------------------------------------------------- the weekly series

def test_weeks_start_on_monday_and_gaps_are_filled_with_zero():
    series = fc.weekly_series([(date(2026, 10, 7), 1), (date(2026, 10, 8), 2), (date(2026, 10, 21), 1)], TODAY)
    assert [(p["week"], p["value"]) for p in series] == [("2026-10-05", 3), ("2026-10-12", 0), ("2026-10-19", 1)]
    assert [p["partial"] for p in series] == [False, False, True]  # the current week is not over


def test_the_current_week_appears_even_without_data_and_nothing_gives_an_empty_series():
    series = fc.weekly_series([(date(2026, 10, 7), 1)], TODAY)
    assert [p["week"] for p in series] == ["2026-10-05", "2026-10-12", "2026-10-19"] and series[-1]["value"] == 0 and series[-1]["partial"]
    assert fc.weekly_series([], TODAY) == []


# ---------------------------------------------------------------- Holt

def test_a_straight_line_is_continued_exactly_with_no_uncertainty():
    f = fc.holt([2, 4, 6, 8, 10], 3)
    assert f.values == pytest.approx([12, 14, 16]) and f.lower == f.upper == f.values
    assert f.trend == "rising" and f.weekly_change == pytest.approx(2)


def test_a_flat_series_stays_flat_and_a_falling_one_never_goes_below_zero():
    flat = fc.holt([5, 5, 5, 5, 5], 4)
    assert flat.values == [5.0] * 4 and flat.trend == "flat" and flat.weekly_change == 0
    falling = fc.holt([9, 6, 3, 1, 0], 6)
    assert falling.trend == "falling" and all(v >= 0 for v in falling.values + falling.lower) and falling.values[-1] == 0


def test_noisy_data_widens_the_interval_the_further_ahead_we_look():
    f = fc.holt([3, 7, 2, 8, 4, 9, 3], 6)
    widths = [u - l for l, u in zip(f.lower, f.upper)]
    assert widths[0] > 0 and widths == sorted(widths) and all(l <= v <= u for l, v, u in zip(f.lower, f.values, f.upper))


def test_too_little_data_is_refused():
    with pytest.raises(ValueError):
        fc.holt([1, 2, 3], 2)


def test_forecast_block_uses_complete_weeks_only_and_dates_the_future():
    series = [{"week": w, "value": v, "partial": False} for w, v in
              (("2026-09-07", 1), ("2026-09-14", 2), ("2026-09-21", 3), ("2026-09-28", 4), ("2026-10-05", 5), ("2026-10-12", 6))]
    series.append({"week": "2026-10-19", "value": 2, "partial": True})
    block = fc.forecast_series(series, 3)
    assert [p["week"] for p in block["forecast"]] == ["2026-10-19", "2026-10-26", "2026-11-02"]
    assert [p["value"] for p in block["forecast"]] == pytest.approx([7, 8, 9])  # the partial week of 2 did not drag it down
    assert block["weeks_used"] == 6 and block["method"] == fc.METHOD and block["interval"] == "80%" and "estimate" in block["note"]


def test_not_enough_complete_weeks_gives_an_honest_note_instead_of_a_forecast():
    series = [{"week": "2026-10-05", "value": 3, "partial": False}, {"week": "2026-10-12", "value": 4, "partial": False},
              {"week": "2026-10-19", "value": 1, "partial": True}]
    block = fc.forecast_series(series, 4)
    assert block["forecast"] is None and block["weeks_used"] == 2 and "at least 4 complete weeks" in block["note"]
    assert fc.forecast_series([], 4)["forecast"] is None


def test_the_horizon_is_capped():
    series = [{"week": day, "value": float(i), "partial": False} for i, day in enumerate(["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"], 1)]
    assert len(fc.forecast_series(series, 99)["forecast"]) == fc.MAX_HORIZON


# ---------------------------------------------------------------- what-if

CELLS = {("T1", "ent"): {"count": 2, "severity_sum": 9}, ("T1", "free"): {"count": 1, "severity_sum": 2},
         ("T2", "free"): {"count": 4, "severity_sum": 12}, ("T2", None): {"count": 1, "severity_sum": 3}}
WEIGHTS = {"ent": 3.0, "free": 0.5}
LABELS = {"T1": "Slow export", "T2": "Onboarding"}


def themes_by_id(result):
    return {r["theme_id"]: r for r in result["themes"]}


def test_changing_nothing_changes_nothing():
    r = themes_by_id(fc.what_if(CELLS, WEIGHTS, LABELS))
    assert r["T1"]["before"] == r["T1"]["after"] and r["T1"]["before"]["business_impact"] == 100.0 and r["T2"]["before"]["business_impact"] == 32.1
    assert r["T1"]["impact_change"] == 0 and r["T1"]["rank_change"] == 0


def test_raising_a_segments_weight_can_change_which_theme_matters_most():
    result = fc.what_if(CELLS, WEIGHTS, LABELS, segment_weights={"free": 3.0})
    t = themes_by_id(result)
    assert (t["T1"]["before"]["rank"], t["T2"]["before"]["rank"]) == (1, 2) and (t["T1"]["after"]["rank"], t["T2"]["after"]["rank"]) == (2, 1)
    assert t["T2"]["after"]["business_impact"] == 100.0 and t["T1"]["after"]["business_impact"] == pytest.approx(84.6)  # 33 against 39
    assert t["T2"]["rank_change"] == 1 and t["T1"]["rank_change"] == -1  # positive means it moved up
    assert (result["top_before"], result["top_after"]) == ("Slow export", "Onboarding") and result["themes"][0]["label"] == "Onboarding"


def test_extra_insights_count_with_the_segments_weight_and_the_themes_average_severity():
    t = themes_by_id(fc.what_if(CELLS, WEIGHTS, LABELS, extra_insights=[{"theme_id": "T2", "segment_id": "free", "count": 10}]))
    # T2 raw: 0.5x12 + 1x3 = 9, plus 10 insights at the theme's average severity 3.0 and weight 0.5 = 15 -> 24 against T1's 28
    assert t["T2"]["after"]["business_impact"] == pytest.approx(85.7) and t["T2"]["after"]["frequency"] == 15 and t["T1"]["after"]["rank"] == 1
    explicit = themes_by_id(fc.what_if(CELLS, WEIGHTS, LABELS, extra_insights=[{"theme_id": "T2", "segment_id": "ent", "count": 2, "severity": 5}]))
    assert explicit["T2"]["after"]["business_impact"] == 100.0  # 9 + 2 x 5 x 3.0 = 39 beats 28


def test_extra_insights_for_a_theme_with_no_history_assume_a_middling_severity():
    t = themes_by_id(fc.what_if(CELLS, WEIGHTS, {**LABELS, "T3": "New"}, extra_insights=[{"theme_id": "T3", "segment_id": "ent", "count": 1}]))
    assert t["T3"]["before"]["frequency"] == 0 and t["T3"]["after"]["frequency"] == 1 and t["T3"]["after"]["business_impact"] == pytest.approx(9 / 28 * 100, abs=0.1)


def test_a_what_if_with_no_themes():
    assert fc.what_if({}, {}, {}, segment_weights={"x": 2}) == {"themes": [], "top_before": None, "top_after": None}


# ---------------------------------------------------------------- narrative guard

DATA = {"recent_weeks": [3, 4, 5], "trend": "rising", "weekly_change": 1.0, "forecast": [{"week": "2026-10-26", "value": 6.4, "range": [5.1, 7.7]}]}


@pytest.mark.parametrize("text,ok", [
    ("Weekly counts are rising by about 1 per week; next week may reach 6.4, between 5.1 and 7.7. This is an estimate.", True),
    ("It could reach 6 next week.", True),  # a rounded figure
    ("It is up 25% on last quarter.", False),
    ("Next week may reach 9.", False),
    ("No figures at all, just an estimate.", True),
    ("The week of 2026-10-26 looks higher.", True),  # dates in the data count as known
])
def test_a_narrative_may_only_use_figures_from_the_data(text, ok):
    assert nv.only_known_numbers(text, DATA) is ok


def reply(text):
    return Completion(json.dumps({"narrative": text}), "gemini", "flash-lite", 200, 60, 700)


def test_a_good_narrative_is_returned_tidied_and_a_made_up_figure_drops_it():
    assert nv.narrate(DATA, lambda m: reply("  Counts are rising   by 1 a week; this is an estimate. ")) == "Counts are rising by 1 a week; this is an estimate."
    assert nv.narrate(DATA, lambda m: reply("Counts will double, up 80%.")) is None


@pytest.mark.parametrize("text", ["not json", json.dumps({"narrative": ""}), json.dumps({"other": "x"}), json.dumps({"narrative": 5}), "[1]"])
def test_unusable_narratives_are_none(text):
    assert nv.narrate(DATA, lambda m: Completion(text, "g", "m", 1, 1, 1)) is None


def test_no_provider_means_no_narrative_not_an_error():
    def down(messages):
        raise AllProvidersFailed(["gemini: HTTP 429"])

    assert nv.narrate(DATA, down) is None


def test_the_prompt_demands_estimates_and_gives_the_data():
    seen = []
    nv.narrate(DATA, lambda m: seen.append(m) or reply("ok"))
    assert "ESTIMATE" in seen[0][0]["content"] and "ONLY numbers that appear in the JSON" in seen[0][0]["content"]
    assert json.loads(seen[0][1]["content"])["trend"] == "rising"


# ---------------------------------------------------------------- endpoints

@pytest.fixture
def world(monkeypatch):
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    monkeypatch.setattr(api, "today", lambda: datetime(2026, 10, 24, 10, tzinfo=timezone.utc))
    with TestClient(app) as client:
        with database.user_tx(who.id) as conn:
            ws = conn.execute("select create_workspace('Forecast test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            other = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'Other') returning id", (ws,)).fetchone()["id"]
            seg = {n: conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, %s, %s, %s) returning id", (cid, n, t, w)).fetchone()["id"]
                   for n, t, w in (("Enterprise", "enterprise", 3), ("Free", "free", 0.5))}
            foreign_segment = conn.execute("insert into segments (campaign_id, name, tier, weight) values (%s, 'Foreign', 'other', 1) returning id", (other,)).fetchone()["id"]
            t1 = conn.execute("insert into themes (campaign_id, label, color_code) values (%s, 'Slow export', '#000') returning id", (cid,)).fetchone()["id"]
            t2 = conn.execute("insert into themes (campaign_id, label, color_code) values (%s, 'Onboarding', '#111') returning id", (cid,)).fetchone()["id"]
            foreign_theme = conn.execute("insert into themes (campaign_id, label, color_code) values (%s, 'Foreign', '#222') returning id", (other,)).fetchone()["id"]

            def add(theme, segment, severity, when):
                conn.execute("insert into insights (campaign_id, theme_id, segment_id, summary_text, severity, created_at) values (%s, %s, %s, 'x', %s, %s)",
                             (cid, theme, segment, severity, when))

            for week_start, count in ((7, 1), (14, 2), (21, 3), (28, 4)):  # September Mondays
                for _ in range(count):
                    add(t1, seg["Enterprise"], 4, datetime(2026, 9, week_start, 12, tzinfo=timezone.utc))
            for day, count in ((5, 5), (12, 6)):  # October Mondays
                for _ in range(count):
                    add(t1, seg["Enterprise"], 4, datetime(2026, 10, day, 12, tzinfo=timezone.utc))
            add(t1, seg["Enterprise"], 4, datetime(2026, 10, 20, 12, tzinfo=timezone.utc))  # this week, not over yet
            add(t2, seg["Free"], 2, datetime(2026, 10, 8, 12, tzinfo=timezone.utc))
            add(t2, None, 3, datetime(2026, 10, 9, 12, tzinfo=timezone.utc))
        client.world = SimpleNamespace(who=who, campaign=str(cid), empty=str(other), seg={k: str(v) for k, v in seg.items()},
                                       foreign_segment=str(foreign_segment), t1=str(t1), t2=str(t2), foreign_theme=str(foreign_theme))
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


def scripted_reply(text):
    calls = []

    def llm(messages):
        calls.append(messages)
        return reply(text)

    llm.calls = calls
    return llm


@needs_db
def test_forecast_for_the_whole_campaign(world, monkeypatch):
    llm = scripted_reply("Pain points are rising by 1 a week and may reach 8 next week; this is an estimate.")
    monkeypatch.setattr(api, "call_llm", llm)
    r = world.post(f"/api/v1/campaigns/{world.world.campaign}/forecast", json={"horizon_weeks": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estimate"] is True and body["method"] == fc.METHOD and body["scope"] == {}
    weeks = {p["week"]: (p["value"], p["partial"]) for p in body["series"]}
    assert weeks["2026-09-07"] == (1, False) and weeks["2026-10-12"] == (6, False) and weeks["2026-10-19"] == (1, True)
    # complete weeks: 1,2,3,4,5,6 plus the 2 from theme two in the week of 5 October -> 1,2,3,4,7,6
    assert body["weeks_used"] == 6 and [p["week"] for p in body["forecast"]] == ["2026-10-19", "2026-10-26", "2026-11-02"]
    assert [p["value"] for p in body["series"] if not p["partial"]] == [1, 2, 3, 4, 7, 6]
    assert body["trend"] in ("rising", "flat", "falling") and all(p["lower"] <= p["value"] <= p["upper"] for p in body["forecast"])
    assert body["narrative"] is None or "estimate" in body["narrative"]  # shown only if every figure in it is in the data


@needs_db
def test_forecast_for_a_theme_is_exact_and_narrated_only_with_known_figures(world, monkeypatch):
    llm = scripted_reply("Slow export is rising by 1 a week and may reach 7 next week; this is an estimate.")
    monkeypatch.setattr(api, "call_llm", llm)
    r = world.post(f"/api/v1/campaigns/{world.world.campaign}/forecast", json={"theme_id": world.world.t1, "horizon_weeks": 3}).json()
    assert r["scope"] == {"theme": "Slow export"} and r["weeks_used"] == 6
    assert [p["value"] for p in r["forecast"]] == pytest.approx([7, 8, 9]) and r["trend"] == "rising"
    assert r["narrative"] == "Slow export is rising by 1 a week and may reach 7 next week; this is an estimate."
    facts = json.loads(llm.calls[0][1]["content"])
    assert facts["scope"] == {"theme": "Slow export"} and facts["recent_weeks"] == [1, 2, 3, 4, 5, 6]
    with database.user_tx(world.world.who.id) as conn:
        assert conn.execute("select count(*) as n from telemetry_logs where action_type = 'forecast_narrative'").fetchone()["n"] == 1

    monkeypatch.setattr(api, "call_llm", scripted_reply("It will grow 300% by Christmas."))
    assert world.post(f"/api/v1/campaigns/{world.world.campaign}/forecast", json={"theme_id": world.world.t1}).json()["narrative"] is None


@needs_db
def test_forecast_of_business_impact_weights_by_segment(world, monkeypatch):
    monkeypatch.setattr(api, "call_llm", scripted_reply("unused"))
    r = world.post(f"/api/v1/campaigns/{world.world.campaign}/forecast", json={"metric": "impact", "theme_id": world.world.t1, "narrative": False}).json()
    weeks = {p["week"]: p["value"] for p in r["series"]}
    assert weeks["2026-09-07"] == 12.0 and weeks["2026-10-12"] == 72.0  # 3 (weight) x 4 (severity) x count
    assert r["narrative"] is None


@needs_db
def test_not_enough_history_is_said_plainly(world, monkeypatch):
    monkeypatch.setattr(api, "call_llm", scripted_reply("unused"))
    r = world.post(f"/api/v1/campaigns/{world.world.campaign}/forecast", json={"theme_id": world.world.t2}).json()
    assert r["forecast"] is None and "at least 4 complete weeks" in r["note"] and r["narrative"] is None and r["estimate"] is True
    empty = world.post(f"/api/v1/campaigns/{world.world.empty}/forecast", json={}).json()
    assert empty["series"] == [] and empty["forecast"] is None


@needs_db
def test_forecast_input_checks(world):
    path = f"/api/v1/campaigns/{world.world.campaign}/forecast"
    assert world.post(path, json={"theme_id": world.world.foreign_theme}).status_code == 422
    assert world.post(path, json={"segment_id": world.world.foreign_segment}).status_code == 422
    for bad in ({"horizon_weeks": 0}, {"horizon_weeks": 13}, {"metric": "revenue"}):
        assert world.post(path, json=bad).status_code == 422


@needs_db
def test_scenario_changing_segment_weights(world, monkeypatch):
    w = world.world
    llm = scripted_reply("Giving Free customers more weight makes this an estimate worth checking.")
    monkeypatch.setattr(api, "call_llm", llm)
    r = world.post(f"/api/v1/campaigns/{w.campaign}/scenario", json={"segment_weights": {w.seg["Free"]: 20}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estimate"] is True and body["assumptions"]["segment_weights"] == [{"segment": "Free", "from": 0.5, "to": 20.0}]
    themes = {t["label"]: t for t in body["themes"]}
    assert themes["Slow export"]["before"]["rank"] == 1 and themes["Onboarding"]["before"]["rank"] == 2
    # Slow export: 22 Enterprise insights x weight 3 x severity 4 = 264. Onboarding before: 0.5 x 2 + 1 x 3 = 4; after: 20 x 2 + 3 = 43.
    assert themes["Slow export"]["after"]["business_impact"] == 100.0 and themes["Onboarding"]["before"]["business_impact"] == pytest.approx(1.5)
    assert themes["Onboarding"]["after"]["business_impact"] == pytest.approx(16.3) and themes["Onboarding"]["after"]["rank"] == 2
    assert body["narrative"] == "Giving Free customers more weight makes this an estimate worth checking."  # no figures, so it passes the guard


@needs_db
def test_scenario_adding_insights_can_overtake_the_leader(world, monkeypatch):
    w = world.world
    monkeypatch.setattr(api, "call_llm", scripted_reply("unused"))
    r = world.post(f"/api/v1/campaigns/{w.campaign}/scenario", json={
        "extra_insights": [{"theme_id": w.t2, "segment_id": w.seg["Enterprise"], "count": 30, "severity": 5}], "narrative": False}).json()
    assert (r["top_before"], r["top_after"]) == ("Slow export", "Onboarding")
    assert r["assumptions"]["extra_insights"] == [{"theme": "Onboarding", "segment": "Enterprise", "count": 30}]
    top = r["themes"][0]
    assert top["label"] == "Onboarding" and top["rank_change"] == 1 and top["after"]["frequency"] == top["before"]["frequency"] + 30


@needs_db
def test_scenario_input_checks(world):
    w = world.world
    path = f"/api/v1/campaigns/{w.campaign}/scenario"
    assert world.post(path, json={}).status_code == 422
    assert world.post(path, json={"segment_weights": {w.foreign_segment: 2}}).status_code == 422
    assert world.post(path, json={"segment_weights": {str(uuid4()): 2}}).status_code == 422
    assert world.post(path, json={"segment_weights": {w.seg["Free"]: 0}}).status_code == 422
    assert world.post(path, json={"segment_weights": {w.seg["Free"]: 99}}).status_code == 422
    assert world.post(path, json={"extra_insights": [{"theme_id": w.foreign_theme, "count": 1}]}).status_code == 422
    assert world.post(path, json={"extra_insights": [{"theme_id": w.t1, "count": 0}]}).status_code == 422
    assert world.post(path, json={"extra_insights": [{"theme_id": w.t1, "count": 1, "severity": 6}]}).status_code == 422
    assert world.post(path, json={"extra_insights": [{"theme_id": w.t1, "segment_id": w.foreign_segment, "count": 1}]}).status_code == 422


@needs_db
def test_other_users_get_404(world):
    w = world.world
    w.who.id = uuid4()
    assert world.post(f"/api/v1/campaigns/{w.campaign}/forecast", json={}).status_code == 404
    assert world.post(f"/api/v1/campaigns/{w.campaign}/scenario", json={"segment_weights": {w.seg["Free"]: 2}}).status_code == 404
