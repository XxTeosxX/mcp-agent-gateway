import logging
from collections.abc import Callable

from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.integrations.google.job_tools import JOB_REGISTRY, JOB_REQUIRED_SCOPE, JOB_TOOLS
from app.integrations.google.prompts import (
    DRIVE_PROMPT_REGISTRY,
    DRIVE_PROMPT_REQUIRED_SCOPE,
    DRIVE_PROMPTS,
)
from app.integrations.google.tools import DRIVE_REGISTRY, DRIVE_REQUIRED_SCOPE, DRIVE_TOOLS
from app.integrations.slack.tools import SLACK_REGISTRY, SLACK_REQUIRED_SCOPE, SLACK_TOOLS
from app.mcp.event_store import InMemoryEventStore
from app.shared.context import current_user_scopes

logger = logging.getLogger(__name__)

# (tools, registry, required_scope) — required_scope=None means ungated.
_GROUPS: list[tuple[list[types.Tool], dict[str, Callable], str | None]] = [
    (list(DRIVE_TOOLS), DRIVE_REGISTRY, DRIVE_REQUIRED_SCOPE),
    (list(JOB_TOOLS), JOB_REGISTRY, JOB_REQUIRED_SCOPE),
    (list(SLACK_TOOLS), SLACK_REGISTRY, SLACK_REQUIRED_SCOPE),
]

# tool name -> required scope (or None). Single source for filter + gate.
TOOL_SCOPE: dict[str, str | None] = {tool.name: required for tools, _registry, required in _GROUPS for tool in tools}

_REGISTRY: dict[str, Callable] = {
    name: handler for _tools, registry, _required in _GROUPS for name, handler in registry.items()
}


# (prompts, registry, required_scope) — same scope-gating model as tools.
_PROMPT_GROUPS: list[tuple[list[types.Prompt], dict[str, Callable], str | None]] = [
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
    for tools, _registry, required in _GROUPS:
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


def create_session_manager() -> StreamableHTTPSessionManager:
    mcp_server = Server("mcp-streamable-http-demo")

    @mcp_server.list_tools()
    async def _list() -> list[types.Tool]:
        return await handle_list_tools()

    @mcp_server.call_tool()
    async def _call(name: str, arguments: dict) -> types.CallToolResult:
        scopes = current_user_scopes.get()
        handler = _REGISTRY.get(name)
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
