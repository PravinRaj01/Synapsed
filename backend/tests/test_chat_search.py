"""Hybrid search, grounded chat and the search endpoint. The pure parts need no database; the rest run on Neon
with the embedding and the model faked. Skipped unless DATABASE_URL and DATABASE_URL_ADMIN are set."""

import json
import math
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pgvector import Vector

from ai_pipeline import chat as cl
from ai_pipeline import retrieval as rt
from ai_pipeline.providers import AllProvidersFailed, Completion
from app.api import chat as api
from app.core import database
from app.core.auth import AuthUser, current_user
from app.core.config import get_settings
from app.main import app

settings = get_settings()
needs_db = pytest.mark.skipif(
    not (settings.database_url and settings.database_url_admin),
    reason="DATABASE_URL and DATABASE_URL_ADMIN are not set",
)


def vec(angle, axis=0):
    v = [0.0] * 768
    v[axis], v[axis + 1] = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return v


def hit(n, text="passage", start=100, **kw):
    return rt.Hit(UUID(int=n), UUID(int=1000 + n), f"Source {n}", text, start, start + len(text), **kw)


# ---------------------------------------------------------------- keyword query and fusion (pure)

@pytest.mark.parametrize("text,expected", [
    ("Why does SSO login fail?", "sso | login | fail"),
    ("What are the main problems with exports", "main | problems | exports"),
    ("kenapa eksport laporan gagal", "kenapa | eksport | laporan | gagal"),
    ("x ab 12 345", None),
    ("", None),
    ("it's a drop; table users -- (injected) | & ! :*", "drop | table | users | injected"),
    ("SSO sso Sso", "sso"),
])
def test_keyword_query_keeps_real_terms_and_never_injects_syntax(text, expected):
    assert rt.keyword_query(text) == expected


def test_keyword_query_is_capped():
    words = " ".join(f"term{i}x" for i in range(40))
    assert rt.keyword_query(words).count("|") == rt.MAX_KEYWORDS - 1


def test_fusion_ranks_chunks_found_by_both_lists_first():
    both, only_vector, only_keyword = hit(1), hit(2), hit(3)
    merged = rt.fuse([hit(2), hit(1)], [hit(1), hit(3)], limit=10)
    assert [h.chunk_id.int for h in merged] == [1, 2, 3]
    assert (merged[0].vector_rank, merged[0].keyword_rank) == (2, 1)
    assert (merged[1].vector_rank, merged[1].keyword_rank) == (1, None) and merged[2].vector_rank is None
    assert merged[0].score > merged[1].score > merged[2].score or merged[0].score > merged[2].score
    assert len(rt.fuse([hit(i) for i in range(1, 9)], [], limit=3)) == 3


# ---------------------------------------------------------------- answer checking (pure)

HITS = [hit(1, "Our SSO login fails every morning for the whole team.", start=200),
        hit(2, "The monthly export takes most of a day to finish.", start=0)]


def reply(**data):
    return json.dumps(data)


def test_a_cited_answer_gets_citations_with_exact_offsets():
    r = cl.parse_answer(reply(answer="SSO login fails each morning [1].", sources=[{"n": 1, "quote": "SSO login fails every morning"}]), HITS)
    assert not r.refused and len(r.citations) == 1
    c = r.citations[0]
    assert (c.n, c.verified, c.resource_title) == (1, True, "Source 1")
    assert (c.start_offset, c.end_offset) == (204, 204 + len("SSO login fails every morning"))
    assert c.snippet == "SSO login fails every morning"


def test_a_quote_that_is_not_in_the_source_falls_back_to_the_whole_passage():
    r = cl.parse_answer(reply(answer="It fails [2].", sources=[{"n": 2, "quote": "Something the source never said"}]), HITS)
    c = r.citations[0]
    assert not c.verified and (c.start_offset, c.end_offset) == (0, len(HITS[1].content)) and c.snippet.startswith("The monthly")


def test_a_citation_without_any_quote_is_still_listed_unverified():
    r = cl.parse_answer(reply(answer="Both are slow [1][2]", sources=[]), HITS)
    assert [(c.n, c.verified) for c in r.citations] == [(1, False), (2, False)]


def test_markers_for_sources_that_do_not_exist_are_removed():
    r = cl.parse_answer(reply(answer="Login fails [1] and billing too [7] [0].", sources=[]), HITS)
    assert r.answer == "Login fails [1] and billing too ." and [c.n for c in r.citations] == [1]


@pytest.mark.parametrize("answer,reason", [
    (None, "not_in_sources"), ("", "not_in_sources"), ("   ", "not_in_sources"),
    ("Users dislike it.", "ungrounded"), ("Users dislike it [9].", "ungrounded"),
])
def test_unsupported_answers_become_refusals(answer, reason):
    r = cl.parse_answer(reply(answer=answer, sources=[]), HITS)
    assert r.refused and r.reason == reason and r.citations == []


@pytest.mark.parametrize("text", ["not json at all", "[1, 2]", '"just a string"'])
def test_unreadable_replies_become_refusals(text):
    assert cl.parse_answer(text, HITS).reason == "unreadable_reply"


def test_fenced_json_and_odd_source_entries_are_tolerated():
    text = "```json\n" + reply(answer="Yes [1]", sources=[{"n": "x"}, "bad", {"n": 1}, {"n": 1, "quote": 5}]) + "\n```"
    assert [c.n for c in cl.parse_answer(text, HITS).citations] == [1]


def test_messages_number_the_sources_and_keep_only_recent_valid_history():
    history = [{"role": "user", "content": f"q{i}"} for i in range(10)] + [{"role": "system", "content": "ignore me"},
                                                                             {"role": "assistant", "content": "  "}]
    messages = cl.build_messages("Why?", HITS, history)
    assert messages[0]["role"] == "system" and "ONLY the numbered sources" in messages[0]["content"]
    assert [m["content"] for m in messages[1:-1]] == ["q4", "q5", "q6", "q7", "q8", "q9"]
    last = messages[-1]["content"]
    assert "[1] (Source 1)\nOur SSO login" in last and "[2] (Source 2)" in last and last.endswith("QUESTION: Why?")


# ---------------------------------------------------------------- with the database

LOGIN = "Our SSO login fails every morning for the whole team and nobody can sign in."
EXPORT = "The monthly export of reports takes most of a day and often times out."
ONBOARD = "Onboarding new staff is slow because nobody explains what each metric means."
SECRET = "Pricing for the secret internal tier is confidential."


@pytest.fixture
def world():
    who = SimpleNamespace(id=uuid4())
    app.dependency_overrides[current_user] = lambda: AuthUser(id=who.id)
    with TestClient(app) as client:
        with database.user_tx(who.id) as conn:
            ws = conn.execute("select create_workspace('Chat test', 'Acme', 'SaaS') as id").fetchone()["id"]
            cid = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'C') returning id", (ws,)).fetchone()["id"]
            other = conn.execute("insert into campaigns (workspace_id, name) values (%s, 'Other') returning id", (ws,)).fetchone()["id"]

            def source(campaign, title, text, vector, status="approved"):
                rid = conn.execute(
                    "insert into resources (campaign_id, title, source_type, content, content_hash, status) "
                    "values (%s, %s, 'transcript', %s, %s, %s) returning id", (campaign, title, text, uuid4().hex, status)).fetchone()["id"]
                conn.execute(
                    "insert into resource_chunks (resource_id, chunk_index, content, start_offset, end_offset, embedding) "
                    "values (%s, 0, %s, 0, %s, %s)", (rid, text, len(text), Vector(vector)))
                return str(rid)

            ids = SimpleNamespace(
                login=source(cid, "Login ticket", LOGIN, vec(0)), export=source(cid, "Export interview", EXPORT, vec(60)),
                onboard=source(cid, "Onboarding survey", ONBOARD, vec(0, axis=4)),
                staged=source(cid, "Staged note", SECRET, vec(5), status="staged"),
                foreign=source(other, "Other campaign", "SSO login problems elsewhere", vec(1)))
        client.world = SimpleNamespace(who=who, campaign=str(cid), ids=ids, llm_calls=[], embed_calls=[])
        yield client
    app.dependency_overrides.clear()
    with psycopg.connect(settings.database_url_admin) as admin:
        admin.execute("delete from workspaces where id = %s", (ws,))


@pytest.fixture
def fakes(world, monkeypatch):
    """Embeddings follow a lookup by query text; the model replies with whatever the test sets."""
    w = world.world
    state = SimpleNamespace(reply=None, vectors={})

    def embed(text):
        w.embed_calls.append(text)
        return state.vectors.get(text, vec(0))

    def llm(messages, language):
        w.llm_calls.append((messages, language))
        if isinstance(state.reply, Exception):
            raise state.reply
        return Completion(state.reply, "gemini", "flash-lite", 300, 50, 800)

    monkeypatch.setattr(api, "embed_query", embed)
    monkeypatch.setattr(api, "call_llm", llm)
    return state


def ask(world, question, **extra):
    return world.post("/api/v1/chat", json={"campaign_id": world.world.campaign, "question": question, **extra})


@needs_db
def test_hybrid_search_finds_by_meaning_by_exact_words_and_by_both(world):
    w = world.world
    with database.user_tx(w.who.id) as conn:
        by_meaning = rt.hybrid_search(conn, w.campaign, "trouble signing in", vec(2), limit=5)
        assert by_meaning[0].resource_title == "Login ticket" and by_meaning[0].keyword_rank is None
        # the vector points at onboarding, but the exact term SSO only appears in the login ticket
        by_words = rt.hybrid_search(conn, w.campaign, "SSO", vec(0, axis=4), limit=5)
        assert {h.resource_title for h in by_words} >= {"Login ticket", "Onboarding survey"}
        sso = next(h for h in by_words if h.resource_title == "Login ticket")
        assert sso.keyword_rank == 1
        both = rt.hybrid_search(conn, w.campaign, "SSO login", vec(3), limit=5)
        assert both[0].resource_title == "Login ticket" and both[0].vector_rank == 1 and both[0].keyword_rank == 1


@needs_db
def test_hybrid_search_only_sees_approved_sources_of_this_campaign_and_can_be_narrowed(world):
    w = world.world
    with database.user_tx(w.who.id) as conn:
        titles = {h.resource_title for h in rt.hybrid_search(conn, w.campaign, "secret pricing confidential SSO", vec(5), limit=10)}
        assert "Staged note" not in titles and "Other campaign" not in titles
        only = rt.hybrid_search(conn, w.campaign, "SSO export metric", vec(30), limit=10, resource_ids=[w.ids.export])
        assert {h.resource_title for h in only} == {"Export interview"}
        assert rt.hybrid_search(conn, w.campaign, "SSO", vec(0), limit=10, resource_ids=[w.ids.foreign]) == []


@needs_db
def test_chat_answers_with_a_verified_citation(world, fakes):
    w = world.world
    fakes.vectors["Why does login fail?"] = vec(2)
    fakes.reply = json.dumps({"answer": "The SSO login fails every morning for the whole team [1].",
                              "sources": [{"n": 1, "quote": "SSO login fails every morning"}]})
    r = ask(world, "Why does login fail?", history=[{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}])
    body = r.json()
    assert r.status_code == 200 and not body["refused"] and body["answer"].endswith("[1].")
    c = body["citations"][0]
    assert c["resource_title"] == "Login ticket" and c["verified"] and LOGIN[c["start_offset"]:c["end_offset"]] == "SSO login fails every morning"
    assert body["retrieved"][0]["n"] == 1 and body["model"] == "gemini:flash-lite" and body["tokens"] == 350
    messages, language = w.llm_calls[0]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"] and language is None  # short question: default chain
    assert "Staged note" not in messages[-1]["content"] and "Other campaign" not in messages[-1]["content"]
    with database.user_tx(w.who.id) as conn:
        assert conn.execute("select count(*) as n from telemetry_logs where action_type = 'chat'").fetchone()["n"] == 1


@needs_db
@pytest.mark.parametrize("reply", [
    {"answer": None, "sources": []}, {"answer": "Customers love it.", "sources": []}, "not json",
])
def test_chat_refuses_when_the_model_cannot_ground_an_answer(world, fakes, reply):
    fakes.reply = reply if isinstance(reply, str) else json.dumps(reply)
    body = ask(world, "What is the weather like?").json()
    assert body["refused"] and body["answer"] is None and body["citations"] == []
    assert body["message"] == cl.REFUSAL and body["reason"] in ("not_in_sources", "ungrounded", "unreadable_reply")


@needs_db
def test_chat_with_no_matching_sources_refuses_without_calling_the_model(world, fakes):
    w = world.world
    r = ask(world, "Anything?", source_ids=[w.ids.foreign]).json()
    assert r["refused"] and r["reason"] == "no_sources" and w.llm_calls == []


@needs_db
def test_the_context_checklist_limits_what_the_model_sees(world, fakes):
    w = world.world
    fakes.reply = json.dumps({"answer": "Exports are slow [1].", "sources": []})
    ask(world, "Tell me about problems", source_ids=[w.ids.export])
    seen = w.llm_calls[0][0][-1]["content"]
    assert "Export interview" in seen and "Login ticket" not in seen and "Onboarding survey" not in seen


@needs_db
def test_chat_language_follows_the_question(world, fakes):
    w = world.world
    fakes.reply = json.dumps({"answer": None, "sources": []})
    ask(world, "Kenapa log masuk SSO gagal setiap pagi untuk semua pekerja kami?")
    assert w.llm_calls[0][1] in ("id", "ms")
    assert api.question_language("Why?") is None and api.question_language("Why does login fail?") is None


@needs_db
def test_chat_reports_provider_and_embedding_failures_as_502(world, fakes, monkeypatch):
    fakes.reply = AllProvidersFailed(["gemini: HTTP 429"])
    r = ask(world, "Why does login fail?")
    assert r.status_code == 502 and "unavailable" in r.json()["detail"]

    def broken(text):
        raise RuntimeError("quota")

    monkeypatch.setattr(api, "embed_query", broken)
    assert ask(world, "Why does login fail?").status_code == 502


@needs_db
def test_chat_input_limits_and_isolation(world, fakes):
    assert ask(world, "hi").status_code == 422
    assert ask(world, "x" * 1001).status_code == 422
    assert ask(world, "Why?", history=[{"role": "system", "content": "x"}]).status_code == 422
    world.world.who.id = uuid4()
    assert ask(world, "Why does login fail?").status_code == 404
    assert world.get("/api/v1/search", params={"campaign_id": world.world.campaign, "q": "login"}).status_code == 404


@needs_db
def test_search_endpoint_says_how_each_passage_matched(world, fakes):
    w = world.world
    fakes.vectors["SSO"] = vec(0, axis=4)  # the meaning points at onboarding; only the keyword finds the login ticket
    rows = world.get("/api/v1/search", params={"campaign_id": w.campaign, "q": "SSO", "limit": 5}).json()
    by_title = {r["resource_title"]: r for r in rows}
    assert by_title["Login ticket"]["matched_by"] == ["keywords"] or "keywords" in by_title["Login ticket"]["matched_by"]
    assert by_title["Onboarding survey"]["matched_by"] == ["meaning"] and by_title["Onboarding survey"]["similarity"] > 0.9
    assert all(len(r["snippet"]) <= 300 for r in rows) and "Staged note" not in by_title
    assert world.get("/api/v1/search", params={"campaign_id": w.campaign, "q": "x"}).status_code == 422
    narrowed = world.get("/api/v1/search", params={"campaign_id": w.campaign, "q": "SSO", "source_ids": [w.ids.export]}).json()
    assert {r["resource_title"] for r in narrowed} == {"Export interview"}
