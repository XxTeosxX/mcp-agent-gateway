import pytest

from app.shared.redis import get_redis


@pytest.mark.asyncio
async def test_get_redis_returns_pingable_client(monkeypatch):
    import app.shared.redis as redis_mod

    pinged = {"ok": False}

    class _Fake:
        async def ping(self):
            pinged["ok"] = True
            return True

    monkeypatch.setattr(redis_mod, "from_url", lambda url, **kw: _Fake())
    client = await get_redis("redis://x:6379/0")
    assert pinged["ok"] is True
    assert client is not None


@pytest.mark.asyncio
async def test_get_redis_propagates_ping_failure(monkeypatch):
    import app.shared.redis as redis_mod

    class _Fake:
        async def ping(self):
            raise ConnectionError("redis down")

    monkeypatch.setattr(redis_mod, "from_url", lambda url, **kw: _Fake())
    with pytest.raises(ConnectionError):
        await get_redis("redis://x:6379/0")
