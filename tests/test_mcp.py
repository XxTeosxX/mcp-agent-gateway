from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import types

from app.main import app
from app.mcp.server import handle_list_tools


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


class TestHandleListTools:
    async def test_returns_tools_list(self) -> None:
        tools = await handle_list_tools()

        assert isinstance(tools, list)
        assert len(tools) == 1

        tool = tools[0]
        assert isinstance(tool, types.Tool)
        assert tool.name == "start-notification-stream"
        assert "count" in tool.inputSchema.get("required", [])

    async def test_tool_has_correct_schema(self) -> None:
        tools = await handle_list_tools()
        tool = tools[0]

        props = tool.inputSchema["properties"]
        assert props["interval"]["type"] == "number"
        assert props["count"]["type"] == "number"
        assert props["caller"]["type"] == "string"


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
        assert len(tools) == 1
        assert tools[0]["name"] == "start-notification-stream"

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
        content = data["result"]["content"]
        assert len(content) == 1
        assert "5 notifications" in content[0]["text"]

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
        content = data["result"]["content"]
        assert "3 notifications" in content[0]["text"]
        assert "pytest" in content[0]["text"]

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
