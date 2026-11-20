from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.integrations.selector_adapter import TestSelectorAdapter


def test_test_selection_success_returns_structured_result(client: TestClient, tmp_path, monkeypatch):
    project = tmp_path / "project"
    tests = project / "tests"
    tests.mkdir(parents=True)
    app_file = project / "billing.py"
    app_file.write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
    test_file = tests / "test_billing.py"
    test_file.write_text("from billing import calculate_total\n\ndef test_total():\n    calculate_total()\n", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])

    def custom_selector(impact_report, test_mapping):
        assert impact_report["changed_functions"][0]["name"] == "calculate_total"
        assert test_mapping["success"] is True
        return {
            "success": True,
            "selected_tests": [{"test_id": "tests/test_billing.py::test_total", "test_file": "tests/test_billing.py", "test_name": "test_total", "target_functions": ["calculate_total"], "selection_reason": "direct", "priority": "high"}],
            "total_tests_discovered": 1, "total_tests_selected": 1, "reduction_percentage": 0.0,
            "pytest_args": ["tests/test_billing.py::test_total"],
            "selection_summary": {"total_selected": 1}, "errors": [],
        }

    TestSelectorAdapter.register_custom_selector(custom_selector)
    response = client.post("/api/v1/tests/select", json={
        "project_path": str(project),
        "impact_report": {"changed_functions": [{"name": "calculate_total"}], "impacted_functions": [], "unassigned_changed_lines": []},
    })
    assert response.status_code == 200, response.text
    assert response.json()["selected_tests"][0]["test_name"] == "test_total"
    assert response.json()["pytest_args"] == ["tests/test_billing.py::test_total"]


def test_test_selection_missing_project_path_returns_422(client: TestClient):
    assert client.post("/api/v1/tests/select", json={"impact_report": {}}).status_code == 422
