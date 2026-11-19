from fastapi.testclient import TestClient
from app.integrations.analyzer_adapter import CodeAnalyzerAdapter


def test_analysis_endpoint_success(client: TestClient):
    """Verifies successful code change analysis when adapter is connected."""
    # Register mock analyzer for unit testing
    def mock_analyzer(git_diff: str):
        assert "calculate_total" in git_diff
        return {
            "changed_functions": ["calculate_total"],
            "impacted_functions": ["calculate_total", "checkout"],
            "impacted_modules": ["billing.py", "checkout.py"],
        }

    CodeAnalyzerAdapter.register_custom_analyzer(mock_analyzer)

    payload = {
        "git_diff": """diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@ -10,2 +10,2 @@
-def calculate_total(items):
+def calculate_total(items, tax=0.05):
"""
    }

    response = client.post("/api/v1/analysis", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["changed_functions"] == ["calculate_total"]
    assert "checkout" in data["impacted_functions"]
    assert "billing.py" in data["impacted_modules"]


def test_analysis_empty_diff_returns_422(client: TestClient):
    """Empty or whitespace-only git_diff must be rejected with 422 Unprocessable Entity."""
    response = client.post("/api/v1/analysis", json={"git_diff": "   "})
    assert response.status_code == 422
    data = response.json()
    assert "error" in data


def test_analysis_missing_field_returns_422(client: TestClient):
    """Missing git_diff payload must be rejected with 422 Unprocessable Entity."""
    response = client.post("/api/v1/analysis", json={})
    assert response.status_code == 422


def test_analysis_integration_unavailable_returns_503(client: TestClient):
    """When the code analyzer module is unavailable, endpoint must return 503."""
    CodeAnalyzerAdapter.register_custom_analyzer(None)

    payload = {
        "git_diff": "diff --git a/test.py b/test.py\n+def foo(): pass"
    }

    response = client.post("/api/v1/analysis", json=payload)
    assert response.status_code == 503
    data = response.json()
    assert "Code analyzer integration pending" in data["error"]
