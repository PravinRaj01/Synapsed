from collections import Counter

import pytest

from ai_pipeline.analysis import extraction as ex
from ai_pipeline.analysis.quotes import locate_quote
from ai_pipeline.providers import AllProvidersFailed, Completion

TEXT = (
    "Interviewer: How do you handle reporting?\n"
    "Maya: Every month I export four CSV files and stitch them together in a spreadsheet, which takes me most "
    "of a day.   The export also times out whenever an account has more than ten thousand rows.\n"
    "Maya: Otherwise the team is great."
)


# ---- locating quotes --------------------------------------------------------------------

def test_exact_quote_gives_exact_offsets():
    quote = "Every month I export four CSV files and stitch them together in a spreadsheet"
    match = locate_quote(TEXT, quote)
    assert match.exact and TEXT[match.start : match.end] == quote


def test_surrounding_quote_marks_are_ignored():
    match = locate_quote(TEXT, '"The export also times out whenever an account has more than ten thousand rows."')
    assert match.exact and TEXT[match.start : match.end].startswith("The export also times out")


def test_whitespace_and_case_differences_still_match_and_map_back_to_the_source():
    match = locate_quote(TEXT, "which takes me most of a day. the EXPORT also times out")
    assert match and not match.exact
    assert TEXT[match.start : match.end] == "which takes me most of a day.   The export also times out"


def test_curly_quotes_and_dashes_are_unified():
    text = "She said it’s a real pain – every single week, we redo this by hand."
    match = locate_quote(text, "it's a real pain - every single week")
    assert match and text[match.start : match.end] == "it’s a real pain – every single week"


def test_invented_or_reworded_quotes_are_not_found():
    assert locate_quote(TEXT, "The export is broken and nobody at the company cares") is None
    assert locate_quote(TEXT, "Every month I export five CSV files and stitch them") is None


def test_a_quote_shortened_with_an_ellipsis_still_counts_if_every_piece_is_in_the_text():
    ellipsis_quote = "Every month I export four CSV files... The export also times out whenever an account has more than ten thousand rows"
    match = locate_quote(TEXT, ellipsis_quote)
    assert match and TEXT[match.start : match.end] == "Every month I export four CSV files"
    trailing = locate_quote(TEXT, "The export also times out whenever an account has more...")
    assert trailing and TEXT[trailing.start : trailing.end].startswith("The export also times out")
    unicode_dots = locate_quote(TEXT, "…The export also times out whenever an account has more than ten thousand rows…")
    assert unicode_dots and TEXT[unicode_dots.start : unicode_dots.end].endswith("ten thousand rows")


def test_an_ellipsis_does_not_launder_an_invented_piece_or_the_wrong_order():
    assert locate_quote(TEXT, "Every month I export four CSV files... and then the whole company cheers loudly") is None
    assert locate_quote(TEXT, "The export also times out whenever an account... Every month I export four CSV files") is None


def test_very_short_quotes_are_rejected():
    assert locate_quote(TEXT, "export") is None
    assert locate_quote(TEXT, "  day.  ") is None


def test_non_latin_text_is_located():
    text = "எங்கள் கடையில் கழிவு மேலாண்மை மிகவும் கடினமாக உள்ளது. தினமும் நிறைய உணவு கழிவு வருகிறது."
    match = locate_quote(text, "தினமும்  நிறைய உணவு கழிவு வருகிறது")
    assert match and text[match.start : match.end] == "தினமும் நிறைய உணவு கழிவு வருகிறது"


# ---- validating the model's JSON --------------------------------------------------------

def entry(**kw):
    base = dict(kind="pain_point", pain_point="Exports time out on large accounts",
                quote="The export also times out whenever an account has more than ten thousand rows",
                use_case="monthly reporting", severity=4, sentiment="negative")
    return {**base, **kw}


def validate(raw, window=TEXT, start=0):
    dropped = Counter()
    return ex.validate_items(raw, window, start, dropped), dropped


def test_valid_item_is_kept_with_the_sources_own_quote_and_offsets():
    items, dropped = validate({"items": [entry()]})
    assert len(items) == 1 and not dropped
    item = items[0]
    assert TEXT[item.start : item.end] == item.quote and item.exact and item.severity == 4


def test_offsets_include_the_window_start():
    window = TEXT[40:]
    items, _ = validate({"items": [entry()]}, window=window, start=40)
    assert TEXT[items[0].start : items[0].end] == items[0].quote


def test_unfound_quotes_are_dropped_and_counted():
    items, dropped = validate({"items": [entry(quote="Nobody ever answers our support tickets here")]})
    assert items == [] and dropped["quote_not_found"] == 1


def test_bad_shapes_are_dropped():
    items, dropped = validate({"items": [entry(pain_point=""), entry(quote=""), "oops", {"x": 1}]})
    assert items == [] and dropped["bad_shape"] == 4
    assert validate({"items": "nope"})[1]["bad_shape"] == 1
    assert validate([entry()])[0]  # a bare list is accepted too


def test_enums_and_numbers_are_normalised():
    items, _ = validate({"items": [entry(kind="Feature_Request", sentiment="ANGRY", severity="9")]})
    assert (items[0].kind, items[0].sentiment, items[0].severity) == ("feature_request", "neutral", 5)
    items, _ = validate({"items": [entry(kind="whatever", severity=None, sentiment="Positive")]})
    assert (items[0].kind, items[0].severity, items[0].sentiment) == ("pain_point", 3, "positive")


def test_overlong_quotes_are_cut_back_to_their_first_part_not_dropped():
    # Spoken transcripts have no sentence ends, so a "sentence" can run on for pages.
    long_text = " ".join(f"word{i}" for i in range(400))
    items, dropped = validate({"items": [entry(quote=long_text)]}, window=long_text)
    assert len(items) == 1 and not dropped
    assert 0 < len(items[0].quote) <= ex.MAX_QUOTE_CHARS
    assert long_text.startswith(items[0].quote) and not items[0].quote.endswith("wor")  # whole words, still verbatim
    assert items[0].start == 0 and items[0].end == len(items[0].quote)


def test_an_overlong_quote_that_is_not_in_the_text_is_still_dropped():
    long_text = " ".join(f"word{i}" for i in range(400))
    invented = " ".join(f"other{i}" for i in range(400))
    items, dropped = validate({"items": [entry(quote=invented)]}, window=long_text)
    assert items == [] and dropped["quote_not_found"] == 1


def test_shorten_quote_leaves_short_quotes_alone_and_cuts_at_a_word():
    assert ex.shorten_quote("  a short quote  ") == "a short quote"
    cut = ex.shorten_quote("lorem " * 200)
    assert len(cut) <= ex.MAX_QUOTE_CHARS and cut.endswith("lorem")
    assert len(ex.shorten_quote("x" * 1000)) == ex.MAX_QUOTE_CHARS  # no spaces to cut at


def test_merge_windows_removes_duplicates_from_overlapping_windows():
    a = ex.Item("pain_point", "x", "q", "", 3, "negative", 100, 200, True)
    dup = ex.Item("pain_point", "x again", "q", "", 3, "negative", 110, 205, True)
    other = ex.Item("pain_point", "y", "q2", "", 3, "negative", 300, 380, True)
    assert ex.merge_windows([dup, other, a]) == [a, other]


# ---- extracting a whole resource --------------------------------------------------------

class Llm:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, language):
        self.calls.append((messages, language))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return Completion(reply, "gemini", "m", 100, 50, 900)


def test_extract_resource_end_to_end():
    import json

    llm = Llm([json.dumps({"items": [entry()]})])
    seen = []
    result = ex.extract_resource(TEXT, "en", llm, on_completion=lambda c, m: seen.append(c.provider))
    assert len(result.items) == 1 and result.windows == 1 and seen == ["gemini"]
    messages, language = llm.calls[0]
    assert language == "en" and messages[0]["role"] == "system" and TEXT in messages[1]["content"]


def test_a_non_json_reply_is_retried_once_with_a_reminder():
    import json

    llm = Llm(["Sorry, here are the points: none", json.dumps({"items": [entry()]})])
    result = ex.extract_resource(TEXT, "en", llm)
    assert len(result.items) == 1 and len(llm.calls) == 2
    assert llm.calls[1][0][-1]["content"] == ex.RETRY_NOTE


def test_two_bad_replies_raise():
    with pytest.raises(ValueError):
        ex.extract_resource(TEXT, "en", Llm(["nope", "still nope"]))


def test_provider_failure_propagates():
    with pytest.raises(AllProvidersFailed):
        ex.extract_resource(TEXT, "en", Llm([AllProvidersFailed(["gemini: HTTP 429"])]))


def test_long_text_is_split_into_windows_and_results_merged():
    import json

    long_text = ("Maya: " + "The export also times out whenever an account has more than ten thousand rows. " * 3 + "\n\n") * 60  # about 14,700 characters
    assert len(long_text) > 2 * ex.MAX_WINDOW_CHARS
    reply = json.dumps({"items": [entry()]})
    llm = Llm([reply] * 10)
    result = ex.extract_resource(long_text, "en", llm)
    assert result.windows == len(llm.calls) >= 2
    starts = [i.start for i in result.items]
    assert starts == sorted(starts) and len(set(starts)) == len(starts)  # no duplicates
    assert all(long_text[i.start : i.end] == i.quote for i in result.items)


def test_prompt_demands_english_summaries_and_exact_quotes():
    system = ex.build_messages("x")[0]["content"]
    assert "IN ENGLISH" in system and "EXACTLY" in system and "<PERSON>" in system and '"items": []' in system


def test_the_graph_has_the_planned_shape_and_exports_its_branches():
    from ai_pipeline.analysis.graph import build_graph

    mermaid = build_graph().get_graph().draw_mermaid()
    edges = {line.strip() for line in mermaid.splitlines() if ">" in line}
    # dotted arrows are the conditional edges: stop early when there is nothing to analyse or place
    assert {"__start__ --> select;", "select -.-> extract;", "select -.-> __end__;",
            "extract --> embed;", "embed -.-> cluster;", "embed -.-> __end__;",
            "cluster --> name_themes;", "name_themes --> score;", "score --> roadmap;",
            "roadmap --> __end__;"} <= edges
