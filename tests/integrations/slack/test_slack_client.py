import httpx
import pytest
import respx

from app.integrations.slack.constants import SLACK_API_BASE
from app.integrations.slack.slack_client import SlackAPIError, SlackClient


@pytest.fixture
async def slack_client():
    sc = SlackClient(timeout=10.0, max_retries=3)
    yield sc
    await sc.close()


@pytest.mark.asyncio
@respx.mock
async def test_post_message_success(slack_client):
    respx.post(f"{SLACK_API_BASE}/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "1.2"})
    )
    result = await slack_client.post_message("xoxb-bot", "C1", "hello")
    assert result == {"ok": True, "channel": "C1", "ts": "1.2"}


@pytest.mark.asyncio
@respx.mock
async def test_post_message_ok_false_raises(slack_client):
    respx.post(f"{SLACK_API_BASE}/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "not_in_channel"})
    )
    with pytest.raises(SlackAPIError, match="not_in_channel"):
        await slack_client.post_message("xoxb-bot", "C1", "hi")


@pytest.mark.asyncio
@respx.mock
async def test_search_messages_returns_matches(slack_client):
    respx.get(f"{SLACK_API_BASE}/search.messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "messages": {"matches": [{"text": "found it", "ts": "9.9"}]},
            },
        )
    )
    matches = await slack_client.search_messages("xoxp-user", "found", 20)
    assert matches == [{"text": "found it", "ts": "9.9"}]


@pytest.mark.asyncio
@respx.mock
async def test_search_messages_ok_false_raises(slack_client):
    respx.get(f"{SLACK_API_BASE}/search.messages").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "not_authed"})
    )
    with pytest.raises(SlackAPIError, match="not_authed"):
        await slack_client.search_messages("xoxp-user", "query", 10)


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_429_then_succeeds(slack_client):
    route = respx.post(f"{SLACK_API_BASE}/chat.postMessage")
    route.side_effect = [
        httpx.Response(429),
        httpx.Response(200, json={"ok": True, "channel": "C1", "ts": "1.2"}),
    ]
    result = await slack_client.post_message("xoxb-bot", "C1", "hello")
    assert result["ts"] == "1.2"
    assert route.call_count == 2
