from fastapi.testclient import TestClient
from app.integrations.analyzer_adapter import CodeAnalyzerAdapter
from app.core.exceptions import TestExecutionTimeoutError
from app.database.models import AnalysisRun
from app.services.test_runner_service import TestRunnerService


def test_create_report_endpoint_high_risk(client: TestClient):
    """Report creation with failed tests must result in HIGH risk level."""
    payload = {
        "impact_analysis": {
            "success": True,
            "changed_functions": [{"name": "calculate_total", "metadata": {"line": 12}}],
            "summary": {"changed_functions_count": 1},
        },
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
    assert get_data["impact_analysis"]["changed_functions"][0]["metadata"]["line"] == 12


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


def test_full_workflow_run_endpoint(client: TestClient, tmp_path, monkeypatch):
    """Runs analysis, real mapping/selection, mocked Docker execution, scoring, and persistence."""
    from app.core.config import get_settings

    project = tmp_path / "project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    app_file = project / "billing.py"
    app_file.write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_billing.py").write_text(
        "from billing import calculate_total\n\ndef test_calculate_total():\n    assert calculate_total() == 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])

    def mock_analyzer(diff, source_files):
        assert str(app_file.resolve()) in source_files
        return {
            "success": True,
            "changed_files": [{"file_path": "billing.py", "change_type": "modified"}],
            "changed_functions": [{
                "id": f"{app_file.resolve().as_posix()}:calculate_total",
                "name": "calculate_total", "qualified_name": "calculate_total",
                "file_path": app_file.resolve().as_posix(), "start_line": 1, "end_line": 2,
                "function_type": "function", "changed_lines": [2], "nested": {"evidence": ["line 2"]},
            }],
            "impacted_functions": [], "unassigned_changed_lines": [], "errors": [],
            "summary": {"changed_functions_count": 1},
        }

    CodeAnalyzerAdapter.register_custom_analyzer(mock_analyzer)

    def mock_runner(path, selected_tests):
        assert selected_tests == ["tests/test_billing.py::test_calculate_total"]
        return {"total_tests": 1, "passed": 1, "failed": 0, "failures": []}

    TestRunnerService.register_custom_runner(mock_runner)
    response = client.post("/api/v1/runs", json={
        "git_diff": "diff --git a/billing.py b/billing.py\n+def calculate_total():",
        "project_path": str(project),
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["impact_analysis"]["changed_functions"][0]["nested"]["evidence"] == ["line 2"]
    assert str(project.resolve()) not in response.text
    assert data["impact_analysis"]["changed_functions"][0]["file_path"] == "billing.py"
    assert data["workflow_report"]["risk"]["verification_status"] == "VERIFIED"
    assert data["workflow_report"]["verification_success"] is True
    assert data["tests"]["passed"] == 1
    retrieved = client.get(f"/api/v1/reports/{data['run_id']}").json()
    assert str(project.resolve()) not in retrieved.__str__()
    assert retrieved["impact_analysis"] == data["impact_analysis"]
    assert retrieved["workflow_report"]["test_selection"]["selected_tests"][0]["test_name"] == "test_calculate_total"


def test_get_legacy_report_redacts_filesystem_paths(client, db_session, tmp_path):
    """Old rows are sanitized at serialization time without mutating persistence."""
    project_root = tmp_path / "legacy project"
    absolute_file = str(project_root / "src" / "module.py")
    db_session.add(
        AnalysisRun(
            run_id="legacy-path-report",
            changed_functions=[{
                "id": f"{absolute_file}:calculate",
                "file_path": absolute_file,
            }],
            impacted_functions=[],
            impacted_modules=[absolute_file],
            selected_tests=[],
            test_results={
                "total_tests": 0,
                "passed": 0,
                "failed": 0,
                "failures": [],
            },
            impact_analysis={
                "changed_functions": [{"file_path": absolute_file}],
                "errors": [{"file_path": absolute_file, "error": f"Could not read {absolute_file}"}],
            },
            workflow_report={
                "metadata": {"project_path": str(project_root)},
                "test_execution": {"stdout": f"failed in {absolute_file}"},
            },
            risk_level="MEDIUM",
            recommendations=[
                f"Review {absolute_file}",
                "Diagnostic at C:\\private data\\internal.py",
            ],
        )
    )
    db_session.commit()

    response = client.get("/api/v1/reports/legacy-path-report")

    assert response.status_code == 200, response.text
    body = response.json()
    assert str(project_root) not in response.text
    assert "project_path" not in body["workflow_report"]["metadata"]
    assert body["changed_functions"][0]["file_path"].replace("\\", "/") == "src/module.py"
    assert body["impact_analysis"]["changed_functions"][0]["file_path"].replace("\\", "/") == "src/module.py"
    assert body["workflow_report"]["test_execution"]["stdout"].replace("\\", "/") == "failed in src/module.py"
    assert "C:\\private data" not in response.text


def test_workflow_requires_project_path(client: TestClient):
    response = client.post("/api/v1/runs", json={"git_diff": "diff --git a/a.py b/a.py"})
    assert response.status_code == 422


def test_workflow_empty_test_discovery_is_not_verified(client: TestClient, tmp_path, monkeypatch):
    from app.core.config import get_settings

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    CodeAnalyzerAdapter.register_custom_analyzer(lambda diff, files: {
        "success": True, "changed_files": [], "changed_functions": [], "impacted_functions": [],
        "unassigned_changed_lines": [], "errors": [], "summary": {},
    })
    response = client.post("/api/v1/runs", json={"git_diff": "diff --git a/a.py b/a.py", "project_path": str(project)})
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["workflow_report"]["test_execution"]["status"] == "skipped"
    assert data["workflow_report"]["verification_success"] is False


def test_workflow_preserves_timeout_evidence(client: TestClient, tmp_path, monkeypatch):
    from app.core.config import get_settings

    project = tmp_path / "project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    app_file = project / "billing.py"
    app_file.write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_billing.py").write_text(
        "from billing import calculate_total\n\ndef test_calculate_total():\n    assert calculate_total() == 1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    CodeAnalyzerAdapter.register_custom_analyzer(lambda diff, files: {
        "success": True,
        "changed_files": [{"file_path": "billing.py", "change_type": "modified"}],
        "changed_functions": [{
            "id": f"{app_file.resolve().as_posix()}:calculate_total",
            "name": "calculate_total", "qualified_name": "calculate_total",
            "file_path": app_file.resolve().as_posix(), "start_line": 1, "end_line": 2,
            "function_type": "function", "changed_lines": [2],
        }],
        "impacted_functions": [], "unassigned_changed_lines": [], "errors": [], "summary": {},
    })

    def timeout_runner(*args, **kwargs):
        raise TestExecutionTimeoutError(
            "pytest timed out",
            details={"stdout": "partial output", "stderr": "partial error", "execution_time": 12.5},
        )

    monkeypatch.setattr(TestRunnerService, "execute_tests", timeout_runner)
    response = client.post("/api/v1/runs", json={
        "git_diff": "diff --git a/billing.py b/billing.py\n+    return 2",
        "project_path": str(project),
    })

    assert response.status_code == 201, response.text
    report = response.json()["workflow_report"]
    assert report["test_execution"]["status"] == "timeout"
    assert report["test_execution"]["stdout"] == "partial output"
    assert report["test_execution"]["stderr"] == "partial error"
    assert report["test_execution"]["execution_time"] == 12.5
    assert report["risk"]["verification_status"] == "TIMEOUT"
    assert report["verification_success"] is False
