import json
import logging
from collections.abc import Awaitable, Callable

from mcp import types
from pydantic import BaseModel, Field, ValidationError

from app.gateway.context import current_user_id
from app.gateway.usage import track_usage
from app.integrations.slack.slack_client import SlackAPIError, slack_client as _slack_client
from app.integrations.slack.token_store import SlackTokenNotFoundError, get_valid_slack_token
from app.shared.store import slack_token_store

logger = logging.getLogger(__name__)


class SlackSendInput(BaseModel):
    channel: str
    text: str


class SlackSearchInput(BaseModel):
    query: str
    count: int = Field(default=20, ge=1, le=100)


class SlackSendResult(BaseModel):
    ok: bool
    channel: str
    ts: str


class SlackSearchMatch(BaseModel):
    text: str
    channel: str
    user: str
    ts: str
    permalink: str


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        isError=True,
        content=[types.TextContent(type="text", text=message)],
    )


def _ok(data) -> types.CallToolResult:
    text = json.dumps(data) if not isinstance(data, str) else data
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)])


def _to_match(m: dict) -> dict:
    ch = m.get("channel", {})
    channel = ch.get("name", ch.get("id", "")) if isinstance(ch, dict) else str(ch)
    return SlackSearchMatch(
        text=m.get("text", ""),
        channel=channel,
        user=m.get("user", ""),
        ts=m.get("ts", ""),
        permalink=m.get("permalink", ""),
    ).model_dump()


_NOT_AUTHORIZED = "Slack not authorized. Call POST /auth/slack/initiate to authorize your account."


async def _get_slack_token(token_type: str) -> str | types.CallToolResult:
    try:
        return await get_valid_slack_token(current_user_id.get(), token_type, slack_token_store.get())
    except SlackTokenNotFoundError:
        return _error(_NOT_AUTHORIZED)


@track_usage("slack-send-message")
async def handle_slack_send_message(arguments: dict) -> types.CallToolResult:
    try:
        args = SlackSendInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    token = await _get_slack_token("bot")
    if isinstance(token, types.CallToolResult):
        return token

    try:
        result = await _slack_client.post_message(token, args.channel, args.text)
    except SlackAPIError as exc:
        return _error(f"Slack error: {exc}")
    return _ok(SlackSendResult(**result).model_dump())


@track_usage("slack-search-messages")
async def handle_slack_search_messages(arguments: dict) -> types.CallToolResult:
    try:
        args = SlackSearchInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    token = await _get_slack_token("user")
    if isinstance(token, types.CallToolResult):
        return token

    try:
        matches = await _slack_client.search_messages(token, args.query, args.count)
    except SlackAPIError as exc:
        return _error(f"Slack error: {exc}")
    return _ok([_to_match(m) for m in matches])


SLACK_TOOLS: list[types.Tool] = [
    types.Tool(
        name="slack-send-message",
        description="Post a message to a Slack channel as the bot. The bot must be a member of the channel.",
        inputSchema={
            "type": "object",
            "required": ["channel", "text"],
            "properties": {
                "channel": {"type": "string", "description": "Channel ID (e.g. 'C0123ABCD') or name"},
                "text": {"type": "string", "description": "Message text"},
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=False),
    ),
    types.Tool(
        name="slack-search-messages",
        description="Search messages across the user's Slack workspace using Slack search syntax.",
        inputSchema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g. 'deploy in:#ops')"},
                "count": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
        },
        annotations=types.ToolAnnotations(readOnlyHint=True),
    ),
]

SLACK_REGISTRY: dict[str, Callable[[dict], Awaitable[types.CallToolResult]]] = {
    "slack-send-message": handle_slack_send_message,
    "slack-search-messages": handle_slack_search_messages,
}
