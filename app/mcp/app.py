from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from app.mcp.server import create_session_manager


class MCPApp:
    def __init__(self) -> None:
        self._manager: StreamableHTTPSessionManager | None = None

    def set_manager(self, manager: StreamableHTTPSessionManager) -> None:
        self._manager = manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._manager is None:
            raise RuntimeError("mcp_app: session manager not initialized")
        await self._manager.handle_request(scope, receive, send)


mcp_app = MCPApp()


@asynccontextmanager
async def mcp_lifespan(
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
) -> AsyncIterator[None]:
    manager = create_session_manager(
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
    mcp_app.set_manager(manager)
    async with manager.run():
        yield
