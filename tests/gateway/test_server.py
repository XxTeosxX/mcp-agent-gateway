import json
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi.testclient import TestClient
from mcp import types

from app.gateway.server import handle_health_check, handle_list_tools
from app.main import app
from tests.conftest import make_token


@pytest.fixture(scope="session")
def client(rsa_key: RSAPrivateKey) -> TestClient:
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {make_token(rsa_key)}"
        yield c


class TestHandleListTools:
    async def test_returns_tools_list(self) -> None:
        tools = await handle_list_tools()

        assert isinstance(tools, list)
        assert len(tools) == 2

        tool_names = [t.name for t in tools]
        assert "start-notification-stream" in tool_names
        assert "health-check" in tool_names

        notif_tool = next(t for t in tools if t.name == "start-notification-stream")
        assert isinstance(notif_tool, types.Tool)
        assert "count" in notif_tool.inputSchema.get("required", [])

    async def test_tool_has_correct_schema(self) -> None:
        tools = await handle_list_tools()
        tool = tools[0]

        props = tool.inputSchema["properties"]
        assert props["interval"]["type"] == "number"
        assert props["count"]["type"] == "number"
        assert props["caller"]["type"] == "string"


class TestMCPHealthCheckTool:
    async def test_handle_health_check_returns_status(self) -> None:
        result = await handle_health_check()
        assert isinstance(result, types.CallToolResult)
        assert result.isError is False
        assert len(result.content) == 1
        assert result.content[0].type == "text"
        assert "ok" in result.content[0].text

    async def test_handle_health_check_contains_keys(self) -> None:
        result = await handle_health_check()

        data = json.loads(result.content[0].text)
        assert data == {"status": "ok", "redis": False, "version": "1.27.1"}

    async def test_handle_health_check_has_structured_content(self) -> None:
        result = await handle_health_check()
        assert result.structuredContent is not None
        assert result.structuredContent == {"status": "ok", "redis": False, "version": "1.27.1"}


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
        assert len(tools) == 2
        tool_names = [t["name"] for t in tools]
        assert "start-notification-stream" in tool_names
        assert "health-check" in tool_names

    def test_call_tool_with_defaults(self, client: httpx.Client) -> None:
        session_id = self._initialize(client)

        resp = client.post(
            self.MCP_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "start-notification-stream",
                    "arguments": {"interval": 0.01, "count": 5, "caller": "test"},
                },
            },
            headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        content = result["content"]
        assert len(content) == 1
        assert "5 notifications" in content[0]["text"]
        assert result.get("isError") is False

    def test_call_tool_custom_params(self, client: httpx.Client) -> None:
        session_id = self._initialize(client)

        resp = client.post(
            self.MCP_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "start-notification-stream",
                    "arguments": {"interval": 0.01, "count": 3, "caller": "pytest"},
                },
            },
            headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        content = result["content"]
        assert "3 notifications" in content[0]["text"]
        assert "pytest" in content[0]["text"]
        assert result.get("isError") is False

    def test_unknown_tool_still_calls_handler(self, client: httpx.Client) -> None:
        session_id = self._initialize(client)

        resp = client.post(
            self.MCP_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "nonexistent-tool",
                    "arguments": {"interval": 0.01, "count": 1, "caller": "test"},
                },
            },
            headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data

    def test_health_check_tool(self, client: httpx.Client) -> None:
        session_id = self._initialize(client)

        resp = client.post(
            self.MCP_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "health-check",
                    "arguments": {},
                },
            },
            headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert result.get("isError") is False
        assert "structuredContent" in result
        assert result["structuredContent"] == {"status": "ok", "redis": False, "version": "1.27.1"}
        content = result["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert "ok" in content[0]["text"]

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
