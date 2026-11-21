from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.core.config import get_settings
from app.core.exceptions import TestExecutionTimeoutError
from app.services.test_runner_service import TestRunnerService


def test_test_execution_success(client: TestClient, tmp_path, monkeypatch):
    """Verifies test execution returns total, passed, failed, and failure lists."""
    def mock_runner(project_path: str, tests: list):
        assert "tests/test_billing.py::test_calculate_total" in tests
        return {
            "total_tests": 5,
            "passed": 4,
            "failed": 1,
            "failures": ["test_calculate_total"],
        }

    TestRunnerService.register_custom_runner(mock_runner)
    project = tmp_path / "project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_billing.py").write_text("def test_calculate_total():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])

    payload = {
        "project_path": str(project),
        "selected_tests": ["tests/test_billing.py::test_calculate_total"],
    }

    response = client.post("/api/v1/tests/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["total_tests"] == 5
    assert data["passed"] == 4
    assert data["failed"] == 1
    assert data["failures"] == ["test_calculate_total"]


def test_test_execution_invalid_project_path_returns_400(client: TestClient):
    """Non-existent project path must be rejected with 400."""
    TestRunnerService.register_custom_runner(None)
    payload = {
        "project_path": "non_existent_folder_abc123",
        "selected_tests": ["tests/test_sample.py::test_sample"],
    }
    response = client.post("/api/v1/tests/execute", json=payload)
    assert response.status_code == 400
    data = response.json()
    assert "does not exist" in data["error"]


def test_test_execution_illegal_test_name_returns_422(client: TestClient):
    """Malicious test names containing shell operators must be rejected by Pydantic validator."""
    payload = {
        "project_path": ".",
        "selected_tests": ["test_name; cat /etc/passwd"],
    }
    response = client.post("/api/v1/tests/execute", json=payload)
    assert response.status_code == 422


def test_test_execution_empty_tests_list_returns_422(client: TestClient):
    """Empty test list must be rejected with 422."""
    payload = {
        "project_path": ".",
        "selected_tests": [],
    }
    response = client.post("/api/v1/tests/execute", json=payload)
    assert response.status_code == 422


def test_test_execution_docker_unavailable_returns_503(client: TestClient, tmp_path, monkeypatch):
    """When Docker is unavailable, the service must return 503 instead of falling back to host."""
    TestRunnerService.register_custom_runner(None)
    project_root = tmp_path / "approved"
    project_root.mkdir()
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(project_root)])

    tests_dir = project_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text("def test_calculate_total():\n    assert True\n", encoding="utf-8")
    with patch.object(TestRunnerService, "is_docker_available", return_value=False):
        payload = {
            "project_path": str(project_root),
            "selected_tests": ["tests/test_sample.py::test_calculate_total"],
        }
        response = client.post("/api/v1/tests/execute", json=payload)
        assert response.status_code == 503
        data = response.json()
        assert "Docker is not installed or the Docker daemon is not running" in data["error"]


def test_docker_command_security_flags():
    """Verifies that the generated Docker command enforces all required containment flags."""
    runner = TestRunnerService()
    cmd = runner._build_docker_command(Path("."), ["test_sample"])
    assert "docker" in cmd[0]
    assert "--user" in cmd and "1000:1000" in cmd
    assert "--env" in cmd and cmd[cmd.index("--env") + 1] == "PYTHONPATH=/app"
    assert "--network" in cmd and "none" in cmd
    assert "--memory" in cmd
    assert "--cpus" in cmd
    assert "--pids-limit" in cmd
    assert "--read-only" in cmd
    assert any(":ro" in arg for arg in cmd)
    assert cmd[-5:] == ["pytest", "-q", "-o", "cache_dir=/tmp/.pytest_cache", "test_sample"]


def test_test_execution_rejects_path_traversal(client: TestClient, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    response = client.post("/api/v1/tests/execute", json={
        "project_path": str(project),
        "selected_tests": ["../outside/test_secret.py::test_secret"],
    })
    assert response.status_code == 422


def test_test_execution_rejects_absolute_target(client: TestClient, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    response = client.post("/api/v1/tests/execute", json={
        "project_path": str(project),
        "selected_tests": ["/etc/passwd::test_secret"],
    })
    assert response.status_code == 422


def test_pytest_parser_preserves_output_and_failure_details():
    result = TestRunnerService()._parse_pytest_output(
        "FAILED tests/test_billing.py::test_total - assertion failed\n1 failed in 0.01s",
        "runner warning",
        ["tests/test_billing.py::test_total"],
        1,
        0.25,
    )
    assert result.status == "failed"
    assert result.summary["passed"] == 0
    assert result.summary["failed"] == 1
    assert result.summary["skipped"] == 0
    assert result.summary["total"] == 1
    assert "FAILED tests/test_billing.py::test_total" in result.stdout
    assert result.stderr == "runner warning"
    assert result.failure_details[0]["test"] == "tests/test_billing.py::test_total"
    assert result.execution_time == 0.25


def test_pytest_parser_uses_final_summary_not_test_output():
    output = "test prints: 99 passed in 8.0s\n1 passed, 1 skipped in 0.02s\n"
    result = TestRunnerService()._parse_pytest_output(output, "", ["tests/test_x.py::test_x"], 0, 0.1)
    assert result.status == "skipped"
    assert result.summary["passed"] == 1
    assert result.summary["skipped"] == 1


def test_pytest_parser_marks_missing_summary_as_error():
    result = TestRunnerService()._parse_pytest_output(
        "test says 1 passed", "", ["tests/test_x.py::test_x"], 0, 0.1
    )
    assert result.status == "error"
    assert result.success is False


def test_pytest_parser_marks_no_tests_collected_as_skipped():
    result = TestRunnerService()._parse_pytest_output(
        "no tests ran in 0.01s", "", ["tests/test_missing.py::test_missing"], 5, 0.01
    )
    assert result.status == "skipped"
    assert result.success is False
    assert result.total_tests == 0


def test_pytest_parser_preserves_collection_errors():
    result = TestRunnerService()._parse_pytest_output(
        "ERROR tests/test_billing.py::test_total - fixture missing\n1 error in 0.02s",
        "",
        ["tests/test_billing.py::test_total"],
        1,
        0.02,
    )
    assert result.status == "error"
    assert result.summary["errors"] == 1
    assert result.success is False


def test_pytest_parser_marks_all_passed_as_verified_execution():
    result = TestRunnerService()._parse_pytest_output(
        "2 passed in 0.03s", "", ["tests/test_billing.py::test_total"], 0, 0.03
    )
    assert result.status == "passed"
    assert result.success is True
    assert result.summary["total"] == result.summary["passed"] == 2


def test_timeout_keeps_partial_output_and_execution_metadata(tmp_path, monkeypatch):
    project = tmp_path / "project"
    test_file = project / "tests" / "test_case.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_case(): pass\n", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(TestRunnerService, "is_docker_available", lambda self: True)

    timeout = subprocess.TimeoutExpired(
        cmd=["docker"], timeout=1, output=b"partial stdout", stderr=b"partial stderr"
    )
    with patch("app.services.test_runner_service.subprocess.run", side_effect=timeout):
        with pytest.raises(TestExecutionTimeoutError) as raised:
            TestRunnerService().execute_tests(str(project), ["tests/test_case.py::test_case"])

    assert raised.value.details["status"] == "timeout"
    assert raised.value.details["stdout"] == "partial stdout"
    assert raised.value.details["stderr"] == "partial stderr"
    assert raised.value.details["execution_time"] >= 0


def test_custom_runner_cannot_mark_partial_results_as_passed(tmp_path, monkeypatch):
    project = tmp_path / "project"
    test_file = project / "tests" / "test_case.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_case(): pass\n", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    TestRunnerService.register_custom_runner(
        lambda *_: {
            "total_tests": 2,
            "passed": 1,
            "failed": 0,
            "skipped": 1,
            "status": "passed",
            "success": True,
        }
    )
    try:
        result = TestRunnerService().execute_tests(str(project), ["tests/test_case.py::test_case"])
    finally:
        TestRunnerService.register_custom_runner(None)

    assert result.status == "skipped"
    assert result.success is False
