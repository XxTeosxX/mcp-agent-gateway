from app.config import settings
from tests.conftest import make_token

JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
PAYLOAD = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def _auth(rsa_key):
    return {"Authorization": f"Bearer {make_token(rsa_key)}", **JSON_HEADERS}


def test_exceeding_limit_returns_429(client, rsa_key, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUESTS", 2)
    headers = _auth(rsa_key)

    responses = [client.post("/mcp/", json=PAYLOAD, headers=headers) for _ in range(3)]

    assert responses[0].status_code == 400
    assert responses[1].status_code == 400
    assert responses[2].status_code == 429
    assert responses[2].headers.get("Retry-After")
    assert responses[2].json()["detail"] == "Rate limit exceeded"


def test_fail_open_when_rate_check_errors(client, rsa_key, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUESTS", 1)

    async def boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr("app.gateway.middleware.rate_limiter.check_rate_limit", boom)
    headers = _auth(rsa_key)

    for _ in range(3):
        resp = client.post("/mcp/", json=PAYLOAD, headers=headers)
        assert resp.status_code != 429


def test_disabled_allows_all(client, rsa_key, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_MAX_REQUESTS", 1)
    headers = _auth(rsa_key)

    for _ in range(3):
        resp = client.post("/mcp/", json=PAYLOAD, headers=headers)
        assert resp.status_code != 429
