import os
from pathlib import Path

import pytest

from app.core.exceptions import ChangeGuardException, InvalidInputError
from app.services import project_path_service
from app.services.project_path_service import discover_python_source_files, validate_project_path
from app.services.test_runner_service import TestRunnerService, settings as runner_settings


@pytest.fixture
def approved_root(tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    return root


def test_validates_project_inside_approved_root(approved_root):
    project = approved_root / "project"
    project.mkdir()

    assert validate_project_path(str(project), [str(approved_root)]) == project.resolve()


def test_rejects_project_outside_approved_roots(approved_root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(InvalidInputError, match="outside"):
        validate_project_path(str(outside), [str(approved_root)])


@pytest.mark.parametrize("roots", [None, [], ["."], ["./"], [""]])
def test_rejects_missing_empty_and_unsafe_approved_roots(approved_root, monkeypatch, roots):
    if roots is None:
        monkeypatch.setattr(project_path_service, "get_settings", lambda: type("Settings", (), {"APPROVED_PROJECT_ROOTS": []})())
    with pytest.raises(ChangeGuardException) as raised:
        validate_project_path(str(approved_root), roots)
    assert raised.value.status_code == 500


def test_rejects_relative_or_nonexistent_approved_root(approved_root, tmp_path):
    for roots in (["relative/root"], [str(tmp_path / "missing-root")]):
        with pytest.raises(ChangeGuardException):
            validate_project_path(str(approved_root), roots)


def test_rejects_nonexistent_project_and_file_instead_of_directory(approved_root, tmp_path):
    with pytest.raises(InvalidInputError, match="does not exist"):
        validate_project_path(str(approved_root / "missing"), [str(approved_root)])

    project_file = approved_root / "not-a-directory.py"
    project_file.write_text("pass\n", encoding="utf-8")
    with pytest.raises(InvalidInputError, match="not a directory"):
        validate_project_path(str(project_file), [str(approved_root)])


def test_rejects_project_symlink_resolving_outside_approved_roots(approved_root, tmp_path):
    outside = tmp_path / "outside-project"
    outside.mkdir()
    link = approved_root / "linked-project"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable on this OS or account")

    with pytest.raises(InvalidInputError, match="outside"):
        validate_project_path(str(link), [str(approved_root)])


def test_discovery_excludes_generated_and_dependency_directories(approved_root):
    (approved_root / "app.py").write_text("pass\n", encoding="utf-8")
    excluded = [
        ".git", ".venv", "venv", "__pycache__", "site-packages", "node_modules",
        "build", "dist", "target", "vendor", ".tox", ".pytest_cache",
    ]
    for name in excluded:
        directory = approved_root / name
        directory.mkdir()
        (directory / "ignored.py").write_text("pass\n", encoding="utf-8")

    result = discover_python_source_files(str(approved_root), [str(approved_root)])

    assert result == [str((approved_root / "app.py").resolve())]
    assert all(Path(path).is_absolute() for path in result)


def test_discovery_rejects_python_file_symlink_outside_project(approved_root, tmp_path):
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("pass\n", encoding="utf-8")
    link = approved_root / "linked.py"
    try:
        link.symlink_to(outside_file)
    except (OSError, NotImplementedError):
        pytest.skip("File symlinks are unavailable on this OS or account")

    with pytest.raises(InvalidInputError, match="outside"):
        discover_python_source_files(str(approved_root), [str(approved_root)])


def test_discovery_fails_when_maximum_depth_is_exceeded(approved_root, monkeypatch):
    monkeypatch.setattr(project_path_service, "MAX_SOURCE_DISCOVERY_DEPTH", 1)
    (approved_root / "level-one").mkdir()
    (approved_root / "level-one" / "level-two").mkdir()

    with pytest.raises(InvalidInputError, match="maximum depth"):
        discover_python_source_files(str(approved_root), [str(approved_root)])


def test_discovery_fails_when_maximum_file_count_is_exceeded(approved_root, monkeypatch):
    monkeypatch.setattr(project_path_service, "MAX_SOURCE_FILES", 2)
    for name in ("a.py", "b.py", "c.py"):
        (approved_root / name).write_text("pass\n", encoding="utf-8")

    with pytest.raises(InvalidInputError, match="maximum of 2"):
        discover_python_source_files(str(approved_root), [str(approved_root)])


def test_discovery_does_not_traverse_directory_symlinks(approved_root, tmp_path):
    (approved_root / "inside.py").write_text("pass\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "outside.py").write_text("pass\n", encoding="utf-8")
    link = approved_root / "external-directory"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks are unavailable on this OS or account")

    result = discover_python_source_files(str(approved_root), [str(approved_root)])

    assert result == [str((approved_root / "inside.py").resolve())]


def test_test_runner_reuses_shared_approved_root_validator(approved_root, tmp_path, monkeypatch):
    project = approved_root / "project"
    project.mkdir()
    monkeypatch.setattr(runner_settings, "APPROVED_PROJECT_ROOTS", [str(approved_root)])

    assert TestRunnerService()._validate_and_resolve_project_path(str(project)) == project.resolve()
    with pytest.raises(InvalidInputError, match="outside"):
        TestRunnerService()._validate_and_resolve_project_path(str(tmp_path))


def test_discovery_reports_inaccessible_directory(approved_root, monkeypatch):
    real_scandir = os.scandir

    def failing_scandir(path):
        if Path(path) == approved_root:
            raise PermissionError("access denied")
        return real_scandir(path)

    monkeypatch.setattr(project_path_service.os, "scandir", failing_scandir)
    with pytest.raises(InvalidInputError, match="Cannot read project directory"):
        discover_python_source_files(str(approved_root), [str(approved_root)])
