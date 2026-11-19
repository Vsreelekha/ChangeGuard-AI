from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import patch
from app.services.test_runner_service import TestRunnerService


def test_test_execution_success(client: TestClient):
    """Verifies test execution returns total, passed, failed, and failure lists."""
    def mock_runner(project_path: str, tests: list):
        assert "test_calculate_total" in tests
        return {
            "total_tests": 5,
            "passed": 4,
            "failed": 1,
            "failures": ["test_calculate_total"],
        }

    TestRunnerService.register_custom_runner(mock_runner)

    payload = {
        "project_path": ".",
        "selected_tests": ["test_calculate_total"],
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
        "selected_tests": ["test_sample"],
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


def test_test_execution_docker_unavailable_returns_503(client: TestClient):
    """When Docker is unavailable, the service must return 503 instead of falling back to host."""
    TestRunnerService.register_custom_runner(None)

    with patch.object(TestRunnerService, "is_docker_available", return_value=False):
        payload = {
            "project_path": ".",
            "selected_tests": ["test_calculate_total"],
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
    assert "--network" in cmd and "none" in cmd
    assert "--memory" in cmd
    assert "--cpus" in cmd
    assert "--pids-limit" in cmd
    assert "--read-only" in cmd
    assert any(":ro" in arg for arg in cmd)
    assert "pytest" in cmd
