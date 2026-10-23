"""Web research: search, fetch and extract page text for the staging vault."""

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

MAX_PAGE_BYTES = 2_000_000
MAX_REDIRECTS = 3
USER_AGENT = "Mozilla/5.0 (compatible; SynapsedResearchBot/1.0)"


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class Page:
    title: str
    url: str
    text: str


MIN_PAGE_CHARS = 300
_CHALLENGE_TITLE = re.compile(
    r"just a moment|one moment|attention required|access denied|are you a (robot|human)|"
    r"verify you are|checking your browser|captcha|403 forbidden|404 not found|page not found|"
    r"^\s*(error\s*)?(403|404)\b",
    re.IGNORECASE,
)


def is_real_content(title: str, text: str | None) -> bool:
    """Reject bot-challenge pages, error pages and near-empty extractions."""
    if not text or len(text.strip()) < MIN_PAGE_CHARS:
        return False
    return not _CHALLENGE_TITLE.search(title or "")


def is_public_url(url: str) -> bool:
    """Only http(s) URLs whose host resolves exclusively to public addresses (SSRF guard)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


class _NoResults(Exception):
    pass


def _transient() -> tuple[type[BaseException], ...]:
    from ddgs.exceptions import RatelimitException, TimeoutException

    return (_NoResults, RatelimitException, TimeoutException)


@retry(
    retry=retry_if_exception_type(_transient()),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    reraise=True,
)
def _ddgs_text(query: str, max_results: int) -> list[dict]:
    """DuckDuckGo often answers "No results found" when it is throttling, even for queries
    that do have results, so an empty answer is retried before it is believed."""
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException

    try:
        results = DDGS().text(query, max_results=max_results)
    except DDGSException as exc:
        if "no results" in str(exc).lower():
            raise _NoResults from exc
        raise
    if not results:
        raise _NoResults
    return results


def search_web(query: str, max_results: int = 5) -> list[SearchHit]:
    try:
        results = _ddgs_text(query, max_results)
    except _NoResults:
        return []
    return [
        SearchHit(r.get("title", ""), r.get("href", ""), r.get("body", ""))
        for r in results if r.get("href")
    ]


def fetch_page(url: str, timeout: float = 15.0) -> Page | None:
    """Fetch a page without trusting redirects, and extract its main text. None on failure."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, headers={"User-Agent": USER_AGENT}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                if not is_public_url(url):
                    return None
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                        return None
                    body = b""
                    for piece in response.iter_bytes():
                        body += piece
                        if len(body) > MAX_PAGE_BYTES:
                            break
                html = body.decode(response.encoding or "utf-8", errors="replace")
                text = trafilatura.extract(html, include_comments=False, include_tables=False)
                meta = trafilatura.extract_metadata(html)
                title = meta.title if meta and meta.title else url
                if not is_real_content(title, text):
                    return None
                return Page(title, url, text)
    except httpx.HTTPError:
        return None
    return None


def summarize(text: str, limit: int = 320) -> str:
    """A short extractive preview: whole sentences from the start, up to limit characters."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", cut)]
    return (cut[: ends[-1]] if ends else cut.rstrip() + "…").strip()
