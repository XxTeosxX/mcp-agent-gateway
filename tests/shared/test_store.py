import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from app.shared.store import InMemoryStore, RedisStore


@pytest_asyncio.fixture
async def redis():
    client = FakeRedis(decode_responses=True)
    await client.flushall()
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_redisstore_set_get(redis):
    store = RedisStore(redis, "t:")
    await store.set("k", "v")
    assert await store.get("k") == "v"


@pytest.mark.asyncio
async def test_redisstore_get_missing_returns_none(redis):
    store = RedisStore(redis, "t:")
    assert await store.get("nope") is None


@pytest.mark.asyncio
async def test_redisstore_pop_is_atomic_getdel(redis):
    store = RedisStore(redis, "t:")
    await store.set("k", "v")
    assert await store.pop("k") == "v"
    assert await store.get("k") is None


@pytest.mark.asyncio
async def test_redisstore_prefix_isolates_keys(redis):
    a = RedisStore(redis, "a:")
    b = RedisStore(redis, "b:")
    await a.set("k", "va")
    await b.set("k", "vb")
    assert await a.get("k") == "va"
    assert await b.get("k") == "vb"


@pytest.mark.asyncio
async def test_redisstore_clear_only_own_prefix(redis):
    a = RedisStore(redis, "a:")
    b = RedisStore(redis, "b:")
    await a.set("k", "va")
    await b.set("k", "vb")
    await a.clear()
    assert await a.get("k") is None
    assert await b.get("k") == "vb"


@pytest.mark.asyncio
async def test_redisstore_set_with_ttl_sets_expiry(redis):
    store = RedisStore(redis, "t:")
    await store.set("k", "v", ttl=60)
    assert await redis.ttl("t:k") > 0


@pytest.mark.asyncio
async def test_redisstore_set_without_ttl_no_expiry(redis):
    store = RedisStore(redis, "t:")
    await store.set("k", "v")
    assert await redis.ttl("t:k") == -1


@pytest.mark.asyncio
async def test_inmemory_set_get_pop():
    store = InMemoryStore()
    await store.set("k", "v")
    assert await store.get("k") == "v"
    assert await store.pop("k") == "v"
    assert await store.get("k") is None


@pytest.mark.asyncio
async def test_inmemory_ttl_expires(monkeypatch):
    import app.shared.store as store_mod

    store = InMemoryStore()
    t = [1000.0]
    monkeypatch.setattr(store_mod.time, "time", lambda: t[0])
    await store.set("k", "v", ttl=10)
    t[0] = 1009.0
    assert await store.get("k") == "v"
    t[0] = 1011.0
    assert await store.get("k") is None
