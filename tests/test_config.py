from app.config import Settings


def test_rate_limit_defaults():
    s = Settings()
    assert s.RATE_LIMIT_ENABLED is True
    assert s.RATE_LIMIT_MAX_REQUESTS == 100
    assert s.RATE_LIMIT_WINDOW_SECONDS == 60
