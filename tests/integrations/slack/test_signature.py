import hashlib
import hmac

from app.integrations.slack.signature import (
    is_timestamp_fresh,
    verify_slack_signature,
)

_SECRET = "test-signing-secret"


def _sign(secret: str, timestamp: str, raw: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + raw
    return "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()


def test_verify_valid_signature():
    ts = "1700000000"
    body = b'{"type":"event_callback"}'
    sig = _sign(_SECRET, ts, body)
    assert verify_slack_signature(_SECRET, ts, body, sig) is True


def test_verify_rejects_tampered_body():
    ts = "1700000000"
    sig = _sign(_SECRET, ts, b'{"type":"event_callback"}')
    assert verify_slack_signature(_SECRET, ts, b'{"type":"TAMPERED"}', sig) is False


def test_verify_rejects_wrong_secret():
    ts = "1700000000"
    body = b'{"a":1}'
    sig = _sign("other-secret", ts, body)
    assert verify_slack_signature(_SECRET, ts, body, sig) is False


def test_verify_rejects_empty_secret_or_header():
    ts = "1700000000"
    body = b'{"a":1}'
    sig = _sign(_SECRET, ts, body)
    assert verify_slack_signature("", ts, body, sig) is False
    assert verify_slack_signature(_SECRET, ts, body, "") is False


def test_timestamp_fresh_now():
    now = 1700000000.0
    assert is_timestamp_fresh("1700000000", now=now) is True


def test_timestamp_stale_beyond_window():
    now = 1700000000.0
    assert is_timestamp_fresh(str(1700000000 - 301), now=now) is False


def test_timestamp_non_numeric_is_false():
    assert is_timestamp_fresh("not-a-number") is False
