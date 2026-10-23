import pytest

from app.core import rate_limit
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def no_rate_limits(monkeypatch):
    """Rate limits are off in tests (many tests call an endpoint more often than a real user may).

    Tests of the limiter itself patch `rate_limit.get_settings` again, which takes precedence.
    """
    real = get_settings()
    monkeypatch.setattr(rate_limit, "get_settings", lambda: real.model_copy(update={"rate_limit_enabled": False}))
