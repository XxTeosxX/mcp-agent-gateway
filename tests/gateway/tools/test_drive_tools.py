import json
import time

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

from app.config import settings
from app.gateway.context import current_user_id
from app.gateway.tools import drive_tools
from app.integrations.google.drive_client import drive_client
from app.shared.store import InMemoryStore, token_store


@pytest.fixture(autouse=True)
def setup_drive_client():
    drive_client.init()
    yield
    import asyncio

    asyncio.run(drive_client.close())


@pytest.fixture(autouse=True)
def _init_token_store():
    token_store.init(InMemoryStore())
    yield


@pytest.fixture
def encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.config.settings.GOOGLE_TOKEN_ENCRYPTION_KEY", key)
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr("app.config.settings.GOOGLE_CLIENT_SECRET", "test-secret")
    return key


@pytest.fixture
async def stored_token(encryption_key):
    key = settings.GOOGLE_TOKEN_ENCRYPTION_KEY.encode()
    enc = Fernet(key).encrypt(b"fake-refresh-token").decode()
    await token_store.get().set(
        "user-123",
        json.dumps(
            {
                "access_token": "valid-access-token",
                "refresh_token_enc": enc,
                "expires_at": time.time() + 3600,
            }
        ),
    )


@pytest.mark.asyncio
@respx.mock
async def test_drive_search_files_returns_tool_result(stored_token, encryption_key):
    current_user_id.set("user-123")

    respx.get("https://www.googleapis.com/drive/v3/files").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "id": "f1",
                        "name": "Proposal.pdf",
                        "mimeType": "application/pdf",
                        "webViewLink": "https://drive.google.com/f1",
                        "modifiedTime": "2026-05-01T10:00:00Z",
                    }
                ]
            },
        )
    )

    result = await drive_tools.handle_drive_search_files({"query": "proposal", "max_results": 10})

    assert result.isError is False
    data = json.loads(result.content[0].text)
    assert len(data) == 1
    assert data[0]["file_id"] == "f1"


@pytest.mark.asyncio
async def test_drive_search_files_no_token_returns_error():
    current_user_id.set("user-no-token")

    result = await drive_tools.handle_drive_search_files({"query": "anything"})

    assert result.isError is True
    assert "authorize" in result.content[0].text.lower()


@pytest.mark.asyncio
async def test_drive_search_files_invalid_input_returns_error():
    current_user_id.set("user-123")
    result = await drive_tools.handle_drive_search_files({})
    assert result.isError is True
    assert "query" in result.content[0].text.lower()


def test_drive_tools_list_has_three_tools():
    assert len(drive_tools.DRIVE_TOOLS) == 3
    names = {t.name for t in drive_tools.DRIVE_TOOLS}
    assert names == {"drive-search-files", "drive-get-file-content", "drive-list-recent"}


def test_drive_registry_has_three_handlers():
    assert set(drive_tools.DRIVE_REGISTRY.keys()) == {
        "drive-search-files",
        "drive-get-file-content",
        "drive-list-recent",
    }
