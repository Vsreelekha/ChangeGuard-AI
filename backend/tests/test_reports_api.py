from fastapi.testclient import TestClient
from app.integrations.analyzer_adapter import CodeAnalyzerAdapter
from app.integrations.selector_adapter import TestSelectorAdapter
from app.services.test_runner_service import TestRunnerService


def test_create_report_endpoint_high_risk(client: TestClient):
    """Report creation with failed tests must result in HIGH risk level."""
    payload = {
        "changed_functions": ["calculate_total"],
        "impacted_functions": ["calculate_total", "checkout"],
        "impacted_modules": ["billing.py", "checkout.py"],
        "tests": {
            "total_tests": 5,
            "passed": 4,
            "failed": 1,
            "failures": ["test_calculate_total"],
        },
    }

    response = client.post("/api/v1/reports", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["risk_level"] == "HIGH"
    assert "run_id" in data
    assert any("Resolve these failures" in r for r in data["recommendations"])

    # Verify retrieval
    run_id = data["run_id"]
    get_res = client.get(f"/api/v1/reports/{run_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["run_id"] == run_id
    assert get_data["risk_level"] == "HIGH"


def test_create_report_endpoint_low_risk(client: TestClient):
    """Report creation with all passing tests must result in LOW risk level."""
    payload = {
        "changed_functions": ["calculate_total"],
        "impacted_functions": ["calculate_total"],
        "impacted_modules": ["billing.py"],
        "tests": {
            "total_tests": 4,
            "passed": 4,
            "failed": 0,
            "failures": [],
        },
    }

    response = client.post("/api/v1/reports", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["risk_level"] == "LOW"


def test_get_report_not_found_returns_404(client: TestClient):
    """Retrieving a non-existent run_id must return 404."""
    response = client.get("/api/v1/reports/run-non-existent-999")
    assert response.status_code == 404
    data = response.json()
    assert "was not found" in data["error"]


def test_full_workflow_run_endpoint(client: TestClient):
    """Verifies complete end-to-end pipeline execution via POST /api/v1/runs."""
    # 1. Setup mock analyzer
    CodeAnalyzerAdapter.register_custom_analyzer(
        lambda diff: {
            "changed_functions": ["calculate_total"],
            "impacted_functions": ["calculate_total", "checkout"],
            "impacted_modules": ["billing.py", "checkout.py"],
        }
    )

    # 2. Setup mock selector
    TestSelectorAdapter.register_custom_selector(
        lambda funcs: [
            {"test_name": "test_calculate_total", "reason": "Verifies billing", "priority": "high"}
        ]
    )

    # 3. Setup mock runner
    TestRunnerService.register_custom_runner(
        lambda path, tests: {
            "total_tests": 2,
            "passed": 2,
            "failed": 0,
            "failures": [],
        }
    )

    payload = {
        "git_diff": "diff --git a/billing.py b/billing.py\n+def calculate_total(): pass",
        "project_path": ".",
    }

    response = client.post("/api/v1/runs", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "run_id" in data
    assert data["changed_functions"] == ["calculate_total"]
    assert data["tests"]["passed"] == 2
    assert data["tests"]["failed"] == 0
    # Multi-module impact (billing.py & checkout.py) correctly evaluates to MEDIUM risk
    assert data["risk_level"] == "MEDIUM"


def test_full_workflow_stage_error_on_missing_analyzer(client: TestClient):
    """Verifies that missing analyzer stops the pipeline with a stage-specific 503 error."""
    CodeAnalyzerAdapter.register_custom_analyzer(None)

    payload = {
        "git_diff": "diff --git a/test.py b/test.py\n+def foo(): pass",
    }

    response = client.post("/api/v1/runs", json=payload)
    assert response.status_code == 503
    data = response.json()
    assert "Code analyzer integration pending" in data["error"]
