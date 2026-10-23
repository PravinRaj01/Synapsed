import math
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from ai_pipeline import embedder
from app.ingestion import web


def fake_client(calls, fail_first=0, code=429):
    state = {"failures": fail_first}

    def embed_content(model, contents, config):
        calls.append({"model": model, "n": len(contents), "dims": config.output_dimensionality,
                      "task": config.task_type})
        if state["failures"] > 0:
            state["failures"] -= 1
            raise errors.APIError(code, {"error": {"message": "slow down"}})
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[3.0, 4.0] + [0.0] * 766) for _ in contents])

    return SimpleNamespace(models=SimpleNamespace(embed_content=embed_content))


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(embedder._embed_batch.retry, "sleep", lambda _s: None)


def test_normalize_gives_unit_length():
    v = embedder.normalize([3.0, 4.0])
    assert math.isclose(sum(x * x for x in v), 1.0) and v == [0.6, 0.8]
    assert embedder.normalize([0.0, 0.0]) == [0.0, 0.0]


def test_embeds_in_batches_at_768_dims(monkeypatch):
    calls = []
    monkeypatch.setattr(embedder, "_client", lambda: fake_client(calls))
    vectors = embedder.embed_texts(["t"] * 120)
    assert len(vectors) == 120 and all(len(v) == 768 for v in vectors)
    assert [c["n"] for c in calls] == [50, 50, 20]
    assert {c["dims"] for c in calls} == {768} and {c["task"] for c in calls} == {"RETRIEVAL_DOCUMENT"}
    assert math.isclose(sum(x * x for x in vectors[0]), 1.0)


def test_retries_rate_limits_then_succeeds(monkeypatch):
    calls = []
    client = fake_client(calls, fail_first=2, code=429)  # one client, so its failure count persists
    monkeypatch.setattr(embedder, "_client", lambda: client)
    assert len(embedder.embed_texts(["hello"])) == 1
    assert len(calls) == 3


def test_does_not_retry_client_errors(monkeypatch):
    calls = []
    client = fake_client(calls, fail_first=5, code=400)
    monkeypatch.setattr(embedder, "_client", lambda: client)
    with pytest.raises(errors.APIError):
        embedder.embed_texts(["hello"])
    assert len(calls) == 1


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin", "http://localhost:8000", "http://192.168.1.10/", "http://10.0.0.5/",
    "http://169.254.169.254/latest/meta-data", "http://[::1]/", "ftp://8.8.8.8/", "file:///etc/passwd",
    "not a url", "http:///nohost",
])
def test_private_and_odd_urls_are_rejected(url):
    assert web.is_public_url(url) is False


def test_public_ip_is_allowed():
    assert web.is_public_url("https://8.8.8.8/") is True


ARTICLE = "<html><head><title>{title}</title></head><body><article>{body}</article></body></html>"
BODY = "".join(
    f"<p>Paragraph {i}: product teams collect interviews, tickets and survey answers, then struggle to "
    "turn the scattered notes into evidence they can use when planning the roadmap.</p>" for i in range(6)
)


REAL_CLIENT = httpx.Client  # captured once, so patching twice in one test does not nest


def patch_http(monkeypatch, handler):
    monkeypatch.setattr(web.httpx, "Client", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(web, "is_public_url", lambda url: "internal" not in url)


def html_response(title, body):
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=ARTICLE.format(title=title, body=body))


def test_fetch_page_extracts_a_real_article(monkeypatch):
    patch_http(monkeypatch, lambda req: html_response("Synthesizing interviews", BODY))
    page = web.fetch_page("https://example.org/post")
    assert page and page.title == "Synthesizing interviews" and "roadmap" in page.text


def test_fetch_page_skips_bot_challenge_and_error_pages(monkeypatch):
    patch_http(monkeypatch, lambda req: html_response("One moment, please...", "<p>Checking your browser</p>"))
    assert web.fetch_page("https://example.org/a") is None
    patch_http(monkeypatch, lambda req: html_response("Just a moment...", BODY))  # long text, challenge title
    assert web.fetch_page("https://example.org/b") is None
    patch_http(monkeypatch, lambda req: httpx.Response(404, text="nope"))
    assert web.fetch_page("https://example.org/c") is None
    patch_http(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF"))
    assert web.fetch_page("https://example.org/d") is None


def test_fetch_page_refuses_redirects_to_private_addresses(monkeypatch):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://internal.local/secrets"})

    patch_http(monkeypatch, handler)
    assert web.fetch_page("https://example.org/redirect") is None
    assert seen == ["https://example.org/redirect"]  # the private target was never requested


def test_fetch_page_follows_a_safe_redirect(monkeypatch):
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return html_response("Moved article", BODY)

    patch_http(monkeypatch, handler)
    assert web.fetch_page("https://example.org/old").title == "Moved article"


def test_real_content_rules():
    assert web.is_real_content("How to fix 404 errors in React", "x" * 400)
    assert not web.is_real_content("404 Not Found", "x" * 400)
    assert not web.is_real_content("Error 403", "x" * 400)
    assert not web.is_real_content("Fine title", "too short")
    assert not web.is_real_content("Attention Required! | Cloudflare", "x" * 400)
    assert not web.is_real_content("Fine title", None)


def fake_ddgs(monkeypatch, outcomes):
    """DDGS().text() returns or raises the next outcome each time it is called."""
    import ddgs

    calls = []

    class Fake:
        def text(self, *a, **k):
            calls.append(1)
            outcome = outcomes[min(len(calls), len(outcomes)) - 1]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(ddgs, "DDGS", Fake)
    monkeypatch.setattr(web._ddgs_text.retry, "sleep", lambda _s: None)
    return calls


def test_search_with_no_results_is_empty_after_retrying(monkeypatch):
    from ddgs.exceptions import DDGSException

    calls = fake_ddgs(monkeypatch, [DDGSException("No results found.")])
    assert web.search_web("zzzzqqqq nothing matches this") == []
    assert len(calls) == 3  # believed only after three empty answers


def test_search_recovers_from_a_throttled_empty_answer(monkeypatch):
    from ddgs.exceptions import DDGSException

    hit = {"title": "T", "href": "https://example.org/a", "body": "b"}
    calls = fake_ddgs(monkeypatch, [DDGSException("No results found."), [hit]])
    assert [h.url for h in web.search_web("customer interviews")] == ["https://example.org/a"]
    assert len(calls) == 2


def test_search_keeps_failing_loudly_on_rate_limits(monkeypatch):
    from ddgs.exceptions import RatelimitException

    fake_ddgs(monkeypatch, [RatelimitException("429")])
    with pytest.raises(RatelimitException):
        web.search_web("customer interviews")


def test_summarize_keeps_whole_sentences():
    text = "The export is slow. Users wait minutes for reports to finish. " + "More detail here. " * 50
    summary = web.summarize(text, limit=60)
    assert summary == "The export is slow." and len(summary) <= 60
    assert web.summarize("Short note.") == "Short note."
    assert web.summarize("x" * 500, limit=100).endswith("…")
