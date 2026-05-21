import httpx


class HttpClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def init(self) -> None:
        self._client = httpx.AsyncClient(timeout=10.0, verify=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("http_client not initialized — call init() in lifespan")
        return self._client
