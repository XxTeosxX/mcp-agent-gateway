import logging
from collections.abc import Callable

from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.gateway.context import current_user_scopes
from app.gateway.event_store import InMemoryEventStore
from app.gateway.tools.drive_tools import DRIVE_REGISTRY, DRIVE_REQUIRED_SCOPE, DRIVE_TOOLS
from app.gateway.tools.job_tools import JOB_REGISTRY, JOB_REQUIRED_SCOPE, JOB_TOOLS
from app.gateway.tools.slack_tools import SLACK_REGISTRY, SLACK_REQUIRED_SCOPE, SLACK_TOOLS

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


def _scope_ok(required: str | None, scopes: frozenset[str]) -> bool:
    return required is None or required in scopes


def visible_tools(scopes: frozenset[str]) -> list[types.Tool]:
    out: list[types.Tool] = []
    for tools, _registry, required in _GROUPS:
        if _scope_ok(required, scopes):
            out.extend(tools)
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

    return StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=InMemoryEventStore(),
        json_response=True,
    )
