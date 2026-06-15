import hashlib
import hmac
import json
import time

import httpx
from fakeredis.aioredis import FakeRedis

from app.main import app

_SECRET = "test-signing-secret"


def _sign(timestamp: str, raw: bytes) -> str:
    base = b"v0:" + timestamp.encode() + b":" + raw
    return "v0=" + hmac.new(_SECRET.encode(), base, hashlib.sha256).hexdigest()


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _headers(raw: bytes, *, ts: str | None = None, sig: str | None = None) -> dict:
    ts = ts if ts is not None else str(int(time.time()))
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig if sig is not None else _sign(ts, raw),
        "Content-Type": "application/json",
    }


async def test_valid_event_published(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "event_callback", "event_id": "Ev123", "event": {"type": "message"}}).encode()

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))

    assert resp.status_code == 200
    entries = await redis.xrange("events:slack")
    assert len(entries) == 1
    _id, fields = entries[0]
    assert fields["event_id"] == "Ev123"
    assert fields["type"] == "event_callback"
    assert json.loads(fields["payload"])["event"]["type"] == "message"
    assert await redis.get("webhook:slack:Ev123") == "1"


async def test_duplicate_event_published_once(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "event_callback", "event_id": "EvDup"}).encode()

    async with _client() as ac:
        r1 = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))
        r2 = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))

    assert r1.status_code == 200 and r2.status_code == 200
    assert await redis.xlen("events:slack") == 1


async def test_bad_signature_rejected_nothing_published(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "event_callback", "event_id": "EvBad"}).encode()

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw, sig="v0=deadbeef"))

    assert resp.status_code == 401
    assert await redis.xlen("events:slack") == 0


async def test_stale_timestamp_rejected(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "event_callback", "event_id": "EvOld"}).encode()
    old_ts = str(int(time.time()) - 600)

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw, ts=old_ts))

    assert resp.status_code == 401
    assert await redis.xlen("events:slack") == 0


async def test_url_verification_echoes_challenge(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode()

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))

    assert resp.status_code == 200
    assert resp.json()["challenge"] == "abc123"
    assert await redis.xlen("events:slack") == 0


async def test_no_bearer_required(monkeypatch):

    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "event_callback", "event_id": "EvAuth"}).encode()

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))

    assert resp.status_code == 200


async def test_non_object_json_returns_400(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", _SECRET)
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = b"[1, 2, 3]"

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))

    assert resp.status_code == 400
    assert await redis.xlen("events:slack") == 0


async def test_unconfigured_secret_returns_503(monkeypatch):
    monkeypatch.setattr("app.config.settings.SLACK_SIGNING_SECRET", "")
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    raw = json.dumps({"type": "event_callback", "event_id": "EvNoCfg"}).encode()

    async with _client() as ac:
        resp = await ac.post("/webhooks/slack", content=raw, headers=_headers(raw))

    assert resp.status_code == 503
