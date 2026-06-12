from app.gateway.context import current_user_scopes
from app.gateway.server import handle_list_tools


async def test_job_tools_are_listed():
    token = current_user_scopes.set(frozenset({"mcp:google:read"}))
    try:
        names = {t.name for t in await handle_list_tools()}
    finally:
        current_user_scopes.reset(token)
    assert {"drive-export-large-file", "wait-for-job"} <= names


async def test_job_handlers_in_session_registry():
    from app.gateway.server import _REGISTRY

    assert {"drive-export-large-file", "wait-for-job"} <= set(_REGISTRY)
