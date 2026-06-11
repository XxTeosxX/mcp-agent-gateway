import logging

import pytest

from app.logging import SensitiveDataFilter


@pytest.fixture
def sensitive_filter():
    return SensitiveDataFilter()


def _make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, "", 0, msg, (), None)


def test_bearer_token_scrubbed(sensitive_filter):
    record = _make_record("Auth: Bearer eyJhbGciOiJSUzI1NiJ9.secret")
    sensitive_filter.filter(record)
    assert "eyJhbGciOiJSUzI1NiJ9" not in record.getMessage()
    assert "Bearer ***" in record.getMessage()


def test_slack_bot_token_scrubbed(sensitive_filter):
    record = _make_record("token=xoxb-123456789-abcdefgh")
    sensitive_filter.filter(record)
    assert "xoxb-123456789" not in record.getMessage()
    assert "xox*-***" in record.getMessage()


def test_slack_user_token_scrubbed(sensitive_filter):
    record = _make_record("token=xoxp-123456789-abcdefgh")
    sensitive_filter.filter(record)
    assert "xoxp-123456789" not in record.getMessage()
    assert "xox*-***" in record.getMessage()


def test_google_refresh_token_scrubbed(sensitive_filter):
    record = _make_record("refresh=1//abc123.def-456")
    sensitive_filter.filter(record)
    assert "abc123" not in record.getMessage()
    assert "1//***" in record.getMessage()


def test_benign_text_untouched(sensitive_filter):
    record = _make_record("Request completed in 42ms")
    sensitive_filter.filter(record)
    assert record.getMessage() == "Request completed in 42ms"
