from typing import Any
from unittest.mock import patch

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fakeredis.aioredis import FakeRedis
from fastapi.testclient import TestClient
from mcp import types

from app.main import app
from app.mcp.server import TOOL_SCOPE, handle_list_tools, visible_tools
from app.shared.context import current_user_scopes
from tests.conftest import make_token


@pytest.fixture(scope="session")
def _session_fake_redis():
    return FakeRedis(decode_responses=True)


@pytest.fixture(scope="session")
def client(rsa_key: RSAPrivateKey, _session_fake_redis: FakeRedis) -> TestClient:
    async def _get_redis(_url):
        await _session_fake_redis.ping()
        return _session_fake_redis

    token = make_token(
        rsa_key,
        resource_access={"mcp-gateway": {"roles": ["drive-user", "slack-user"]}},
    )
    with patch("app.main.get_redis", _get_redis):
        with TestClient(app) as c:
            c.headers["Authorization"] = f"Bearer {token}"
            yield c


class TestHandleListTools:
    async def test_returns_drive_tools(self) -> None:
        token = current_user_scopes.set(frozenset({"mcp:google:read"}))
        try:
            tools = await handle_list_tools()
        finally:
            current_user_scopes.reset(token)
        tool_names = {t.name for t in tools}
        assert "drive-search-files" in tool_names
        assert "drive-get-file-content" in tool_names
        assert "drive-list-recent" in tool_names

    async def test_does_not_include_health_check(self) -> None:
        token = current_user_scopes.set(frozenset({"mcp:google:read", "mcp:slack:read"}))
        try:
            tools = await handle_list_tools()
        finally:
            current_user_scopes.reset(token)
        assert "health-check" not in {t.name for t in tools}

    async def test_tool_readonly_hints_match_tool_nature(self) -> None:
        write_tools = {"slack-send-message", "drive-export-large-file"}
        token = current_user_scopes.set(frozenset({"mcp:google:read", "mcp:slack:read"}))
        try:
            tools = await handle_list_tools()
        finally:
            current_user_scopes.reset(token)
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

    def test_roger_cannot_see_or_call_drive(self, rsa_key) -> None:
        roger_redis = FakeRedis(decode_responses=True)

        async def _get_redis(_url):
            await roger_redis.ping()
            return roger_redis

        roger = make_token(rsa_key, resource_access={"mcp-gateway": {"roles": ["slack-user"]}})
        with patch("app.main.get_redis", _get_redis):
            with TestClient(app) as c:
                c.headers["Authorization"] = f"Bearer {roger}"
                session_id = self._initialize(c)

                listed = c.post(
                    self.MCP_PATH,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
                )
                names = {t["name"] for t in listed.json()["result"]["tools"]}
                assert "slack-send-message" in names
                assert "drive-search-files" not in names
                assert "drive-export-large-file" not in names

                called = c.post(
                    self.MCP_PATH,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "drive-search-files", "arguments": {"query": "x"}},
                    },
                    headers={**self.JSON_HEADERS, "Mcp-Session-Id": session_id},
                )
                result = called.json()["result"]
                assert result.get("isError") is True
                assert "Unknown tool" in result["content"][0]["text"]

    def test_request_without_session_returns_error(self, rsa_key) -> None:
        fresh_redis = FakeRedis(decode_responses=True)

        async def _get_redis(_url):
            await fresh_redis.ping()
            return fresh_redis

        token = make_token(
            rsa_key,
            resource_access={"mcp-gateway": {"roles": ["drive-user", "slack-user"]}},
        )
        with patch("app.main.get_redis", _get_redis):
            with TestClient(app) as c:
                c.headers["Authorization"] = f"Bearer {token}"
                resp = c.post(
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


def test_required_scope_constants():
    from app.integrations.google.job_tools import JOB_REQUIRED_SCOPE
    from app.integrations.google.tools import DRIVE_REQUIRED_SCOPE
    from app.integrations.slack.tools import SLACK_REQUIRED_SCOPE

    assert DRIVE_REQUIRED_SCOPE == "mcp:google:read"
    assert JOB_REQUIRED_SCOPE == "mcp:google:read"  # async Drive capabilities
    assert SLACK_REQUIRED_SCOPE == "mcp:slack:read"


_DRIVE = {"drive-search-files", "drive-get-file-content", "drive-list-recent"}
_JOBS = {"drive-export-large-file", "wait-for-job"}
_SLACK_SAMPLE = "slack-send-message"


def _names(scopes):
    return {t.name for t in visible_tools(frozenset(scopes))}


def test_visible_tools_drive_only():
    names = _names({"mcp:google:read"})
    assert _DRIVE <= names
    assert _JOBS <= names  # jobs gate on the Drive scope
    assert _SLACK_SAMPLE not in names


def test_visible_tools_slack_only():
    names = _names({"mcp:slack:read"})
    assert _SLACK_SAMPLE in names
    assert _DRIVE.isdisjoint(names)
    assert _JOBS.isdisjoint(names)


def test_visible_tools_both():
    names = _names({"mcp:google:read", "mcp:slack:read"})
    assert _DRIVE <= names
    assert _JOBS <= names
    assert _SLACK_SAMPLE in names


def test_visible_tools_none():
    assert _names(set()) == set()


def test_tool_scope_map_covers_every_tool():
    # Every advertised tool has an entry; nothing falls through ungated by accident.
    all_names = {t.name for t in visible_tools(frozenset({"mcp:google:read", "mcp:slack:read"}))}
    assert all_names == set(TOOL_SCOPE)
    assert TOOL_SCOPE["drive-export-large-file"] == "mcp:google:read"
    assert TOOL_SCOPE["wait-for-job"] == "mcp:google:read"
