from typing import Any
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from mcp import types

from app.gateway.server import handle_list_tools
from app.main import app
from tests.conftest import make_token


@pytest.fixture(scope="session")
def _session_fake_redis():
    return FakeRedis(decode_responses=True)


@pytest.fixture(scope="session")
def client(rsa_key: RSAPrivateKey, _session_fake_redis: FakeRedis) -> TestClient:
    async def _get_redis(_url):
        await _session_fake_redis.ping()
        return _session_fake_redis

    with patch("app.main.get_redis", _get_redis):
        with TestClient(app) as c:
            c.headers["Authorization"] = f"Bearer {make_token(rsa_key)}"
            yield c


class TestHandleListTools:
    async def test_returns_drive_tools(self) -> None:
        tools = await handle_list_tools()

        assert isinstance(tools, list)
        tool_names = {t.name for t in tools}
        assert "drive-search-files" in tool_names
        assert "drive-get-file-content" in tool_names
        assert "drive-list-recent" in tool_names

    async def test_does_not_include_health_check(self) -> None:
        tools = await handle_list_tools()
        tool_names = {t.name for t in tools}
        assert "health-check" not in tool_names

    async def test_tool_readonly_hints_match_tool_nature(self) -> None:

        write_tools = {"slack-send-message"}
        tools = await handle_list_tools()
        for tool in tools:
            assert isinstance(tool, types.Tool)
            expected = tool.name not in write_tools
            assert tool.annotations.readOnlyHint is expected, tool.name


class TestMCPIntegration:
    MCP_PATH = "/mcp/"
    INIT_PAYLOAD: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }
    JSON_HEADERS = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    def _initialize(self, client: httpx.Client) -> str:
        resp = client.post(self.MCP_PATH, json=self.INIT_PAYLOAD, headers=self.JSON_HEADERS)
        assert resp.status_code == 200
        session_id = resp.headers.get("mcp-session-id")
        assert session_id is not None, "No Mcp-Session-Id in response"
        return session_id

    def test_list_tools(self, client: httpx.Client) -> None:
        session_id = self._initialize(client)

        resp = client.post(
            self.MCP_PATH,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        tools = data["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert "drive-search-files" in tool_names
        assert "drive-get-file-content" in tool_names
        assert "drive-list-recent" in tool_names
        assert "health-check" not in tool_names

    def test_call_unknown_tool_returns_error(self, client: httpx.Client) -> None:
        session_id = self._initialize(client)

        resp = client.post(
            self.MCP_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "nonexistent-tool", "arguments": {}},
            },
            headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        result = data.get("result", {})
        assert result.get("isError") is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_request_without_session_returns_error(self, client: httpx.Client) -> None:
        resp = client.post(
            self.MCP_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
            headers=self.JSON_HEADERS,
        )

        data = resp.json()
        assert "error" in data
