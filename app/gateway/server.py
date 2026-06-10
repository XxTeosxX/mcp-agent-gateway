import logging
from collections.abc import Callable

from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.gateway.event_store import InMemoryEventStore
from app.gateway.tools.drive_tools import DRIVE_REGISTRY, DRIVE_TOOLS
from app.gateway.tools.slack_tools import SLACK_REGISTRY, SLACK_TOOLS

logger = logging.getLogger(__name__)


async def handle_list_tools() -> list[types.Tool]:
    return list(DRIVE_TOOLS) + list(SLACK_TOOLS)


def create_session_manager() -> StreamableHTTPSessionManager:
    mcp_server = Server("mcp-streamable-http-demo")

    _registry: dict[str, Callable] = {**DRIVE_REGISTRY, **SLACK_REGISTRY}

    @mcp_server.list_tools()
    async def _list() -> list[types.Tool]:
        return await handle_list_tools()

    @mcp_server.call_tool()
    async def _call(name: str, arguments: dict) -> types.CallToolResult:
        handler = _registry.get(name)
        if handler is None:
            raise McpError(ErrorData(code=-32601, message=f"Unknown tool: {name}"))
        return await handler(arguments)

    return StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=InMemoryEventStore(),
        json_response=True,
    )
