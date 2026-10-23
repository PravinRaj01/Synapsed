import json

import pytest

from ai_pipeline.analysis import clustering as cl
from ai_pipeline.analysis.clustering import Candidate
from ai_pipeline.providers import AllProvidersFailed, Completion, ToolCall

JOIN, NEW = 0.90, 0.81


def call(name, **args):
    return ToolCall("c1", name, args, json.dumps(args))


def reply(*calls, text=""):
    return Completion(text, "gemini", "flash-lite", 100, 20, 500, tool_calls=list(calls))


class Script:
    """A scripted model: answers in order and records what it was shown."""

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def __call__(self, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class Events:
    def __init__(self):
        self.items = []

    def __call__(self, node, status, **details):
        self.items.append((node, status, details))

    def tools(self):
        return [d["output"].get("tool") for _, _, d in self.items if "output" in d]


EXPORT = Candidate("t-export", "Slow export", 0.85, ["Export times out on large accounts"])
LOGIN = Candidate("t-login", "Login problems", 0.83, ["Cannot sign in with Google"])


def run(candidates, llm=None, search=None, max_steps=4, events=None, on_completion=None):
    events = events or Events()
    decision = cl.decide(
        "Reports take ten minutes to export", candidates, join=JOIN, new=NEW, max_steps=max_steps,
        llm=llm or Script(), search=search or (lambda q: []), trace=events, on_completion=on_completion,
    )
    return decision, events


@pytest.mark.parametrize("best,expected", [(0.95, "join"), (0.90, "join"), (0.89, None), (0.81, None), (0.80, "new"), (None, "new")])
def test_threshold_decision(best, expected):
    assert cl.threshold_decision(best, JOIN, NEW) == expected


def test_a_close_match_joins_without_calling_the_model():
    llm = Script()
    decision, events = run([Candidate("t1", "Slow export", 0.93)], llm)
    assert (decision.action, decision.theme_id, decision.method) == ("join", "t1", "threshold")
    assert llm.seen == [] and events.items == []


def test_a_distant_or_missing_match_starts_a_new_theme_without_the_model():
    llm = Script()
    assert run([Candidate("t1", "Other", 0.70)], llm)[0].action == "new"
    first = run([], llm)[0]
    assert (first.action, first.method, first.similarity) == ("new", "threshold", None)
    assert llm.seen == []


def test_grey_zone_agent_appends_to_a_candidate():
    llm = Script(reply(call("append_pain_point", theme_id="t-export")))
    seen = []
    decision, events = run([EXPORT, LOGIN], llm, on_completion=seen.append)
    assert (decision.action, decision.theme_id, decision.method, decision.steps) == ("join", "t-export", "agent", 1)
    shown = json.loads(llm.seen[0][1]["content"])
    assert shown["new_pain_point"].startswith("Reports take") and shown["candidates"][0]["theme_id"] == "t-export"
    assert len(seen) == 1 and events.tools() == ["append_pain_point"]


def test_grey_zone_agent_can_create_a_theme_and_the_label_is_cleaned():
    llm = Script(reply(call("create_new_theme", label="  Report   export is slow  ")))
    decision, _ = run([EXPORT], llm)
    assert (decision.action, decision.label, decision.method) == ("new", "Report export is slow", "agent")


def test_long_labels_are_cut():
    decision, _ = run([EXPORT], Script(reply(call("create_new_theme", label="x" * 300))))
    assert len(decision.label) == cl.MAX_LABEL_CHARS


def test_search_then_decide_can_use_a_theme_found_by_the_search():
    found = Candidate("t-found", "Slow reports", 0.88, ["Monthly reports are slow to generate"])
    searched = []
    llm = Script(reply(call("search_existing_clusters", query="slow reports")), reply(call("append_pain_point", theme_id="t-found")))
    decision, events = run([EXPORT], llm, search=lambda q: searched.append(q) or [found])
    assert (decision.theme_id, decision.steps) == ("t-found", 2) and searched == ["slow reports"]
    followup = llm.seen[1]
    assert followup[-2]["tool_calls"][0]["function"]["name"] == "search_existing_clusters"
    assert followup[-1]["role"] == "tool" and "t-found" in followup[-1]["content"]
    assert events.tools() == ["search_existing_clusters", "append_pain_point"]


def test_an_invented_theme_id_is_rejected_and_the_agent_can_correct_itself():
    llm = Script(reply(call("append_pain_point", theme_id="t-made-up")), reply(call("append_pain_point", theme_id="t-export")))
    decision, _ = run([EXPORT], llm)
    assert (decision.theme_id, decision.steps) == ("t-export", 2)
    assert "unknown theme_id" in llm.seen[1][-1]["content"]


def test_missing_or_garbled_arguments_are_reported_back_to_the_model():
    bad = ToolCall("c1", "create_new_theme", {}, "{not json")
    llm = Script(reply(bad), reply(call("append_pain_point")), reply(call("search_existing_clusters")), reply(call("create_new_theme", label="OK")))
    decision, _ = run([EXPORT], llm)
    assert (decision.action, decision.label, decision.steps) == ("new", "OK", 4)
    assert "label is required" in llm.seen[1][-1]["content"]
    assert "unknown theme_id" in llm.seen[2][-1]["content"]
    assert "query is required" in llm.seen[3][-1]["content"]


def test_an_unknown_function_is_reported_back():
    llm = Script(reply(call("delete_everything")), reply(call("create_new_theme", label="Export")))
    decision, _ = run([EXPORT], llm)
    assert decision.action == "new" and "unknown function" in llm.seen[1][-1]["content"]


def test_only_the_first_of_several_tool_calls_is_used():
    first, second = ToolCall("a", "append_pain_point", {"theme_id": "t-export"}, "{}"), ToolCall("b", "create_new_theme", {"label": "X"}, "{}")
    decision, _ = run([EXPORT], Script(reply(first, second)))
    assert decision.action == "join"


def test_a_reply_without_a_tool_call_gets_a_nudge():
    llm = Script(reply(text="I think they are the same."), reply(call("append_pain_point", theme_id="t-export")))
    decision, _ = run([EXPORT], llm)
    assert decision.theme_id == "t-export" and llm.seen[1][-1]["content"] == cl.NUDGE


def test_the_step_limit_falls_back_to_similarity():
    llm = Script(*[reply(call("search_existing_clusters", query="q"))] * 3)
    close = Candidate("t-close", "Close", 0.88)  # above the midpoint (0.855): joins
    decision, events = run([close], llm, max_steps=3)
    assert (decision.action, decision.theme_id, decision.method, decision.note) == ("join", "t-close", "fallback", "step limit reached")
    assert len(llm.seen) == 3 and events.items[-1][2]["output"]["note"] == "step limit reached"
    far = run([Candidate("t-far", "Far", 0.83)], Script(*[reply(call("search_existing_clusters", query="q"))] * 2), max_steps=2)[0]
    assert (far.action, far.method) == ("new", "fallback")


def test_when_no_provider_answers_the_fallback_decides_and_the_failure_is_traced():
    llm = Script(AllProvidersFailed(["gemini: HTTP 429", "groq-fast: HTTP 503"]))
    decision, events = run([Candidate("t1", "Near", 0.89)], llm)
    assert (decision.action, decision.method, decision.note) == ("join", "fallback", "no provider answered")
    assert events.items[0][1] == "error"


def test_provider_failure_after_a_first_step_still_falls_back():
    llm = Script(reply(call("search_existing_clusters", query="q")), AllProvidersFailed(["all: down"]))
    decision, _ = run([EXPORT], llm)
    assert decision.method == "fallback" and decision.steps == 1


def test_fallback_midpoint():
    assert cl.fallback_decision(Candidate("t", "x", 0.86), JOIN, NEW).action == "join"
    assert cl.fallback_decision(Candidate("t", "x", 0.85), JOIN, NEW).action == "new"
    assert cl.fallback_decision(None, JOIN, NEW).action == "new"
