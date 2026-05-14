import logging
from collections.abc import Callable

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from .event_store import InMemoryEventStore

logger = logging.getLogger(__name__)


async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="start-notification-stream",
            description="Sends a stream of notifications with configurable count and interval",
            inputSchema={
                "type": "object",
                "required": ["interval", "count", "caller"],
                "properties": {
                    "interval": {
                        "type": "number",
                        "description": "Interval between notifications in seconds",
                    },
                    "count": {
                        "type": "number",
                        "description": "Number of notifications to send",
                    },
                    "caller": {
                        "type": "string",
                        "description": "Identifier of the caller to include in notifications",
                    },
                },
            },
        )
    ]


async def handle_call_tool(server: Server, name: str, arguments: dict) -> list[types.TextContent]:
    interval = arguments.get("interval", 1.0)
    count = arguments.get("count", 5)
    caller = arguments.get("caller", "unknown")

    for i in range(count):
        notification_msg = f"[{i + 1}/{count}] Event from '{caller}' - Use Last-Event-ID to resume if disconnected"
        ctx = server.request_context
        await ctx.session.send_log_message(
            level="info",
            data=notification_msg,
            logger="notification_stream",
            related_request_id=ctx.request_id,
        )
        logger.debug(f"Sent notification {i + 1}/{count} for caller: {caller}")
        if i < count - 1:
            await anyio.sleep(interval)

    await server.request_context.session.send_resource_updated(uri="http:///test_resource")
    return [
        types.TextContent(
            type="text",
            text=f"Sent {count} notifications with {interval}s interval for caller: {caller}",
        )
    ]


def build_mcp_server() -> tuple[
    StreamableHTTPSessionManager,
    Callable[[Scope, Receive, Send], None],
]:
    mcp_server = Server("mcp-streamable-http-demo")

    @mcp_server.list_tools()
    async def _list() -> list[types.Tool]:
        return await handle_list_tools()

    @mcp_server.call_tool()
    async def _call(name: str, arguments: dict) -> list[types.TextContent]:
        return await handle_call_tool(mcp_server, name, arguments)

    event_store = InMemoryEventStore()

    json_response = True
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=event_store,
        json_response=json_response,
    )

    async def handle_streamable_http(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    return session_manager, handle_streamable_http
