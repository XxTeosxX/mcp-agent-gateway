from fastapi.testclient import TestClient


class TestHealthCheck:
    def test_returns_ok_status(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_returns_json_content_type(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.headers["content-type"] == "application/json"

    def test_method_not_allowed_post(self, client: TestClient) -> None:
        response = client.post("/health")
        assert response.status_code == 405

    def test_method_not_allowed_put(self, client: TestClient) -> None:
        response = client.put("/health")
        assert response.status_code == 405

    def test_method_not_allowed_delete(self, client: TestClient) -> None:
        response = client.delete("/health")
        assert response.status_code == 405
