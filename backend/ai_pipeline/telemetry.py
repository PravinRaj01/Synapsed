from uuid import UUID

import psycopg

from ai_pipeline.providers import Completion


def record_completion(conn: psycopg.Connection, campaign_id: UUID, action_type: str, completion: Completion) -> None:
    """Write one LLM call to telemetry_logs inside the caller's transaction.

    fallback_from names the providers that failed before this one answered, so the dashboard
    can show how often the free tiers push us down the chain.
    """
    conn.execute(
        """insert into telemetry_logs (campaign_id, model_used, tokens_processed, latency_ms, action_type, fallback_from)
           values (%s, %s, %s, %s, %s, %s)""",
        (
            campaign_id,
            f"{completion.provider}:{completion.model}",
            completion.total_tokens,
            completion.latency_ms,
            action_type,
            ", ".join(completion.failed_before) or None,
        ),
    )
