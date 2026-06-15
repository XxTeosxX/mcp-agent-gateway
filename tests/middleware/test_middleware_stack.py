def test_security_headers_on_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "max-age=31536000" in resp.headers["strict-transport-security"]


def test_security_headers_on_401(client):
    resp = client.get("/mcp/", headers={"Authorization": ""})
    assert resp.status_code == 401
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_origin_guard_rejects_disallowed(client):
    resp = client.get("/mcp/", headers={"Origin": "https://evil.example.com", "Authorization": "Bearer valid"})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Origin not allowed"
