from datetime import UTC, datetime, timedelta

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

_FIELDS = "id,name,mimeType,webViewLink,modifiedTime"


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503)


class DriveClient:
    def __init__(self, timeout: float, max_connections: int, max_keepalive: int, max_retries: int) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://www.googleapis.com",
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_keepalive),
            verify=True,
        )
        self._max_retries = max_retries

    async def close(self) -> None:
        await self._client.aclose()

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential(multiplier=1, min=1, max=16),
            stop=stop_after_attempt(self._max_retries),
            reraise=True,
        )

    async def search_files(
        self,
        token: str,
        q: str,
        max_results: int,
    ) -> list[dict]:
        async for attempt in self._retrying():
            with attempt:
                resp = await self._client.get(
                    "/drive/v3/files",
                    headers=self._auth(token),
                    params={"q": q, "pageSize": max_results, "fields": f"files({_FIELDS})"},
                )
                resp.raise_for_status()
                return resp.json().get("files", [])

    async def get_file_content(self, token: str, file_id: str) -> dict:
        async for attempt in self._retrying():
            with attempt:
                meta_resp = await self._client.get(
                    f"/drive/v3/files/{file_id}",
                    headers=self._auth(token),
                    params={"fields": "id,name,mimeType"},
                )
                meta_resp.raise_for_status()
                meta = meta_resp.json()

                if meta["mimeType"].startswith("application/vnd.google-apps."):
                    content_resp = await self._client.get(
                        f"/drive/v3/files/{file_id}/export",
                        headers=self._auth(token),
                        params={"mimeType": "text/plain"},
                    )
                else:
                    content_resp = await self._client.get(
                        f"/drive/v3/files/{file_id}",
                        headers=self._auth(token),
                        params={"alt": "media"},
                    )
                content_resp.raise_for_status()

                return {
                    "file_id": meta["id"],
                    "name": meta["name"],
                    "content": content_resp.text,
                    "mime_type": meta["mimeType"],
                }

    async def export_file(self, token: str, file_id: str, export_mime: str) -> bytes:
        async for attempt in self._retrying():
            with attempt:
                resp = await self._client.get(
                    f"/drive/v3/files/{file_id}/export",
                    headers=self._auth(token),
                    params={"mimeType": export_mime},
                )
                resp.raise_for_status()
                return resp.content

    async def list_recent(self, token: str, days: int, max_results: int) -> list[dict]:
        async for attempt in self._retrying():
            with attempt:
                since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
                resp = await self._client.get(
                    "/drive/v3/files",
                    headers=self._auth(token),
                    params={
                        "q": f"modifiedTime > '{since}'",
                        "pageSize": max_results,
                        "orderBy": "modifiedTime desc",
                        "fields": f"files({_FIELDS})",
                    },
                )
                resp.raise_for_status()
                return resp.json().get("files", [])
