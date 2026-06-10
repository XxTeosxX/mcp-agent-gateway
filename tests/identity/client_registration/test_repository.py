import pytest

from app.identity.client_registration.models import RegisteredClient
from app.identity.client_registration.repository import get, set as registry_set
from app.shared.store import InMemoryStore

_RESULT = RegisteredClient(client_id="kc-abc", client_secret="secret-xyz")
_URL = "https://myapp.com/client-metadata.json"


@pytest.fixture
def store():
    return InMemoryStore()


class TestClientRegistry:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_cached(self, store):
        assert await get(_URL, store) is None

    @pytest.mark.asyncio
    async def test_set_then_get_returns_result(self, store):
        await registry_set(_URL, _RESULT, store)
        result = await get(_URL, store)
        assert result is not None
        assert result.client_id == "kc-abc"
        assert result.client_secret == "secret-xyz"

    @pytest.mark.asyncio
    async def test_different_urls_do_not_collide(self, store):
        other = RegisteredClient(client_id="other-id", client_secret="other-secret")
        await registry_set(_URL, _RESULT, store)
        await registry_set("https://otherapp.com/meta.json", other, store)
        r1 = await get(_URL, store)
        r2 = await get("https://otherapp.com/meta.json", store)
        assert r1.client_id == "kc-abc"
        assert r2.client_id == "other-id"
