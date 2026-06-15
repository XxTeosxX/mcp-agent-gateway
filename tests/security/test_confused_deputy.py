from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from app.integrations.google.drive_client import drive_client
from app.integrations.google.tools import handle_drive_search_files
from app.integrations.slack.slack_client import slack_client
from app.integrations.slack.tools import handle_slack_send_message
from app.shared.context import current_user_id

GOOGLE_UPSTREAM_TOKEN = "ya29.GOOGLE_UPSTREAM_TOKEN_FOR_USER"
SLACK_BOT_TOKEN = "xoxb-slack-bot-token-xyz789"
DOWNSTREAM_JWT_LIKE = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyLTEyMyJ9.downstream-jwt-signature"


@pytest.fixture(autouse=True)
def _init_clients():
    drive_client.init()
    slack_client.init()
    yield


async def test_drive_tool_never_sends_downstream_jwt_upstream():
    current_user_id.set("user-123")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.get("https://www.googleapis.com/drive/v3/files").mock(
            return_value=Response(
                200,
                json={
                    "files": [
                        {
                            "id": "f1",
                            "name": "t.txt",
                            "mimeType": "text/plain",
                            "webViewLink": "",
                            "modifiedTime": "2026-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        )

        with patch(
            "app.integrations.google.tools._get_drive_token",
            new_callable=AsyncMock,
            return_value=GOOGLE_UPSTREAM_TOKEN,
        ):
            result = await handle_drive_search_files({"query": "test", "max_results": 5})

    assert not result.isError
    assert route.called
    for call in route.calls:
        auth = call.request.headers.get("authorization", "")
        assert GOOGLE_UPSTREAM_TOKEN in auth, f"Expected upstream token in upstream request, got: {auth}"
        assert DOWNSTREAM_JWT_LIKE not in auth, "CONFUSED DEPUTY: downstream JWT was forwarded to upstream Google API"


async def test_slack_tool_never_sends_downstream_jwt_upstream():
    current_user_id.set("user-456")

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://slack.com/api/chat.postMessage").mock(
            return_value=Response(200, json={"ok": True, "channel": "C123", "ts": "1234.5678"})
        )

        with patch(
            "app.integrations.slack.tools._get_slack_token",
            new_callable=AsyncMock,
            return_value=SLACK_BOT_TOKEN,
        ):
            result = await handle_slack_send_message({"channel": "C123", "text": "hello"})

    assert not result.isError
    assert route.called
    for call in route.calls:
        auth = call.request.headers.get("authorization", "")
        assert SLACK_BOT_TOKEN in auth, f"Expected upstream bot token in upstream request, got: {auth}"
        assert DOWNSTREAM_JWT_LIKE not in auth, "CONFUSED DEPUTY: downstream JWT was forwarded to upstream Slack API"
