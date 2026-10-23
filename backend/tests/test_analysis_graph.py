"""The analysis graph against a real Neon database, with the LLM and embeddings faked.

Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set. Test workspaces are deleted afterwards.
"""

import json
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from pgvector import Vector

from ai_pipeline.analysis.graph import build_graph, run_analysis
from ai_pipeline.analysis.state import Deps
from ai_pipeline.analysis.trace import DbTrace
from ai_pipeline.providers import AllProvidersFailed, Completion
from app.core import database
from app.core.config import get_settings
from app.ingestion.chunking import chunk_text

settings = get_settings()
pytestmark = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)

UNIT = [1.0] + [0.0] * 767

INTERVIEW = (
    "Interviewer: How do you handle reporting?\n"
    "Maya: Every month I export four CSV files and stitch them together in a spreadsheet, which takes me most of a "
    "day. The export also times out whenever an account has more than ten thousand rows.\n"
    "Maya: Otherwise the team is great and the new layout looks nice."
) * 1
MALAY = (
    "Aisyah: Fungsi eksport sering gagal apabila akaun mempunyai lebih sepuluh ribu baris. "
    "Pekerja baharu sukar belajar kerana tiada satu tempat yang menerangkan semua metrik kami."
)
PRAISE = "Farid: Support team pun responsive, everything works fine for us. Love the new layout, very clean design."


def item(quote, summary, **kw):
    return {"kind": "pain_point", "pain_point": summary, "quote": quote, "use_case": "monthly reporting",
            "severity": 4, "sentiment": "negative", **kw}


REPLIES = {
    "export four CSV": {"items": [
        item("Every month I export four CSV files and stitch them together in a spreadsheet", "Monthly reports need manual CSV merging"),
        item("The export also times out whenever an account has more than ten thousand rows", "Export times out on large accounts"),
        item("Nobody at the company ever replies to my emails about this", "Invented quote that is not in the text"),
    ]},
    "Fungsi eksport": {"items": [
        item("Fungsi eksport sering gagal apabila akaun mempunyai lebih sepuluh ribu baris", "Export fails on large accounts"),
        item("pekerja baharu sukar belajar kerana tiada satu tempat", "New staff struggle to learn the metrics", kind="feature_request", severity=3),
    ]},
    "Support team": {"items": []},
}


class FakeLlm:
    def __init__(self, fail_on=()):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, messages, language):
        text = messages[-1]["content"]
        self.calls.append(language)
        for needle in self.fail_on:
            if needle in text:
                raise AllProvidersFailed(["gemini: HTTP 429", "groq-fast: HTTP 503"])
        for needle, reply in REPLIES.items():
            if needle in text:
                return Completion(json.dumps(reply), "gemini", "flash-lite", 400, 120, 1100, failed_before=["groq-fast: HTTP 429"])
        raise AssertionError("unexpected text")


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, node, status, **details):
        self.events.append((node, status, details))

    def statuses(self, node):
        return [s for n, s, _ in self.events if n == node]


def deps(llm=None, embed=None):
    rec = Recorder()
    return Deps(llm=llm or FakeLlm(), embed=embed or (lambda texts: [UNIT for _ in texts]), trace=rec), rec


@pytest.fixture
def world():
    database.init_pool()
    user = uuid4()
    with database.user_tx(user) as conn:  # committed before the test runs
        ws = conn.execute("select create_workspace('Graph test', 'Acme', 'SaaS') as id").fetchone()["id"]
        cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
        seg = conn.execute(
            "insert into segments (campaign_id, name, tier, weight) values (%s, 'Enterprise', 'enterprise', 3) returning id", (cid,)
        ).fetchone()["id"]

    def resource(text, status="approved", language="en", segment=None, analyzed=False):
        with database.user_tx(user) as conn:
            rid = conn.execute(
                """insert into resources (campaign_id, title, source_type, content, content_hash, status, language,
                                          segment_id, analyzed_at)
                   values (%s, 't', 'transcript', %s, %s, %s, %s, %s, case when %s then now() end) returning id""",
                (cid, text, uuid4().hex, status, language, segment, analyzed),
            ).fetchone()["id"]
            for c in chunk_text(text, size=240, overlap=120):  # overlap longer than a quote, as in production
                conn.execute(
                    "insert into resource_chunks (resource_id, chunk_index, content, start_offset, end_offset, embedding) "
                    "values (%s, %s, %s, %s, %s, %s)", (rid, c.index, c.content, c.start, c.end, Vector(UNIT)),
                )
        return str(rid)

    yield SimpleNamespace(user=user, campaign=str(cid), segment=seg, resource=resource)
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))
    database.close_pool()


def q(user, sql, *params):
    with database.user_tx(user) as conn:
        return conn.execute(sql, params).fetchall()


def test_full_run_stores_insights_with_exact_citations(world):
    rid = world.resource(INTERVIEW, segment=world.segment)
    d, rec = deps()
    state = run_analysis(world.user, world.campaign, deps=d)

    assert state["resource_ids"] == [rid] and state["errors"] == []
    rows = q(world.user, "select i.*, c.start_offset s, c.end_offset e, c.text_snippet, c.chunk_id from insights i "
                         "join citations c on c.insight_id = i.id order by c.start_offset")
    assert [r["summary_text"] for r in rows] == ["Monthly reports need manual CSV merging", "Export times out on large accounts"]
    for r in rows:  # the citation points at the exact words in the stored text
        assert INTERVIEW[r["s"] : r["e"]] == r["text_snippet"]
        assert r["segment_id"] == world.segment and r["kind"] == "pain_point" and r["severity"] == 4
        assert r["chunk_id"] is not None and float(r["confidence_score"]) == 1.0
        assert len(r["embedding"].to_list()) == 768
    chunk = q(world.user, "select start_offset, end_offset from resource_chunks where id = %s", rows[0]["chunk_id"])[0]
    assert chunk["start_offset"] <= rows[0]["s"] and rows[0]["e"] <= chunk["end_offset"]  # the whole quote is in that chunk
    assert q(world.user, "select analyzed_at from resources where id = %s", rid)[0]["analyzed_at"] is not None


def test_invented_quotes_never_become_insights(world):
    world.resource(INTERVIEW)
    run_analysis(world.user, world.campaign, deps=deps()[0])
    summaries = [r["summary_text"] for r in q(world.user, "select summary_text from insights")]
    assert "Invented quote that is not in the text" not in summaries and len(summaries) == 2


def test_loosely_copied_quotes_are_matched_with_lower_confidence(world):
    world.resource(MALAY, language="id")
    run_analysis(world.user, world.campaign, deps=deps()[0])
    rows = q(world.user, "select i.summary_text, i.kind, i.confidence_score, c.text_snippet from insights i "
                         "join citations c on c.insight_id = i.id order by c.start_offset")
    assert [float(r["confidence_score"]) for r in rows] == [1.0, 0.9]  # second quote differed in case
    assert rows[1]["kind"] == "feature_request" and rows[1]["text_snippet"] in MALAY  # stored text is the source's own


def test_language_reaches_the_provider_chain(world):
    world.resource(MALAY, language="id")
    llm = FakeLlm()
    run_analysis(world.user, world.campaign, deps=deps(llm)[0])
    assert llm.calls == ["id"]


def test_selection_skips_staged_analysed_and_other_campaigns_resources(world):
    wanted = world.resource(INTERVIEW)
    world.resource(MALAY, status="staged")
    world.resource(PRAISE, analyzed=True)
    state = run_analysis(world.user, world.campaign, deps=deps()[0])
    assert state["resource_ids"] == [wanted]


def test_only_resources_restricts_the_run(world):
    first, second = world.resource(INTERVIEW), world.resource(MALAY, language="id")
    state = run_analysis(world.user, world.campaign, resource_ids=[second], deps=deps()[0])
    assert state["resource_ids"] == [second]
    assert q(world.user, "select analyzed_at from resources where id = %s", first)[0]["analyzed_at"] is None


def test_nothing_to_analyse_stops_before_extraction(world):
    d, rec = deps()
    state = run_analysis(world.user, world.campaign, deps=d)
    assert state["resource_ids"] == [] and rec.statuses("extract") == [] and rec.statuses("embed") == []


def test_a_resource_with_no_pain_points_is_still_marked_analysed(world):
    rid = world.resource(PRAISE)
    state = run_analysis(world.user, world.campaign, deps=deps()[0])
    assert state["items"] == [] and state["insight_ids"] == []
    assert q(world.user, "select analyzed_at from resources where id = %s", rid)[0]["analyzed_at"] is not None


def test_a_failing_resource_is_skipped_and_picked_up_by_the_next_run(world):
    good, bad = world.resource(INTERVIEW), world.resource(MALAY, language="id")
    state = run_analysis(world.user, world.campaign, deps=deps(FakeLlm(fail_on=("Fungsi eksport",)))[0])
    assert [e["resource_id"] for e in state["errors"]] == [bad] and state["errors"][0]["stage"] == "extract"
    assert "HTTP 429" in state["errors"][0]["error"]
    done = {str(r["id"]): r["analyzed_at"] is not None for r in q(world.user, "select id, analyzed_at from resources")}
    assert done == {good: True, bad: False}

    again = run_analysis(world.user, world.campaign, deps=deps()[0])  # providers recovered
    assert again["resource_ids"] == [bad] and again["errors"] == []
    assert q(world.user, "select count(*) as n from resources where analyzed_at is null")[0]["n"] == 0


def test_an_embedding_failure_stores_nothing_for_that_resource(world):
    rid = world.resource(INTERVIEW)

    def broken(_texts):
        raise RuntimeError("embedding quota")

    state = run_analysis(world.user, world.campaign, deps=deps(embed=broken)[0])
    assert state["errors"][0]["stage"] == "embed"
    assert q(world.user, "select count(*) as n from insights")[0]["n"] == 0
    assert q(world.user, "select count(*) as n from citations")[0]["n"] == 0
    assert q(world.user, "select analyzed_at from resources where id = %s", rid)[0]["analyzed_at"] is None


def test_every_llm_call_is_recorded_in_telemetry(world):
    world.resource(INTERVIEW)
    run_analysis(world.user, world.campaign, deps=deps()[0])
    row = q(world.user, "select * from telemetry_logs")[0]
    assert row["model_used"] == "gemini:flash-lite" and row["tokens_processed"] == 520
    assert row["action_type"] == "extraction" and row["fallback_from"] == "groq-fast: HTTP 429"


def test_trace_reports_each_node_and_each_llm_call(world):
    world.resource(INTERVIEW)
    d, rec = deps()
    run_analysis(world.user, world.campaign, deps=d)
    assert rec.statuses("select") == ["running", "done"] and rec.statuses("embed") == ["running", "done"]
    assert rec.statuses("extract") == ["running", "done", "done"]  # started, one LLM call, finished
    call = next(details for n, s, details in rec.events if n == "extract" and details.get("model_used"))
    assert call["model_used"] == "gemini:flash-lite" and call["tokens"] == 520 and "TEXT:" in call["prompt"]


def test_db_trace_persists_events_for_the_laboratory(world):
    world.resource(INTERVIEW)
    d, _ = deps()
    run_id = str(uuid4())
    d.trace = DbTrace(world.user, world.campaign, run_id)
    run_analysis(world.user, world.campaign, deps=d, run_id=run_id)
    rows = q(world.user, "select node, status, model_used, tokens, prompt from agent_runs where run_id = %s order by created_at", run_id)
    assert [(r["node"], r["status"]) for r in rows] == [
        ("select", "running"), ("select", "done"), ("extract", "running"), ("extract", "done"),
        ("extract", "done"), ("embed", "running"), ("embed", "done"),
    ]
    call = next(r for r in rows if r["model_used"])
    assert call["tokens"] == 520 and call["prompt"].startswith("TEXT:")


def test_another_user_cannot_analyse_the_campaign(world):
    world.resource(INTERVIEW)
    state = run_analysis(uuid4(), world.campaign, deps=deps()[0])
    assert state["resource_ids"] == []
    assert q(world.user, "select count(*) as n from insights")[0]["n"] == 0


def test_a_second_run_finds_nothing_new(world):
    world.resource(INTERVIEW)
    run_analysis(world.user, world.campaign, deps=deps()[0])
    assert run_analysis(world.user, world.campaign, deps=deps()[0])["resource_ids"] == []


def test_chunk_choice_prefers_a_chunk_holding_the_whole_quote_then_the_one_covering_most_of_it():
    from ai_pipeline.analysis.nodes import _chunk_for

    chunks = [
        {"id": "a", "start_offset": 0, "end_offset": 100},
        {"id": "b", "start_offset": 80, "end_offset": 180},
        {"id": "c", "start_offset": 160, "end_offset": 260},
    ]
    assert _chunk_for(chunks, 85, 150) == "b"  # b holds all of it, a does not
    assert _chunk_for(chunks, 10, 60) == "a"
    assert _chunk_for(chunks, 90, 190) == "b"  # nothing holds it all: b covers 90 of its 100 characters, a only 10
    assert _chunk_for(chunks, 300, 320) is None
    assert _chunk_for([], 0, 10) is None
