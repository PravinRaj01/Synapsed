import httpx
import pytest

from ai_pipeline import providers as p
from app.core.config import Settings

MESSAGES = [{"role": "user", "content": "extract pain points from this interview"}]


def settings(**kw):
    base = dict(groq_api_key="g", google_api_key="m", sealion_api_key="s", llm_max_wait_seconds=5.0)
    return Settings(**{**base, **kw})


def reply(text="{}", status=200, headers=None, finish="stop", usage=(100, 20)):
    body = {"choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1], "total_tokens": sum(usage)}}
    return httpx.Response(status, json=body, headers=headers or {})


class FakeNet:
    """Replaces the HTTP call: answers per provider base URL, in order."""

    def __init__(self, script):
        self.script, self.calls = script, []

    def __call__(self, url, body, api_key):
        host = next(h for h in ("groq", "sea-lion", "googleapis") if h in url)
        self.calls.append((host, body))
        outcome = self.script[host].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def net(monkeypatch):
    def install(script, **kw):
        fake = FakeNet(script)
        monkeypatch.setattr(p, "_post", fake)
        monkeypatch.setattr(p, "_providers", p.build_providers(settings(**kw)))
        return fake

    yield install
    monkeypatch.setattr(p, "_providers", None)


def test_first_provider_answers(net):
    fake = net({"groq": [reply('{"a": 1}')]})
    result = p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings())
    assert result.provider == "groq-fast" and result.text == '{"a": 1}' and result.failed_before == []
    assert result.total_tokens == 120 and [c[0] for c in fake.calls] == ["groq"]


@pytest.mark.parametrize("failure", [
    reply(status=429), reply(status=503), reply(status=401), reply(text=""),
    reply(text="partial", finish="length"), httpx.ConnectTimeout("slow"),
])
def test_failures_fall_through_to_the_next_provider(net, failure):
    fake = net({"groq": [failure], "googleapis": [reply("ok")]})
    result = p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings())
    assert result.provider == "gemini" and result.text == "ok"
    assert len(result.failed_before) == 1 and result.failed_before[0].startswith("groq-fast:")
    assert [c[0] for c in fake.calls] == ["groq", "googleapis"]


def test_a_429_puts_the_provider_on_cooldown(net):
    fake = net({"groq": [reply(status=429, headers={"retry-after": "30"})], "googleapis": [reply("a"), reply("b")]})
    first = p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings())
    second = p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings())
    assert (first.text, second.text) == ("a", "b")
    assert "cooling down" in second.failed_before[0]
    assert [c[0] for c in fake.calls].count("groq") == 1  # not retried while cooling


def test_cooldown_expires(net, monkeypatch):
    fake = net({"groq": [reply(status=429, headers={"retry-after": "30"}), reply("back")], "googleapis": [reply("a")]})
    p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings())
    p.get_providers()["groq-fast"].cooldown_until = 0  # time passes
    assert p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings()).provider == "groq-fast"


def test_unconfigured_and_unknown_providers_are_skipped(net):
    net({"googleapis": [reply("ok")]}, sealion_api_key="")
    result = p.complete(MESSAGES, ["sealion", "nope", "gemini"], settings=settings(sealion_api_key=""))
    assert result.provider == "gemini"
    assert result.failed_before == ["sealion: not configured", "nope: not configured"]


def test_all_failing_raises_with_every_reason(net):
    net({"groq": [reply(status=503)], "googleapis": [reply(status=429)]})
    with pytest.raises(p.AllProvidersFailed) as exc:
        p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings())
    assert len(exc.value.failures) == 2 and "HTTP 503" in str(exc.value) and "HTTP 429" in str(exc.value)


def test_empty_chain_raises(net):
    net({})
    with pytest.raises(p.AllProvidersFailed):
        p.complete(MESSAGES, [], settings=settings())


def test_provider_specific_request_bodies(net):
    fake = net({"sea-lion": [reply()], "googleapis": [reply()], "groq": [reply()]})
    for name in ("sealion", "gemini", "groq-fast"):
        p.complete(MESSAGES, [name], settings=settings())
    bodies = {host: body for host, body in fake.calls}
    assert bodies["sea-lion"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert bodies["googleapis"]["response_format"] == {"type": "json_object"}
    assert bodies["groq"]["reasoning_effort"] == "low" and "response_format" not in bodies["groq"]


def test_gemini_json_mode_can_be_turned_off(net):
    fake = net({"googleapis": [reply()]})
    p.complete(MESSAGES, ["gemini"], json_mode=False, settings=settings())
    assert "response_format" not in fake.calls[0][1]


def test_chain_order_by_language():
    s = settings()
    assert p.chain_for("en", s) == ["groq-fast", "gemini", "sealion"] and p.chain_for(None, s)[0] == "groq-fast"
    assert p.chain_for("id", s) == ["gemini", "sealion", "groq-fast"] and p.chain_for("ta", s)[0] == "gemini"
    assert p.chain_for("en", settings(llm_chain_en=" sealion , gemini ")) == ["sealion", "gemini"]


# ---- budgets ----------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_request_budget_waits_for_the_oldest_request_to_expire():
    clock = Clock()
    budget = p.Budget(rpm=3, tpm=None, clock=clock)
    for _ in range(3):
        budget.record(10)
        clock.now += 5
    assert budget.wait_needed(10) == pytest.approx(45)  # oldest was 15 s ago
    clock.now += 45
    assert budget.wait_needed(10) == 0


def test_token_budget_waits_until_enough_has_expired():
    clock = Clock()
    budget = p.Budget(rpm=None, tpm=1000, clock=clock)
    budget.record(600)
    clock.now += 10
    budget.record(300)
    assert budget.wait_needed(100) == 0  # 900 + 100 fits exactly
    assert budget.wait_needed(400) == pytest.approx(50)  # needs the 600 to expire (50 s from now)
    assert budget.wait_needed(2000) > 0  # can never fit, but still bounded by the window


def test_settle_replaces_the_estimate_with_real_usage():
    clock = Clock()
    budget = p.Budget(rpm=None, tpm=1000, clock=clock)
    budget.record(900)  # estimate
    assert budget.wait_needed(500) > 0
    budget.settle(900, 100)  # the reply really cost 100
    assert budget.wait_needed(500) == 0


def test_a_provider_that_would_wait_too_long_is_skipped(net):
    fake = net({"googleapis": [reply("ok")]})
    groq = p.get_providers()["groq-fast"]
    groq.budget.record(7000)  # the whole token window is spent
    result = p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings(llm_max_wait_seconds=5))
    assert result.provider == "gemini" and "budget would need" in result.failed_before[0]
    assert [c[0] for c in fake.calls] == ["googleapis"]


def test_a_short_wait_is_slept_not_skipped(net, monkeypatch):
    fake = net({"groq": [reply("ok")]})
    slept = []
    monkeypatch.setattr(p.time, "sleep", slept.append)
    monkeypatch.setattr(p.Budget, "wait_needed", lambda self, tokens: 3.0)
    assert p.complete(MESSAGES, ["groq-fast"], settings=settings()).provider == "groq-fast"
    assert slept == [3.0]


# ---- reply parsing ----------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ('{"pain_points": []}', {"pain_points": []}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('```\n{"a": 1}\n```', {"a": 1}),
    ('Sure! Here you go:\n{"a": {"b": 2}}\nHope that helps.', {"a": {"b": 2}}),
    ("[1, 2]", [1, 2]),
])
def test_parse_json_reply(text, expected):
    assert p.parse_json_reply(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", '{"a": 1', "{broken}"])
def test_parse_json_reply_rejects_garbage(text):
    with pytest.raises(ValueError):
        p.parse_json_reply(text)


TOOLS = [{"type": "function", "function": {"name": "create_new_theme", "parameters": {"type": "object"}}}]


def tool_reply(*calls, text=""):
    message = {"content": text or None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": args}} for cid, name, args in calls
    ]}
    body = {"choices": [{"message": message, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 15, "total_tokens": 95}}
    return httpx.Response(200, json=body)


def test_tools_are_sent_and_tool_calls_are_returned(net):
    fake = net({"groq": [tool_reply(("c1", "create_new_theme", '{"label": "Slow export"}'))]})
    result = p.complete(MESSAGES, ["groq-fast"], settings=settings(), tools=TOOLS)
    body = fake.calls[0][1]
    assert body["tools"] == TOOLS and body["tool_choice"] == "auto"
    assert result.text == "" and len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("c1", "create_new_theme", {"label": "Slow export"})


def test_bad_tool_arguments_become_an_empty_dict_but_keep_the_raw_text(net):
    net({"groq": [tool_reply(("c1", "create_new_theme", "{not json"), ("c2", "create_new_theme", "[1, 2]"))]})
    calls = p.complete(MESSAGES, ["groq-fast"], settings=settings(), tools=TOOLS).tool_calls
    assert [c.arguments for c in calls] == [{}, {}] and calls[0].raw_arguments == "{not json"


def test_gemini_json_mode_is_not_sent_together_with_tools(net):
    fake = net({"googleapis": [tool_reply(("c1", "create_new_theme", "{}"))]})
    p.complete(MESSAGES, ["gemini"], settings=settings(), tools=TOOLS)
    assert "response_format" not in fake.calls[0][1] and "tools" in fake.calls[0][1]


def test_no_tools_means_no_tool_fields(net):
    fake = net({"groq": [reply("ok")]})
    p.complete(MESSAGES, ["groq-fast"], settings=settings())
    assert "tools" not in fake.calls[0][1] and "tool_choice" not in fake.calls[0][1]


def test_a_reply_with_neither_text_nor_tool_calls_still_falls_through(net):
    fake = net({"groq": [reply("")], "googleapis": [reply("ok")]})
    assert p.complete(MESSAGES, ["groq-fast", "gemini"], settings=settings(), tools=TOOLS).provider == "gemini"
    assert len(fake.calls) == 2


def test_tool_conversation_messages_can_be_estimated(net):
    history = MESSAGES + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function",
                                                             "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "[]"},
    ]
    net({"groq": [reply("done")]})
    assert p.complete(history, ["groq-fast"], settings=settings(), tools=TOOLS).text == "done"
