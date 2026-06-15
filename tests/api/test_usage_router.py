import time

import httpx
from fakeredis.aioredis import FakeRedis

from app.main import app
from tests.conftest import make_token


async def _seed(redis, user_id, *, tool="drive-search-files", in_tokens=10, out_tokens=20, ts=None):
    await redis.xadd(
        f"usage:{user_id}",
        {
            "ts": str(ts if ts is not None else time.time()),
            "tool": tool,
            "in_tokens": str(in_tokens),
            "out_tokens": str(out_tokens),
        },
    )


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_usage_returns_aggregated_events(rsa_key):
    redis = FakeRedis(decode_responses=True)
    await _seed(redis, "user-123", in_tokens=10, out_tokens=20)
    await _seed(redis, "user-123", in_tokens=5, out_tokens=7)
    app.state.redis = redis
    headers = {"Authorization": f"Bearer {make_token(rsa_key, scope='mcp:admin:read')}"}

    async with _client() as ac:
        resp = await ac.get("/admin/usage/user-123", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert body["total_in_tokens"] == 15
    assert body["total_out_tokens"] == 27
    assert len(body["events"]) == 2


async def test_usage_hours_filter_excludes_old(rsa_key):
    redis = FakeRedis(decode_responses=True)
    await _seed(redis, "user-123", in_tokens=10, out_tokens=20)
    await _seed(redis, "user-123", in_tokens=99, out_tokens=99, ts=time.time() - 48 * 3600)
    app.state.redis = redis
    headers = {"Authorization": f"Bearer {make_token(rsa_key, scope='mcp:admin:read')}"}

    async with _client() as ac:
        resp = await ac.get("/admin/usage/user-123?hours=24", headers=headers)

    body = resp.json()
    assert body["count"] == 1
    assert body["total_in_tokens"] == 10
    assert body["total_out_tokens"] == 20


async def test_usage_requires_admin_scope(rsa_key):
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis
    headers = {"Authorization": f"Bearer {make_token(rsa_key, scope='mcp:tools:read')}"}

    async with _client() as ac:
        resp = await ac.get("/admin/usage/user-123", headers=headers)

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing scope: mcp:admin:read"


async def test_usage_requires_authentication(rsa_key):
    redis = FakeRedis(decode_responses=True)
    app.state.redis = redis

    async with _client() as ac:
        resp = await ac.get("/admin/usage/user-123")

    assert resp.status_code == 401
