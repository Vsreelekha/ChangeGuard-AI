"""API tests for running and retrieving reports for uploaded projects."""

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.exceptions import (
    AnalyzerIntegrationError,
    DatabaseError,
    TestExecutionTimeoutError,
    TestSelectorIntegrationError as SelectorIntegrationFailure,
)
from app.routes.projects import (
    get_project_report_service,
    get_project_workspace_service,
    get_run_workspace_service,
)
from app.services.project_run_workspace_service import ProjectRunWorkspaceService
from app.services.project_workspace_service import ProjectWorkspaceService
from app.services.report_service import ReportService


def _archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("billing.py", "def calculate_total():\n    return 1\n")
        archive.writestr(
            "tests/test_billing.py",
            "from billing import calculate_total\n\n"
            "def test_calculate_total():\n    assert calculate_total() == 1\n",
        )
    return output.getvalue()


def _workspace_service(tmp_path) -> ProjectWorkspaceService:
    approved = tmp_path / "approved"
    approved.mkdir()
    root = approved / "workspaces"
    root.mkdir()
    # ReportService's shared path validator reads the same application setting
    # used by production workspace configuration.
    get_settings().APPROVED_PROJECT_ROOTS = [str(approved)]
    return ProjectWorkspaceService(str(root), [str(approved)])


def _configure_workspace_overrides(workspace: ProjectWorkspaceService) -> None:
    from app.main import app

    app.dependency_overrides[get_project_workspace_service] = lambda: workspace
    app.dependency_overrides[get_run_workspace_service] = lambda: ProjectRunWorkspaceService(
        workspace.workspace_root
    )


@pytest.fixture(autouse=True)
def restore_approved_roots():
    settings = get_settings()
    original = settings.APPROVED_PROJECT_ROOTS
    yield
    settings.APPROVED_PROJECT_ROOTS = original


def _upload(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects",
        files={"file": ("project.zip", _archive(), "application/zip")},
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


def _expire_workspace(service: ProjectWorkspaceService, project_id: str) -> None:
    metadata_path = Path(service.workspace_root) / project_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def _impact(root: str):
    return {
        "success": True,
        "changed_files": [{"file_path": "billing.py", "change_type": "modified"}],
        "changed_functions": [{
            "id": f"{root}/billing.py:calculate_total",
            "name": "calculate_total",
            "file_path": f"{root}/billing.py",
            "nested": {"evidence": [f"{root}/billing.py:2"]},
        }],
        "impacted_functions": [],
        "unassigned_changed_lines": [],
        "errors": [],
        "summary": {"changed_functions_count": 1},
    }


def _successful_report_service():
    class Analyzer:
        def analyze_git_diff(self, git_diff, source_files):
            assert git_diff.startswith("diff --git")
            assert any(path.endswith("billing.py") for path in source_files)
            return _impact(str(Path(source_files[0]).parent).replace("\\", "/"))

    class Selector:
        @staticmethod
        def _split_test_and_application_files(source_files, project_root):
            tests = [path for path in source_files if "/tests/" in path.replace("\\", "/")]
            app = [path for path in source_files if path not in tests]
            return tests, app

        def select_tests_for_files(self, impact, test_files, app_files, project_root):
            return {
                "success": True,
                "selected_tests": [{"test_id": "tests/test_billing.py::test_calculate_total", "test_name": "test_calculate_total"}],
                "pytest_args": ["tests/test_billing.py::test_calculate_total"],
                "total_tests_discovered": 1,
                "total_tests_selected": 1,
                "reduction_percentage": 0,
                "selection_summary": {"nested": {"selected": 1}},
                "errors": [],
            }

    class Runner:
        def execute_tests(self, project_root, selected_tests):
            assert selected_tests == ["tests/test_billing.py::test_calculate_total"]

            class Result:
                def model_dump(self):
                    return {
                        "status": "passed", "success": True,
                        "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0},
                        "execution_time": 0.01,
                        "stdout": project_root + "/tests/test_billing.py",
                        "stderr": "", "exit_code": 0,
                        "failures": [], "failure_details": [],
                    }

            return Result()

    return ReportService(analyzer_service=Analyzer(), selector_service=Selector(), runner_service=Runner())


def test_upload_run_and_report_retrieval_preserve_structure_and_hide_paths(client, tmp_path):
    from app.main import app

    workspace = _workspace_service(tmp_path)
    _configure_workspace_overrides(workspace)
    app.dependency_overrides[get_project_report_service] = _successful_report_service
    try:
        project_id = _upload(client)
        response = client.post(
            f"/api/v1/projects/{project_id}/runs",
            json={"git_diff": "diff --git a/billing.py b/billing.py\n+    return 2"},
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["impact_analysis"]["changed_functions"][0]["nested"]["evidence"] == ["billing.py:2"]
        assert result["workflow_report"]["metadata"] == {"project_id": project_id}
        assert result["workflow_report"]["test_execution"]["stdout"] == "tests/test_billing.py"
        assert result["workflow_report"]["test_selection_result"]["pytest_args"] == [
            "tests/test_billing.py::test_calculate_total"
        ]
        assert result["workflow_report"]["test_execution_result"]["summary"]["passed"] == 1
        assert str(tmp_path) not in response.text

        retrieved = client.get(f"/api/v1/reports/{result['run_id']}")
        assert retrieved.status_code == 200
        assert retrieved.json()["impact_analysis"] == result["impact_analysis"]
        assert retrieved.json()["workflow_report"] == result["workflow_report"]
    finally:
        app.dependency_overrides.pop(get_project_workspace_service, None)
        app.dependency_overrides.pop(get_run_workspace_service, None)
        app.dependency_overrides.pop(get_project_report_service, None)


@pytest.mark.parametrize("project_id", ["bad-id", "0" * 64])
def test_invalid_or_missing_project_is_rejected(client, tmp_path, project_id):
    from app.main import app

    workspace = _workspace_service(tmp_path)
    _configure_workspace_overrides(workspace)
    try:
        response = client.post(f"/api/v1/projects/{project_id}/runs", json={"git_diff": "diff --git a/a.py b/a.py"})
    finally:
        app.dependency_overrides.pop(get_project_workspace_service, None)
        app.dependency_overrides.pop(get_run_workspace_service, None)
    assert response.status_code == 400
    assert str(tmp_path) not in response.text


def test_expired_project_rejects_new_run(client, tmp_path):
    from app.main import app

    workspace = _workspace_service(tmp_path)
    _configure_workspace_overrides(workspace)
    try:
        project_id = _upload(client)
        _expire_workspace(workspace, project_id)
        response = client.post(f"/api/v1/projects/{project_id}/runs", json={"git_diff": "diff --git a/a.py b/a.py"})
    finally:
        app.dependency_overrides.pop(get_project_workspace_service, None)
        app.dependency_overrides.pop(get_run_workspace_service, None)
    assert response.status_code == 400


def test_successful_run_releases_lease(client, tmp_path):
    from app.main import app

    workspace = _workspace_service(tmp_path)
    _configure_workspace_overrides(workspace)
    class ExpireThenRun:
        def __init__(self):
            self.delegate = _successful_report_service()

        def execute_complete_workflow(self, request, db, *, report_metadata=None):
            _expire_workspace(workspace, project_id)
            return self.delegate.execute_complete_workflow(
                request, db, report_metadata=report_metadata
            )

    app.dependency_overrides[get_project_report_service] = ExpireThenRun
    try:
        project_id = _upload(client)
        response = client.post(f"/api/v1/projects/{project_id}/runs", json={"git_diff": "diff --git a/a.py b/a.py"})
        assert response.status_code == 201, response.text
        assert workspace.cleanup_expired_workspaces() == 1
    finally:
        app.dependency_overrides.pop(get_project_workspace_service, None)
        app.dependency_overrides.pop(get_run_workspace_service, None)
        app.dependency_overrides.pop(get_project_report_service, None)


def test_active_workflow_lease_blocks_cleanup(client, tmp_path):
    from app.main import app

    workspace = _workspace_service(tmp_path)
    _configure_workspace_overrides(workspace)

    class ExpiringReportService:
        def execute_complete_workflow(self, request, db, *, report_metadata=None):
            _expire_workspace(workspace, project_id)
            assert workspace.cleanup_expired_workspaces() == 0
            raise AnalyzerIntegrationError("simulated analyzer failure")

    app.dependency_overrides[get_project_report_service] = ExpiringReportService
    try:
        project_id = _upload(client)
        response = client.post(f"/api/v1/projects/{project_id}/runs", json={"git_diff": "diff --git a/a.py b/a.py"})
        assert response.status_code == 503
        assert workspace.cleanup_expired_workspaces() == 1
    finally:
        app.dependency_overrides.pop(get_project_workspace_service, None)
        app.dependency_overrides.pop(get_run_workspace_service, None)
        app.dependency_overrides.pop(get_project_report_service, None)


@pytest.mark.parametrize(
    "failure", ["analyzer", "selector", "timeout", "execution", "persistence"]
)
def test_lease_released_after_workflow_stage_failures(client, tmp_path, monkeypatch, failure):
    from app.main import app

    workspace = _workspace_service(tmp_path)
    _configure_workspace_overrides(workspace)

    class Analyzer:
        def analyze_git_diff(self, git_diff, source_files):
            if failure == "analyzer":
                raise AnalyzerIntegrationError("simulated analyzer failure")
            return _impact(str(Path(source_files[0]).parent).replace("\\", "/"))

    class Selector:
        @staticmethod
        def _split_test_and_application_files(source_files, project_root):
            return [path for path in source_files if "tests" in path], [path for path in source_files if "tests" not in path]

        def select_tests_for_files(self, *args):
            if failure == "selector":
                raise SelectorIntegrationFailure("simulated selector failure")
            return {
                "success": True, "selected_tests": [{"test_name": "test_calculate_total"}],
                "pytest_args": ["tests/test_billing.py::test_calculate_total"],
                "total_tests_discovered": 1, "total_tests_selected": 1,
                "reduction_percentage": 0, "selection_summary": {}, "errors": [],
            }

    class Runner:
        def execute_tests(self, *args):
            if failure == "timeout":
                raise TestExecutionTimeoutError("simulated timeout", details={"execution_time": 1})
            if failure == "execution":
                from app.core.exceptions import TestExecutionError
                raise TestExecutionError("simulated test failure")

            class Result:
                def model_dump(self):
                    return {"status": "passed", "success": True, "summary": {"total": 1, "passed": 1, "failed": 0, "skipped": 0, "errors": 0}, "failures": []}
            return Result()

    report_service = ReportService(analyzer_service=Analyzer(), selector_service=Selector(), runner_service=Runner())
    if failure == "persistence":
        def fail_persist(db, db_run):
            raise DatabaseError("simulated persistence failure")

        monkeypatch.setattr(ReportService, "_persist", staticmethod(fail_persist))
    app.dependency_overrides[get_project_report_service] = lambda: report_service
    try:
        project_id = _upload(client)
        response = client.post(f"/api/v1/projects/{project_id}/runs", json={"git_diff": "diff --git a/billing.py b/billing.py"})
        if failure in {"analyzer", "selector"}:
            assert response.status_code == 503
        elif failure == "persistence":
            assert response.status_code == 500
        else:
            assert response.status_code == 201
            expected = "timeout" if failure == "timeout" else "error"
            assert response.json()["workflow_report"]["test_execution"]["status"] == expected

        _expire_workspace(workspace, project_id)
        assert workspace.cleanup_expired_workspaces() == 1
    finally:
        app.dependency_overrides.pop(get_project_workspace_service, None)
        app.dependency_overrides.pop(get_run_workspace_service, None)
        app.dependency_overrides.pop(get_project_report_service, None)
