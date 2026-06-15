from cryptography.fernet import Fernet

from app.integrations.google.tools import build_drive_registry
from app.integrations.slack.tools import build_slack_registry
from app.shared.http_client import HttpClient
from app.shared.store import InMemoryStore


def test_all_tool_handlers_are_wrapped_by_track_usage():
    fkey = Fernet(Fernet.generate_key())
    http = HttpClient()
    registry = {
        **build_drive_registry(
            drive_client=object(),
            token_store=InMemoryStore(),
            fernet=fkey,
            http_client=http,
            client_id="c",
            client_secret="s",
            redis=None,
        ),
        **build_slack_registry(slack_client=object(), token_store=InMemoryStore(), fernet=fkey, redis=None),
    }
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
