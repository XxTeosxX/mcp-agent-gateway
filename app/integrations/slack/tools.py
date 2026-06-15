import json
import logging
from collections.abc import Awaitable, Callable
from functools import partial

from cryptography.fernet import Fernet
from mcp import types
from pydantic import BaseModel, Field, ValidationError

from app.integrations.slack.slack_client import SlackAPIError, SlackClient
from app.integrations.slack.token_store import (
    _SLACK_SHARED_USER,
    SlackTokenNotFoundError,
    get_valid_slack_token,
)
from app.shared.store import Store
from app.shared.usage import track_usage

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


_NOT_AUTHORIZED = "Slack is not authorized. Provision SLACK_SHARED_BOT_TOKEN / SLACK_SHARED_USER_TOKEN (see README)."


async def _get_slack_token(token_type, slack_client, token_store, fernet) -> str | types.CallToolResult:
    try:
        return await get_valid_slack_token(_SLACK_SHARED_USER, token_type, token_store, fernet)
    except SlackTokenNotFoundError:
        return _error(_NOT_AUTHORIZED)


async def handle_slack_send_message(
    arguments: dict, *, slack_client: SlackClient, token_store: Store, fernet: Fernet
) -> types.CallToolResult:
    try:
        args = SlackSendInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    token = await _get_slack_token("bot", slack_client, token_store, fernet)
    if isinstance(token, types.CallToolResult):
        return token

    try:
        result = await slack_client.post_message(token, args.channel, args.text)
    except SlackAPIError as exc:
        return _error(f"Slack error: {exc}")
    return _ok(SlackSendResult(**result).model_dump())


async def handle_slack_search_messages(
    arguments: dict, *, slack_client: SlackClient, token_store: Store, fernet: Fernet
) -> types.CallToolResult:
    try:
        args = SlackSearchInput(**arguments)
    except ValidationError as exc:
        return _error(f"Invalid input: {exc.errors()[0]['loc'][0]} — {exc.errors()[0]['msg']}")

    token = await _get_slack_token("user", slack_client, token_store, fernet)
    if isinstance(token, types.CallToolResult):
        return token

    try:
        matches = await slack_client.search_messages(token, args.query, args.count)
    except SlackAPIError as exc:
        return _error(f"Slack error: {exc}")
    return _ok([_to_match(m) for m in matches])


SLACK_REQUIRED_SCOPE = "mcp:slack:read"

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


def build_slack_registry(
    *, slack_client: SlackClient, token_store: Store, fernet: Fernet, redis
) -> dict[str, Callable[[dict], Awaitable[types.CallToolResult]]]:
    deps = dict(slack_client=slack_client, token_store=token_store, fernet=fernet)
    handlers = {
        "slack-send-message": partial(handle_slack_send_message, **deps),
        "slack-search-messages": partial(handle_slack_search_messages, **deps),
    }
    return {name: track_usage(name, redis)(h) for name, h in handlers.items()}
