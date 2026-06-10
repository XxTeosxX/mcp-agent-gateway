import pytest

from app.gateway.server import handle_list_tools


@pytest.mark.asyncio
async def test_list_tools_includes_slack():
    names = {t.name for t in await handle_list_tools()}
    assert "slack-send-message" in names
    assert "slack-search-messages" in names
    assert "drive-search-files" in names


def test_dependency_getter_imports():
    from app.shared.dependencies import get_slack_token_store

    assert callable(get_slack_token_store)


def test_router_has_slack_routes():
    from app.authorization.router import router

    paths = {r.path for r in router.routes}
    assert "/auth/slack/initiate" in paths
    assert "/auth/slack/callback" in paths
