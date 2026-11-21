import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.routes.projects import get_project_workspace_service
from app.services.project_workspace_service import ProjectWorkspaceService


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def make_service(tmp_path, **limits):
    approved = tmp_path / "approved"
    approved.mkdir()
    workspace = approved / "private"
    workspace.mkdir()
    return ProjectWorkspaceService(str(workspace), [str(approved)], **limits)


def test_project_upload_returns_identifier_and_never_filesystem_path(tmp_path):
    service = make_service(tmp_path)
    app.dependency_overrides[get_project_workspace_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/projects",
                files={"file": ("project.zip", zip_bytes([("app.py", "pass")]), "application/zip")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"project_id", "file_count", "expires_at"}
    assert body["file_count"] == 1
    assert len(body["project_id"]) == 64
    assert str(tmp_path) not in response.text


def test_project_upload_rejects_unsafe_archive_and_returns_no_partial_workspace(tmp_path):
    service = make_service(tmp_path)
    app.dependency_overrides[get_project_workspace_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/projects",
                files={"file": ("project.zip", zip_bytes([("../escape.py", "pass")]), "application/zip")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert list(Path(service.workspace_root).iterdir()) == []


def test_project_upload_enforces_actual_archive_byte_limit(tmp_path):
    service = make_service(tmp_path, max_upload_bytes=16)
    app.dependency_overrides[get_project_workspace_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/projects",
                files={"file": ("project.zip", zip_bytes([("app.py", "x" * 100)]), "application/zip")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 413
    assert "upload exceeds" in response.json()["error"]
