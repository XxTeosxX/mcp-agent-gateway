from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.mcp.server import build_mcp_server

_session_manager, handle_streamable_http = build_mcp_server()


@asynccontextmanager
async def mcp_lifespan() -> AsyncIterator[None]:
    async with _session_manager.run():
        yield
