import time
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.conftest import make_token


class TestOAuthProtectedResourceMetadata:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200

    def test_resource_matches_audience(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-protected-resource")
        assert resp.json()["resource"] == settings.OAUTH_EXPECTED_AUDIENCE

    def test_authorization_server_matches_issuer(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-protected-resource")
        assert settings.GATEWAY_BASE_URL in resp.json()["authorization_servers"]

    def test_scopes_supported(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-protected-resource")
        scopes = resp.json()["scopes_supported"]
        assert "mcp:google:read" in scopes
        assert "mcp:slack:read" in scopes
        assert "mcp:admin:read" in scopes


class TestAuthBypass:
    def test_health_requires_no_token(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_well_known_requires_no_token(self, client: TestClient) -> None:
        resp = client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200


class TestUnauthorized:
    def test_mcp_without_token_returns_401(self) -> None:
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post("/mcp/", json={})
        assert resp.status_code == 401

    def test_401_includes_www_authenticate_header(self) -> None:
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post("/mcp/", json={})
        assert "WWW-Authenticate" in resp.headers
        assert "Bearer" in resp.headers["WWW-Authenticate"]

    def test_expired_token_returns_401(self, rsa_key: RSAPrivateKey) -> None:
        token = make_token(rsa_key, exp=int(time.time()) - 10)
        with patch("app.identity.token_validator.TokenValidator.validate", side_effect=ValueError("Token expired")):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
        assert resp.status_code == 401

    def test_wrong_audience_returns_401(self, rsa_key: RSAPrivateKey) -> None:
        token = make_token(rsa_key, aud="http://other-service/")
        with patch("app.identity.token_validator.TokenValidator.validate", side_effect=ValueError("Invalid audience")):
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
        assert resp.status_code == 401


class TestAuthorized:
    def test_valid_token_reaches_mcp(self, rsa_key: RSAPrivateKey) -> None:
        token = make_token(rsa_key)

        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post("/mcp/", headers={"Authorization": f"Bearer {token}"}, json={})
        assert resp.status_code != 401
