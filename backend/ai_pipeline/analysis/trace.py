import logging
from uuid import UUID

from psycopg.types.json import Jsonb

from app.core.database import user_tx

logger = logging.getLogger("synapsed.trace")

MAX_TEXT = 4000  # prompts and replies are stored truncated


class DbTrace:
    """Writes each pipeline event to agent_runs, which the Laboratory canvas replays.

    Tracing must never break a run, so failures are logged and swallowed.
    """

    def __init__(self, user_id: UUID | str, campaign_id: UUID | str, run_id: UUID | str):
        self.user_id, self.campaign_id, self.run_id = user_id, campaign_id, run_id

    def __call__(
        self, node: str, status: str, *, model_used: str | None = None, prompt: str | None = None,
        input: dict | None = None, output: dict | str | None = None, tokens: int = 0, latency_ms: int | None = None,
    ) -> None:
        if isinstance(output, str):
            output = {"text": output[:MAX_TEXT]}
        try:
            with user_tx(self.user_id) as conn:
                conn.execute(
                    """insert into agent_runs (campaign_id, run_id, node, status, model_used, prompt,
                                               input, output, tokens, latency_ms)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (self.campaign_id, self.run_id, node, status, model_used,
                     prompt[:MAX_TEXT] if prompt else None,
                     Jsonb(input) if input is not None else None,
                     Jsonb(output) if output is not None else None, tokens, latency_ms),
                )
        except Exception:
            logger.warning("Could not write trace event %s/%s", node, status, exc_info=True)
