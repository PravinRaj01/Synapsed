"""Create a Jira Cloud issue from a PRD (REST API v3, basic auth with an API token)."""

import re

import httpx

from app.core.config import Settings

TIMEOUT = 20.0
MAX_TEXT = 30000  # Jira limits descriptions to about 32,767 characters
MAX_SUMMARY = 250


class JiraError(Exception):
    """A problem to show the user: bad credentials, an unknown project, Jira being down."""


def configured(settings: Settings) -> bool:
    return all([settings.jira_base_url, settings.jira_email, settings.jira_api_token, settings.jira_project_key])


def _plain(text: str) -> str:
    """Drop Markdown emphasis markers; Jira's document format is built from nodes, not markup."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w])_(.+?)_(?![\w])", r"\1", text)
    return text.replace("`", "").strip()


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def markdown_to_adf(markdown: str) -> dict:
    """The subset of Markdown a PRD uses (headings, bullets, checkboxes, quotes, paragraphs) as an Atlassian document."""
    blocks: list[dict] = []
    bullets: list[str] = []
    quotes: list[str] = []

    def flush() -> None:
        if bullets:
            blocks.append({"type": "bulletList", "content": [
                {"type": "listItem", "content": [_paragraph(item)]} for item in bullets]})
            bullets.clear()
        if quotes:
            blocks.append({"type": "blockquote", "content": [_paragraph(" ".join(quotes))]})
            quotes.clear()

    for raw in markdown[:MAX_TEXT].splitlines():
        line = raw.rstrip()
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        bullet = re.match(r"^\s*-\s+(?:\[[ xX]\]\s+)?(.*)$", line)
        if heading:
            flush()
            if _plain(heading.group(2)):
                blocks.append({"type": "heading", "attrs": {"level": len(heading.group(1))},
                               "content": [{"type": "text", "text": _plain(heading.group(2))}]})
        elif bullet:
            if quotes:
                flush()
            if _plain(bullet.group(1)):
                bullets.append(_plain(bullet.group(1)))
        elif line.startswith(">"):
            if bullets:
                flush()
            if _plain(line.lstrip("> ")):
                quotes.append(_plain(line.lstrip("> ")))
        elif not line.strip():
            flush()
        else:
            flush()
            blocks.append(_paragraph(_plain(line)) if _plain(line) else _paragraph(" "))
    flush()
    return {"type": "doc", "version": 1, "content": blocks or [_paragraph(" ")]}


def create_issue(settings: Settings, summary: str, markdown: str) -> tuple[str, str]:
    """Create the issue and return (key, browse URL)."""
    if not configured(settings):
        raise JiraError("Jira is not configured on the server")
    base = settings.jira_base_url.rstrip("/")
    body = {"fields": {
        "project": {"key": settings.jira_project_key}, "summary": " ".join(summary.split())[:MAX_SUMMARY],
        "issuetype": {"name": settings.jira_issue_type}, "description": markdown_to_adf(markdown)}}
    try:
        response = httpx.post(f"{base}/rest/api/3/issue", json=body, auth=(settings.jira_email, settings.jira_api_token), timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise JiraError("Jira could not be reached") from exc
    if response.status_code in (401, 403):
        raise JiraError("Jira rejected the credentials or the account cannot create issues in this project")
    if response.status_code >= 400:
        try:
            detail = response.json()
            messages = detail.get("errorMessages") or list((detail.get("errors") or {}).values())
        except ValueError:
            messages = []
        raise JiraError(f"Jira refused the issue: {'; '.join(str(m) for m in messages)[:300] or f'HTTP {response.status_code}'}")
    key = response.json().get("key")
    if not key:
        raise JiraError("Jira answered without an issue key")
    return key, f"{base}/browse/{key}"
