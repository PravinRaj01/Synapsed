import operator
from dataclasses import dataclass
from typing import Annotated, Callable, TypedDict

from ai_pipeline.providers import Completion


class RunState(TypedDict, total=False):
    """What flows between graph nodes. Large texts stay out of it: nodes reload them by id."""

    campaign_id: str
    user_id: str
    run_id: str
    only_resources: list[str] | None  # restrict the run to these resources (None = all unanalysed)
    resource_ids: list[str]  # selected for this run
    extracted_resources: list[str]  # extracted successfully, including those with no items
    items: list[dict]  # verified items, each tagged with its resource and segment
    insight_ids: list[str]
    new_themes: list[dict]  # {id, label} for themes created in this run (label is None until named)
    themed_insights: int  # insights placed into a theme in this run
    cluster_methods: dict  # how themes were chosen: threshold / agent / fallback -> count
    scored_themes: int
    roadmap_created: int
    roadmap_updated: int
    errors: Annotated[list[dict], operator.add]  # {resource_id, stage, error}


@dataclass
class Deps:
    """Everything the nodes call out to, so tests can swap in fakes."""

    llm: Callable[[list[dict], str | None], Completion]  # (messages, language) -> completion
    embed: Callable[[list[str]], list[list[float]]]
    trace: Callable[..., None]  # (node, status, **details)
    llm_tools: Callable[[list[dict], list[dict]], Completion] | None = None  # (messages, tools) -> completion
