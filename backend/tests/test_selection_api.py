from fastapi.testclient import TestClient
from app.integrations.selector_adapter import TestSelectorAdapter


def test_test_selection_success(client: TestClient):
    """Verifies successful test selection when selector adapter is registered."""
    def mock_selector(impacted_functions):
        assert "calculate_total" in impacted_functions
        return [
            {
                "test_name": "test_calculate_total",
                "reason": "Tests the modified billing function",
                "priority": "high",
            },
            {
                "test_name": "test_checkout_flow",
                "reason": "Tests checkout integration with billing",
                "priority": "medium",
            },
        ]

    TestSelectorAdapter.register_custom_selector(mock_selector)

    payload = {
        "impacted_functions": ["calculate_total", "checkout"]
    }

    response = client.post("/api/v1/tests/select", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "selected_tests" in data
    assert len(data["selected_tests"]) == 2
    assert data["selected_tests"][0]["test_name"] == "test_calculate_total"
    assert data["selected_tests"][0]["priority"] == "high"


def test_test_selection_empty_list_returns_422(client: TestClient):
    """Empty list of impacted functions must be rejected with 422."""
    response = client.post("/api/v1/tests/select", json={"impacted_functions": []})
    assert response.status_code == 422


def test_test_selection_integration_unavailable_returns_503(client: TestClient):
    """When test selector module is not connected, endpoint must return 503."""
    TestSelectorAdapter.register_custom_selector(None)

    payload = {
        "impacted_functions": ["calculate_total"]
    }

    response = client.post("/api/v1/tests/select", json=payload)
    assert response.status_code == 503
    data = response.json()
    assert "Test selector integration pending" in data["error"]
