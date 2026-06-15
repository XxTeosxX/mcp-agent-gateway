import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from app.integrations.slack.constants import SLACK_API_BASE


class SlackAPIError(Exception):
    pass


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503)


class SlackClient:
    def __init__(self, timeout: float, max_retries: int) -> None:
        self._client = httpx.AsyncClient(base_url=SLACK_API_BASE, timeout=httpx.Timeout(timeout), verify=True)
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

    async def post_message(self, bot_token: str, channel: str, text: str) -> dict:
        async for attempt in self._retrying():
            with attempt:
                resp = await self._client.post(
                    "/chat.postMessage",
                    headers=self._auth(bot_token),
                    data={"channel": channel, "text": text},
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    raise SlackAPIError(body.get("error", "unknown_error"))
                return {"ok": True, "channel": body["channel"], "ts": body["ts"]}

    async def search_messages(self, user_token: str, query: str, count: int) -> list[dict]:
        async for attempt in self._retrying():
            with attempt:
                resp = await self._client.get(
                    "/search.messages",
                    headers=self._auth(user_token),
                    params={"query": query, "count": count},
                )
                resp.raise_for_status()
                body = resp.json()
                if not body.get("ok"):
                    raise SlackAPIError(body.get("error", "unknown_error"))
                return body["messages"]["matches"]
