from cryptography.fernet import Fernet

from app.integrations.google.drive_client import DriveClient
from app.integrations.slack.slack_client import SlackClient
from app.mcp.server import _build_registry, handle_list_tools
from app.shared.context import current_user_scopes
from app.shared.http_client import HttpClient
from app.shared.store import InMemoryStore


async def test_job_tools_are_listed():
    token = current_user_scopes.set(frozenset({"mcp:google:read"}))
    try:
        names = {t.name for t in await handle_list_tools()}
    finally:
        current_user_scopes.reset(token)
    assert {"drive-export-large-file", "wait-for-job"} <= names


async def test_job_handlers_in_session_registry():
    fkey = Fernet(Fernet.generate_key())
    registry = _build_registry(
        redis=InMemoryStore(),
        jobs_redis=InMemoryStore(),
        http_client=HttpClient(),
        drive_client=DriveClient(timeout=10.0, max_connections=10, max_keepalive=5, max_retries=3),
        slack_client=SlackClient(timeout=10.0, max_retries=3),
        google_token_store=InMemoryStore(),
        slack_token_store=InMemoryStore(),
        google_fernet=fkey,
        slack_fernet=fkey,
        google_client_id="cid",
        google_client_secret="secret",
    )
    assert {"drive-export-large-file", "wait-for-job"} <= set(registry)
