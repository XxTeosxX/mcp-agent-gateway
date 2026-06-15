import math

import pytest
from fakeredis.aioredis import FakeRedis

from app.middleware.rate_limiter import check_rate_limit


@pytest.fixture
def redis():
    return FakeRedis(decode_responses=True)


async def test_allows_up_to_limit_then_denies(redis):
    key = "ratelimit:u1"
    for i in range(3):
        result = await check_rate_limit(redis, key, limit=3, window=60)
        assert result.allowed is True, f"request {i + 1} should be allowed"
    denied = await check_rate_limit(redis, key, limit=3, window=60)
    assert denied.allowed is False


async def test_denied_has_positive_retry_after(redis):
    key = "ratelimit:u1"
    for _ in range(2):
        await check_rate_limit(redis, key, limit=2, window=60)
    denied = await check_rate_limit(redis, key, limit=2, window=60)
    assert denied.allowed is False
    assert denied.retry_after_seconds > 0


async def test_first_request_sets_ttl(redis):
    key = "ratelimit:u1"
    await check_rate_limit(redis, key, limit=5, window=60)
    ttl = await redis.pttl(key)
    assert ttl > 0


async def test_new_window_after_expiry(redis):
    key = "ratelimit:u1"
    for _ in range(2):
        await check_rate_limit(redis, key, limit=2, window=60)
    assert (await check_rate_limit(redis, key, 2, 60)).allowed is False
    await redis.delete(key)
    assert (await check_rate_limit(redis, key, 2, 60)).allowed is True


async def test_retry_after_is_ceil_of_ttl(redis):
    key = "ratelimit:u1"
    await check_rate_limit(redis, key, limit=1, window=60)
    denied = await check_rate_limit(redis, key, limit=1, window=60)
    ttl_ms = await redis.pttl(key)
    assert denied.retry_after_seconds in (math.ceil(ttl_ms / 1000), math.ceil(ttl_ms / 1000) + 1)
    assert 0 < denied.retry_after_seconds <= 60
