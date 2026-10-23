"""One way to call the free LLM providers (Groq, SEA-LION, Gemini) and survive their limits.

All three speak the OpenAI chat-completions dialect. A request goes down a provider chain:
a provider is skipped when it is not configured, is cooling down after a 429, or would have
to wait too long for its request/token budget; it is abandoned for the next one on errors,
timeouts or an empty reply. Every result says which provider answered and which failed first.
"""

import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger("synapsed.llm")

REQUEST_TIMEOUT = 90.0
COMPLETION_TOKEN_GUESS = 600  # what a typical reply costs against a token budget before we know


class ProviderUnavailable(Exception):
    """This provider cannot take the request right now; try the next one."""


class AllProvidersFailed(Exception):
    def __init__(self, failures: list[str]):
        super().__init__("; ".join(failures) or "no provider is configured for this request")
        self.failures = failures


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict  # {} when the model sent arguments that are not a JSON object
    raw_arguments: str = ""


@dataclass
class Completion:
    text: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    failed_before: list[str] = field(default_factory=list)  # e.g. ["groq-fast: HTTP 429"]
    tool_calls: list[ToolCall] = field(default_factory=list)  # set when the model chose to call tools

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Budget:
    """Sliding one-minute window of requests and tokens."""

    def __init__(self, rpm: int | None, tpm: int | None, clock: Callable[[], float] = time.monotonic):
        self.rpm, self.tpm, self._clock = rpm, tpm, clock
        self._events: deque[tuple[float, int]] = deque()  # (time, tokens)
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        while self._events and now - self._events[0][0] >= 60:
            self._events.popleft()

    def wait_needed(self, tokens: int) -> float:
        """Seconds until a request of this size fits in the window (0 = now)."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            events = list(self._events)
        wait = 0.0
        if self.rpm and len(events) >= self.rpm:
            wait = max(wait, 60 - (now - events[len(events) - self.rpm][0]))
        if self.tpm:
            used = sum(t for _, t in events)
            for stamp, t in events:  # oldest first: how long until enough has expired
                if used + tokens <= self.tpm:
                    break
                used -= t
                wait = max(wait, 60 - (now - stamp))
        return max(wait, 0.0)

    def record(self, tokens: int) -> None:
        """Log a request against the window, using an estimate until real usage is known."""
        now = self._clock()
        with self._lock:
            self._prune(now)
            self._events.append((now, tokens))

    def settle(self, estimated: int, actual: int) -> None:
        """Replace the most recent matching estimate with the real token count."""
        with self._lock:
            for i in range(len(self._events) - 1, -1, -1):
                stamp, tokens = self._events[i]
                if tokens == estimated:
                    self._events[i] = (stamp, actual)
                    return


@dataclass
class Provider:
    name: str
    base_url: str
    model: str
    api_key: str
    extra_body: dict
    budget: Budget
    cooldown_until: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)


_providers: dict[str, Provider] | None = None
_providers_lock = threading.Lock()


def build_providers(settings: Settings) -> dict[str, Provider]:
    return {
        "groq-fast": Provider(
            "groq-fast", "https://api.groq.com/openai/v1", settings.groq_model_fast, settings.groq_api_key,
            {"reasoning_effort": "low"},
            Budget(rpm=None, tpm=7000),  # free tier: 8,000 tokens/min, with headroom
        ),
        "sealion": Provider(
            "sealion", "https://api.sea-lion.ai/v1", settings.sealion_model, settings.sealion_api_key,
            {"chat_template_kwargs": {"enable_thinking": False}},  # it otherwise burns the whole reply on reasoning
            Budget(rpm=9, tpm=None),  # free tier: 10 requests/min
        ),
        "gemini": Provider(
            "gemini", "https://generativelanguage.googleapis.com/v1beta/openai", settings.gemini_model,
            settings.google_api_key, {}, Budget(rpm=None, tpm=None),  # no published free limits: rely on 429s
        ),
    }


def get_providers() -> dict[str, Provider]:
    global _providers
    with _providers_lock:
        if _providers is None:
            _providers = build_providers(get_settings())
        return _providers


def chain_for(language: str | None, settings: Settings | None = None) -> list[str]:
    """Provider order for a language: English first uses the fast Groq model, others lean on Gemini/SEA-LION."""
    settings = settings or get_settings()
    raw = settings.llm_chain_en if language in (None, "en") else settings.llm_chain_other
    return [name.strip() for name in raw.split(",") if name.strip()]


def _estimate_tokens(messages: list[dict], max_tokens: int) -> int:
    chars = sum(len(m.get("content") or "") + len(json.dumps(m.get("tool_calls") or "")) for m in messages)
    return chars // 3 + min(max_tokens, COMPLETION_TOKEN_GUESS)


def _post(url: str, body: dict, api_key: str) -> httpx.Response:
    return httpx.post(
        url, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=REQUEST_TIMEOUT
    )


def _parse_tool_calls(raw_calls: list[dict]) -> list[ToolCall]:
    calls = []
    for index, raw in enumerate(raw_calls):
        function = raw.get("function") or {}
        raw_arguments = function.get("arguments") or ""
        try:
            arguments = json.loads(raw_arguments) if raw_arguments else {}
        except json.JSONDecodeError:
            arguments = {}
        calls.append(ToolCall(
            raw.get("id") or f"call_{index}", function.get("name") or "",
            arguments if isinstance(arguments, dict) else {}, raw_arguments,
        ))
    return calls


def _call(
    provider: Provider, messages: list[dict], max_tokens: int, json_mode: bool, max_wait: float,
    tools: list[dict] | None = None,
) -> Completion:
    now = time.monotonic()
    if provider.cooldown_until > now:
        raise ProviderUnavailable(f"cooling down for {provider.cooldown_until - now:.0f}s after a 429")
    estimate = _estimate_tokens(messages, max_tokens)
    wait = provider.budget.wait_needed(estimate)
    if wait > max_wait:
        raise ProviderUnavailable(f"budget would need a {wait:.0f}s wait")
    if wait > 0:
        time.sleep(wait)

    body = {"model": provider.model, "messages": messages, "max_tokens": max_tokens, **provider.extra_body}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if json_mode and not tools and provider.name == "gemini":
        body["response_format"] = {"type": "json_object"}  # without it Flash-Lite often answers with an empty list
    provider.budget.record(estimate)
    started = time.monotonic()
    try:
        response = _post(f"{provider.base_url}/chat/completions", body, provider.api_key)
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"{type(exc).__name__}") from exc
    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code == 429:
        retry_after = response.headers.get("retry-after", "")
        provider.cooldown_until = time.monotonic() + (float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 30.0)
        raise ProviderUnavailable("HTTP 429")
    if response.status_code != 200:
        raise ProviderUnavailable(f"HTTP {response.status_code}")

    data = response.json()
    choice = data["choices"][0]
    text = (choice["message"].get("content") or "").strip()
    tool_calls = _parse_tool_calls(choice["message"].get("tool_calls") or [])
    usage = data.get("usage") or {}
    prompt_tokens, completion_tokens = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    if usage.get("total_tokens"):
        provider.budget.settle(estimate, usage["total_tokens"])
    if not text and not tool_calls:
        raise ProviderUnavailable(f"empty reply (finish: {choice.get('finish_reason')})")
    if choice.get("finish_reason") == "length":
        raise ProviderUnavailable("reply was cut off at max_tokens")
    return Completion(
        text, provider.name, provider.model, prompt_tokens, completion_tokens, latency_ms, tool_calls=tool_calls
    )


def complete(
    messages: list[dict], chain: list[str], *, max_tokens: int = 1500, json_mode: bool = True,
    settings: Settings | None = None, tools: list[dict] | None = None,
) -> Completion:
    """Run the request down the chain and return the first usable answer.

    With `tools` (OpenAI function schemas) the reply may carry `tool_calls` instead of text.
    """
    settings = settings or get_settings()
    providers = get_providers()
    failures: list[str] = []
    for name in chain:
        provider = providers.get(name)
        if provider is None or not provider.configured:
            failures.append(f"{name}: not configured")
            continue
        try:
            result = _call(provider, messages, max_tokens, json_mode, settings.llm_max_wait_seconds, tools)
        except ProviderUnavailable as exc:
            logger.warning("LLM provider %s failed: %s", name, exc)
            failures.append(f"{name}: {exc}")
            continue
        result.failed_before = failures
        return result
    raise AllProvidersFailed(failures)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_reply(text: str) -> dict | list:
    """Parse a model's JSON reply, tolerating code fences and chatter around the object."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("the reply contains no JSON object") from None
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"the reply is not valid JSON: {exc.msg}") from exc
