from fastapi.testclient import TestClient
from app.core.config import get_settings
from app.integrations.analyzer_adapter import CodeAnalyzerAdapter


def _analysis_result():
    return {
        "success": True,
        "changed_files": [{"file_path": "billing.py", "change_type": "modified"}],
        "changed_functions": [{"name": "calculate_total", "nested": {"changed_lines": [2]}}],
        "impacted_functions": [{"name": "checkout", "distance": 1}],
        "unassigned_changed_lines": [],
        "errors": [],
        "summary": {"changed_functions_count": 1},
    }


def test_analysis_endpoint_success_preserves_structured_result(client: TestClient, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "billing.py").write_text("def calculate_total():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])

    def mock_analyzer(diff, source_files):
        assert "calculate_total" in diff
        assert source_files == [str((project / "billing.py").resolve())]
        return _analysis_result()

    CodeAnalyzerAdapter.register_custom_analyzer(mock_analyzer)
    response = client.post("/api/v1/analysis", json={"git_diff": "diff --git a/billing.py b/billing.py\n+calculate_total", "project_path": str(project)})
    assert response.status_code == 200
    assert response.json()["changed_functions"][0]["nested"]["changed_lines"] == [2]
    assert response.json()["summary"]["changed_functions_count"] == 1


def test_analysis_rejects_project_outside_approved_root(client: TestClient, tmp_path, monkeypatch):
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(approved)])
    response = client.post("/api/v1/analysis", json={"git_diff": "diff --git a/a.py b/a.py\n+x", "project_path": str(outside)})
    assert response.status_code == 400


def test_analysis_empty_diff_returns_422(client: TestClient):
    assert client.post("/api/v1/analysis", json={"git_diff": "   ", "project_path": "."}).status_code == 422


def test_analysis_missing_project_path_returns_422(client: TestClient):
    assert client.post("/api/v1/analysis", json={"git_diff": "diff --git a/a.py b/a.py"}).status_code == 422


def test_analysis_analyzer_failure_returns_503(client: TestClient, tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(get_settings(), "APPROVED_PROJECT_ROOTS", [str(tmp_path)])
    CodeAnalyzerAdapter.register_custom_analyzer(lambda diff, files: {"success": False})
    response = client.post("/api/v1/analysis", json={"git_diff": "diff --git a/a.py b/a.py", "project_path": str(project)})
    assert response.status_code == 503
