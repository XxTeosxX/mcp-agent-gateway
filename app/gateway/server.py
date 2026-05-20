import json
import logging

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from app.gateway.event_store import InMemoryEventStore

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
        ),
        types.Tool(
            name="health-check",
            description="Returns health status of the MCP server",
            inputSchema={
                "type": "object",
                "properties": {},
            },
            outputSchema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["ok", "degraded", "error"],
                        "description": "Overall health status",
                    },
                    "redis": {
                        "type": "boolean",
                        "description": "Redis connection status",
                    },
                    "version": {
                        "type": "string",
                        "description": "Server version",
                    },
                },
                "required": ["status", "redis", "version"],
            },
            annotations=types.ToolAnnotations(
                readOnlyHint=True,
            ),
        ),
    ]


async def handle_start_notification_stream(server: Server, name: str, arguments: dict) -> types.CallToolResult:
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
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=f"Sent {count} notifications with {interval}s interval for caller: {caller}",
            )
        ],
    )


async def handle_health_check() -> types.CallToolResult:
    health_data = {"status": "ok", "redis": False, "version": "1.27.1"}
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text",
                text=json.dumps(health_data),
            )
        ],
        structuredContent=health_data,
    )


def create_session_manager() -> StreamableHTTPSessionManager:
    mcp_server = Server("mcp-streamable-http-demo")

    @mcp_server.list_tools()
    async def _list() -> list[types.Tool]:
        return await handle_list_tools()

    @mcp_server.call_tool()
    async def _call(name: str, arguments: dict) -> types.CallToolResult:
        if name == "health-check":
            return await handle_health_check()

        if name == "start-notification-stream":
            return await handle_start_notification_stream(mcp_server, name, arguments)

    return StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=InMemoryEventStore(),
        json_response=True,
    )
