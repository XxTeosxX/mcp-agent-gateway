import httpx

from app.shared.http_client import HttpClient


async def test_client_property_returns_async_client():
    hc = HttpClient(timeout=5.0)
    try:
        assert isinstance(hc.client, httpx.AsyncClient)
    finally:
        await hc.close()


async def test_close_is_idempotent():
    hc = HttpClient()
    await hc.close()
    await hc.close()  # second close must not raise
