from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from app.gateway.server import create_session_manager

_session_manager = create_session_manager()


class MCPApp:
    def __init__(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._manager.handle_request(scope, receive, send)


mcp_app = MCPApp(_session_manager)


@asynccontextmanager
async def mcp_lifespan() -> AsyncIterator[None]:
    async with _session_manager.run():
        yield
