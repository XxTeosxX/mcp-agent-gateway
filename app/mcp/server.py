import logging
from collections.abc import Callable

from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.integrations.google.job_tools import JOB_REQUIRED_SCOPE, JOB_TOOLS, build_job_registry
from app.integrations.google.prompts import (
    DRIVE_PROMPT_REGISTRY,
    DRIVE_PROMPT_REQUIRED_SCOPE,
    DRIVE_PROMPTS,
)
from app.integrations.google.tools import DRIVE_REQUIRED_SCOPE, DRIVE_TOOLS, build_drive_registry
from app.integrations.slack.tools import SLACK_REQUIRED_SCOPE, SLACK_TOOLS, build_slack_registry
from app.mcp.event_store import InMemoryEventStore
from app.shared.context import current_user_scopes

logger = logging.getLogger(__name__)

# (tools, required_scope) — required_scope=None means ungated.
_GROUPS: list[tuple[list[types.Tool], str | None]] = [
    (list(DRIVE_TOOLS), DRIVE_REQUIRED_SCOPE),
    (list(JOB_TOOLS), JOB_REQUIRED_SCOPE),
    (list(SLACK_TOOLS), SLACK_REQUIRED_SCOPE),
]

# tool name -> required scope (or None). Single source for filter + gate.
TOOL_SCOPE: dict[str, str | None] = {tool.name: required for tools, required in _GROUPS for tool in tools}

_PROMPT_GROUPS: list[tuple[list[types.Prompt], dict, str | None]] = [
    (list(DRIVE_PROMPTS), DRIVE_PROMPT_REGISTRY, DRIVE_PROMPT_REQUIRED_SCOPE),
]

PROMPT_SCOPE: dict[str, str | None] = {
    prompt.name: required for prompts, _registry, required in _PROMPT_GROUPS for prompt in prompts
}

_PROMPT_REGISTRY: dict[str, Callable] = {
    name: handler for _prompts, registry, _required in _PROMPT_GROUPS for name, handler in registry.items()
}


def _scope_ok(required: str | None, scopes: frozenset[str]) -> bool:
    return required is None or required in scopes


def visible_tools(scopes: frozenset[str]) -> list[types.Tool]:
    out: list[types.Tool] = []
    for tools, required in _GROUPS:
        if _scope_ok(required, scopes):
            out.extend(tools)
    return out


def visible_prompts(scopes: frozenset[str]) -> list[types.Prompt]:
    out: list[types.Prompt] = []
    for prompts, _registry, required in _PROMPT_GROUPS:
        if _scope_ok(required, scopes):
            out.extend(prompts)
    return out


async def handle_list_tools() -> list[types.Tool]:
    return visible_tools(current_user_scopes.get())


def _build_registry(
    *,
    redis,
    jobs_redis,
    http_client,
    drive_client,
    slack_client,
    google_token_store,
    slack_token_store,
    google_fernet,
    slack_fernet,
    google_client_id: str,
    google_client_secret: str,
) -> dict[str, Callable]:
    return {
        **build_drive_registry(
            drive_client=drive_client,
            token_store=google_token_store,
            fernet=google_fernet,
            http_client=http_client,
            client_id=google_client_id,
            client_secret=google_client_secret,
            redis=redis,
        ),
        **build_job_registry(redis=jobs_redis),
        **build_slack_registry(
            slack_client=slack_client,
            token_store=slack_token_store,
            fernet=slack_fernet,
            redis=redis,
        ),
    }


def create_session_manager(
    *,
    redis,
    jobs_redis,
    http_client,
    drive_client,
    slack_client,
    google_token_store,
    slack_token_store,
    google_fernet,
    slack_fernet,
    google_client_id: str,
    google_client_secret: str,
) -> StreamableHTTPSessionManager:
    registry = _build_registry(
        redis=redis,
        jobs_redis=jobs_redis,
        http_client=http_client,
        drive_client=drive_client,
        slack_client=slack_client,
        google_token_store=google_token_store,
        slack_token_store=slack_token_store,
        google_fernet=google_fernet,
        slack_fernet=slack_fernet,
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
    )

    mcp_server = Server("mcp-streamable-http-demo")

    @mcp_server.list_tools()
    async def _list() -> list[types.Tool]:
        return await handle_list_tools()

    @mcp_server.call_tool()
    async def _call(name: str, arguments: dict) -> types.CallToolResult:
        scopes = current_user_scopes.get()
        handler = registry.get(name)
        # Unknown tool AND scope-denied collapse to the same error: a caller
        # without the scope cannot tell the tool exists.
        if handler is None or not _scope_ok(TOOL_SCOPE.get(name), scopes):
            raise McpError(ErrorData(code=-32601, message=f"Unknown tool: {name}"))
        return await handler(arguments)

    @mcp_server.list_prompts()
    async def _list_prompts() -> list[types.Prompt]:
        return visible_prompts(current_user_scopes.get())

    @mcp_server.get_prompt()
    async def _get_prompt(name: str, arguments: dict | None) -> types.GetPromptResult:
        scopes = current_user_scopes.get()
        handler = _PROMPT_REGISTRY.get(name)
        # Same collapse as tools: unknown and scope-denied are indistinguishable.
        if handler is None or not _scope_ok(PROMPT_SCOPE.get(name), scopes):
            raise McpError(ErrorData(code=-32601, message=f"Unknown prompt: {name}"))
        return handler(arguments)

    return StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=InMemoryEventStore(),
        json_response=True,
    )
