from datetime import UTC, datetime, timedelta

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings

_FIELDS = "id,name,mimeType,webViewLink,modifiedTime"


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503)


def _retryable():
    return retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        stop=stop_after_attempt(settings.GOOGLE_DRIVE_MAX_RETRIES),
        reraise=True,
    )


class DriveClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def init(self) -> None:
        self._client = httpx.AsyncClient(
            base_url="https://www.googleapis.com",
            timeout=httpx.Timeout(settings.GOOGLE_DRIVE_TIMEOUT),
            limits=httpx.Limits(
                max_connections=settings.GOOGLE_DRIVE_MAX_CONNECTIONS,
                max_keepalive_connections=settings.GOOGLE_DRIVE_MAX_KEEPALIVE,
            ),
            verify=True,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("drive_client not initialized — call init() in lifespan")
        return self._client

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    async def search_files(
        self,
        token: str,
        query: str,
        max_results: int,
        mime_type: str | None,
    ) -> list[dict]:
        @_retryable()
        async def _call() -> list[dict]:
            q = query
            if mime_type:
                q = f"{q} and mimeType='{mime_type}'"
            resp = await self.get().get(
                "/drive/v3/files",
                headers=self._auth(token),
                params={"q": q, "pageSize": max_results, "fields": f"files({_FIELDS})"},
            )
            resp.raise_for_status()
            return resp.json().get("files", [])

        return await _call()

    async def get_file_content(self, token: str, file_id: str) -> dict:
        @_retryable()
        async def _call() -> dict:
            meta_resp = await self.get().get(
                f"/drive/v3/files/{file_id}",
                headers=self._auth(token),
                params={"fields": "id,name,mimeType"},
            )
            meta_resp.raise_for_status()
            meta = meta_resp.json()

            if meta["mimeType"].startswith("application/vnd.google-apps."):
                content_resp = await self.get().get(
                    f"/drive/v3/files/{file_id}/export",
                    headers=self._auth(token),
                    params={"mimeType": "text/plain"},
                )
            else:
                content_resp = await self.get().get(
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

        return await _call()

    async def list_recent(self, token: str, days: int, max_results: int) -> list[dict]:
        @_retryable()
        async def _call() -> list[dict]:
            since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
            resp = await self.get().get(
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

        return await _call()


drive_client = DriveClient()
