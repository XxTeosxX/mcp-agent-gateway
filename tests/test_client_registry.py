import fakeredis.aioredis
import pytest

from app.client_registry import get
from app.client_registry import set as registry_set
from app.dcr import DcrResult

_RESULT = DcrResult(client_id="kc-abc", client_secret="secret-xyz")
_URL = "https://myapp.com/client-metadata.json"


@pytest.fixture
def fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


class TestClientRegistry:
    async def test_get_returns_none_when_not_cached(self, fake_redis):
        result = await get(_URL, redis=fake_redis)
        assert result is None

    async def test_set_then_get_returns_result(self, fake_redis):
        await registry_set(_URL, _RESULT, redis=fake_redis)
        result = await get(_URL, redis=fake_redis)
        assert result is not None
        assert result.client_id == "kc-abc"
        assert result.client_secret == "secret-xyz"

    async def test_different_urls_do_not_collide(self, fake_redis):
        other = DcrResult(client_id="other-id", client_secret="other-secret")
        await registry_set(_URL, _RESULT, redis=fake_redis)
        await registry_set("https://otherapp.com/meta.json", other, redis=fake_redis)

        r1 = await get(_URL, redis=fake_redis)
        r2 = await get("https://otherapp.com/meta.json", redis=fake_redis)
        assert r1.client_id == "kc-abc"
        assert r2.client_id == "other-id"

    async def test_get_returns_none_when_redis_unavailable(self):
        result = await get(_URL, redis=None)
        assert result is None

    async def test_set_silently_fails_when_redis_unavailable(self):
        await registry_set(_URL, _RESULT, redis=None)
