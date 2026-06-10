from app.gateway.tools.drive_tools import DRIVE_REGISTRY
from app.gateway.tools.slack_tools import SLACK_REGISTRY


def test_all_tool_handlers_are_wrapped_by_track_usage():
    registry = {**DRIVE_REGISTRY, **SLACK_REGISTRY}
    expected = {
        "drive-search-files",
        "drive-get-file-content",
        "drive-list-recent",
        "slack-send-message",
        "slack-search-messages",
    }
    assert set(registry) == expected
    for name, handler in registry.items():
        assert hasattr(handler, "__wrapped__"), f"{name} is not decorated with track_usage"
