import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import settings
from app.integrations.slack.constants import SLACK_API_BASE


class SlackAPIError(Exception):
    pass


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503)


def _retryable():
    return retry(
        retry=retry_if_exception(_is_retryable),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        stop=stop_after_attempt(settings.SLACK_MAX_RETRIES),
        reraise=True,
    )


class SlackClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    def init(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=SLACK_API_BASE,
            timeout=httpx.Timeout(settings.SLACK_TIMEOUT),
            verify=True,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def get(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("slack_client not initialized — call init() in lifespan")
        return self._client

    def _auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    async def post_message(self, bot_token: str, channel: str, text: str) -> dict:
        @_retryable()
        async def _call() -> dict:
            resp = await self.get().post(
                "/chat.postMessage",
                headers=self._auth(bot_token),
                data={"channel": channel, "text": text},
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                raise SlackAPIError(body.get("error", "unknown_error"))
            return {"ok": True, "channel": body["channel"], "ts": body["ts"]}

        return await _call()

    async def search_messages(self, user_token: str, query: str, count: int) -> list[dict]:
        @_retryable()
        async def _call() -> list[dict]:
            resp = await self.get().get(
                "/search.messages",
                headers=self._auth(user_token),
                params={"query": query, "count": count},
            )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                raise SlackAPIError(body.get("error", "unknown_error"))
            return body["messages"]["matches"]

        return await _call()


slack_client = SlackClient()
