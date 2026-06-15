import pytest

from app.mcp.server import handle_list_tools
from app.shared.context import current_user_scopes


@pytest.mark.asyncio
async def test_list_tools_includes_slack():
    token = current_user_scopes.set(frozenset({"mcp:google:read", "mcp:slack:read"}))
    try:
        names = {t.name for t in await handle_list_tools()}
    finally:
        current_user_scopes.reset(token)
    assert "slack-send-message" in names
    assert "slack-search-messages" in names
    assert "drive-search-files" in names


def test_router_has_no_slack_oauth_routes():
    # 3-legged Slack OAuth removed — only the shared-token model remains.
    from app.authorization.router import router

    paths = {r.path for r in router.routes}
    assert "/auth/slack/initiate" not in paths
    assert "/auth/slack/callback" not in paths
