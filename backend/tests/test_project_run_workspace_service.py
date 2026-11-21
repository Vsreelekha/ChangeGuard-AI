import json
import logging
import os
import shutil
import stat
import threading
from pathlib import Path

import pytest

from app.core.exceptions import ChangeGuardException, InvalidInputError
from app.services import project_run_workspace_service as run_workspace_module
from app.services.project_run_workspace_service import ProjectRunWorkspaceService


def _make_project(workspace_root: Path, project_dir_name: str = "project") -> Path:
    project = workspace_root / "uploaded-id" / project_dir_name
    (project / "sample_project").mkdir(parents=True, exist_ok=True)
    (project / "sample_project" / "__init__.py").write_text("VALUE = 'original'\n", encoding="utf-8")
    (project / "tests").mkdir(parents=True, exist_ok=True)
    (project / "tests" / "test_sample.py").write_text("def test_value():\n    assert True\n", encoding="utf-8")
    return project


def test_run_workspace_copies_project_and_preserves_original(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    source_bytes = {
        path.relative_to(original): path.read_bytes()
        for path in original.rglob("*")
        if path.is_file()
    }
    service = ProjectRunWorkspaceService(workspace_root)

    with service.create_run_workspace(original) as run_project:
        assert run_project != original
        assert run_project.is_dir()
        assert run_project.resolve().is_relative_to(workspace_root.resolve())
        assert {
            path.relative_to(run_project): path.read_bytes()
            for path in run_project.rglob("*")
            if path.is_file()
        } == source_bytes
        (run_project / "sample_project" / "__init__.py").write_text("VALUE = 'patched'\n", encoding="utf-8")
        assert (original / "sample_project" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 'original'\n"


def test_run_workspace_cleans_up_after_normal_completion(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    with service.create_run_workspace(original) as run_project:
        run_directory = run_project.parent
        assert run_directory.exists()

    assert not run_directory.exists()
    assert original.is_dir()


def test_run_workspace_cleans_up_after_workflow_exception(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)
    run_directory = None

    with pytest.raises(RuntimeError, match="workflow failed"):
        with service.create_run_workspace(original) as run_project:
            run_directory = run_project.parent
            raise RuntimeError("workflow failed")

    assert run_directory is not None and not run_directory.exists()
    assert original.is_dir()


def test_rejects_source_outside_configured_workspace(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    outside_project = _make_project(outside_root)
    service = ProjectRunWorkspaceService(workspace_root)

    with pytest.raises(InvalidInputError, match="inside PROJECT_WORKSPACE_ROOT"):
        with service.create_run_workspace(outside_project):
            pytest.fail("outside project must not be yielded")

    assert list(workspace_root.iterdir()) == []


def test_source_symlink_rejection(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    outside = tmp_path / "outside-secret.py"
    outside.write_text("SECRET = True\n", encoding="utf-8")
    link = original / "sample_project" / "outside.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        link.write_text("not a link\n", encoding="utf-8")
        orig_probe = ProjectRunWorkspaceService._is_link_or_junction

        def mark_as_link(path, entry=None):
            if Path(path) == link:
                return True
            return orig_probe(path, entry)

        monkeypatch.setattr(ProjectRunWorkspaceService, "_is_link_or_junction", staticmethod(mark_as_link))

    service = ProjectRunWorkspaceService(workspace_root)
    with pytest.raises(InvalidInputError, match="symlinks or junctions"):
        with service.create_run_workspace(original):
            pytest.fail("project containing a link must not be yielded")

    assert outside.read_text(encoding="utf-8") == "SECRET = True\n"
    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []



def test_source_ancestor_symlink_rejection(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    intermediate_dir = workspace_root / "tenant_data"
    intermediate_dir.mkdir()
    project = _make_project(intermediate_dir)

    orig_probe = ProjectRunWorkspaceService._is_link_or_junction

    def mark_ancestor_link(path, entry=None):
        if Path(path) == intermediate_dir:
            return True
        return orig_probe(path, entry)

    monkeypatch.setattr(ProjectRunWorkspaceService, "_is_link_or_junction", staticmethod(mark_ancestor_link))

    service = ProjectRunWorkspaceService(workspace_root)
    with pytest.raises(InvalidInputError, match="symlinks or junctions"):
        with service.create_run_workspace(project):
            pytest.fail("project with symlinked ancestor must be rejected before resolving")

    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []



def test_workspace_root_with_symlink_or_junction_ancestor_is_rejected(tmp_path, monkeypatch):
    base_dir = tmp_path / "storage"
    base_dir.mkdir()
    workspace_root = base_dir / "private-workspaces"
    workspace_root.mkdir()

    orig_probe = ProjectRunWorkspaceService._is_link_or_junction

    def mark_base_as_link(path, entry=None):
        if Path(path) == base_dir:
            return True
        return orig_probe(path, entry)

    monkeypatch.setattr(ProjectRunWorkspaceService, "_is_link_or_junction", staticmethod(mark_base_as_link))

    service = ProjectRunWorkspaceService(workspace_root)
    with pytest.raises(InvalidInputError, match="cannot be a link or contain links"):
        service._resolve_workspace_root()


def test_windows_direntry_stat_zero_does_not_fail_directory_copy(tmp_path, monkeypatch):
    """Regression test: on Windows with Python 3.13, DirEntry.stat() returns st_dev=0, st_ino=0

    for directories while Path.lstat() returns actual non-zero values.
    Verify that legitimate directory copies succeed and do not fail with
    'Source directory identity changed during copying.'
    """
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_entry_stat = os.DirEntry.stat

    class _StatZeroIdentityProxy:
        def __init__(self, target):
            self._target = target

        @property
        def st_dev(self):
            return 0

        @property
        def st_ino(self):
            return 0

        def __getattr__(self, name):
            return getattr(self._target, name)

        def __getitem__(self, item):
            if item == 1:
                return 0
            if item == 2:
                return 0
            return self._target[item]

        def __iter__(self):
            for i, val in enumerate(self._target):
                if i in (1, 2):
                    yield 0
                else:
                    yield val

        def __len__(self):
            return len(self._target)

    def fake_direntry_stat(self, follow_symlinks=True):
        real_stat = orig_entry_stat(self, follow_symlinks=follow_symlinks)
        if stat.S_ISDIR(real_stat.st_mode):
            return _StatZeroIdentityProxy(real_stat)
        return real_stat

    monkeypatch.setattr(os.DirEntry, "stat", fake_direntry_stat)

    with service.create_run_workspace(original) as run_project:
        assert run_project.is_dir()
        assert (run_project / "sample_project" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 'original'\n"
        assert (run_project / "tests" / "test_sample.py").exists()


def test_copying_from_verified_source_handle(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    read_calls = []
    orig_read = os.read

    def tracked_read(fd, n):
        read_calls.append(fd)
        return orig_read(fd, n)

    monkeypatch.setattr(run_workspace_module.os, "read", tracked_read)

    with service.create_run_workspace(original) as run_project:
        assert len(read_calls) > 0
        copied_init = run_project / "sample_project" / "__init__.py"
        assert copied_init.read_text(encoding="utf-8") == "VALUE = 'original'\n"


def test_partial_write_in_file_copying_completes_successfully(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_write = os.write
    write_chunks = []

    def chunked_write(fd, data):
        b_data = bytes(data)
        to_write = min(len(b_data), 5)
        write_chunks.append(to_write)
        return orig_write(fd, b_data[:to_write])

    monkeypatch.setattr(run_workspace_module.os, "write", chunked_write)

    with service.create_run_workspace(original) as run_project:
        assert len(write_chunks) > 1
        copied_init = run_project / "sample_project" / "__init__.py"
        assert copied_init.read_text(encoding="utf-8") == "VALUE = 'original'\n"


def test_partial_write_zero_bytes_in_copy_fails_closed(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_write = os.write
    call_count = 0

    def zero_return_write(fd, data):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            return 0
        return orig_write(fd, data)

    monkeypatch.setattr(run_workspace_module.os, "write", zero_return_write)

    with pytest.raises(ChangeGuardException, match="Unable to copy|Unable to create an isolated project workspace"):
        with service.create_run_workspace(original):
            pytest.fail("write returning 0 bytes must raise an error and fail closed")

    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []



def test_partial_write_in_marker_creation_completes(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_write = os.write

    def small_writes(fd, data):
        b = bytes(data)
        to_write = min(len(b), 8)
        return orig_write(fd, b[:to_write])

    monkeypatch.setattr(run_workspace_module.os, "write", small_writes)

    with service.create_run_workspace(original) as run_project:
        marker = run_project.parent / run_workspace_module.OWNER_MARKER
        assert marker.exists()
        data = json.loads(marker.read_text(encoding="utf-8"))
        assert "token" in data and "run_dir" in data


def test_destination_file_creation_without_overwriting(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_copy_file = ProjectRunWorkspaceService._copy_file

    def pre_create_destination(cls, source_entry, destination_entry, destination_root, expected_stat):
        destination_entry.write_text("pre-existing destination\n", encoding="utf-8")
        orig_copy_file(source_entry, destination_entry, destination_root, expected_stat)

    monkeypatch.setattr(ProjectRunWorkspaceService, "_copy_file", classmethod(pre_create_destination))

    with pytest.raises(ChangeGuardException, match="already exists and cannot be safely overwritten|Unable to copy"):
        with service.create_run_workspace(original):
            pytest.fail("pre-existing destination file must trigger failure and not be overwritten")

    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []



def test_source_file_replacement_during_copying(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    injected = False
    orig_read = os.read

    def read_and_tamper(fd, n):
        nonlocal injected
        res = orig_read(fd, n)
        if not injected and res:
            injected = True
            (original / "sample_project" / "__init__.py").write_text("TAMPERED = True\n", encoding="utf-8")
        return res

    monkeypatch.setattr(run_workspace_module.os, "read", read_and_tamper)

    with pytest.raises(ChangeGuardException, match="modified|identity changed|Unable to copy"):
        with service.create_run_workspace(original):
            pytest.fail("source file modified during copying must fail closed")

    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []


def test_source_root_replacement_before_copy_fails_closed(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    original_files_before = {
        path.relative_to(original): path.read_bytes()
        for path in original.rglob("*")
        if path.is_file()
    }
    assert len(original_files_before) > 0

    orig_copy = ProjectRunWorkspaceService._copy_directory_contents
    replaced = False
    original_backup = original.parent / "original_preserved"

    def copy_with_replaced_root(
        cls,
        source: Path,
        destination: Path,
        source_root: Path,
        destination_root=None,
        snapshot=None,
    ):
        nonlocal replaced
        if not replaced and source == source_root:
            replaced = True
            # Replaces the source-root directory after snapshot creation but before the root copy begins.
            # Move original contents to original_backup to verify cleanup does not delete or alter them.
            source_root.rename(original_backup)
            source_root.mkdir()
            (source_root / "sample_project").mkdir()
            (source_root / "sample_project" / "__init__.py").write_text("VALUE = 'tampered'\n", encoding="utf-8")
        return orig_copy(source, destination, source_root, destination_root, snapshot)

    monkeypatch.setattr(
        ProjectRunWorkspaceService,
        "_copy_directory_contents",
        classmethod(copy_with_replaced_root),
    )

    with pytest.raises(ChangeGuardException, match="Source directory identity changed during copying."):
        with service.create_run_workspace(original):
            pytest.fail("source root replacement before copying must fail closed")

    assert replaced is True
    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []

    # Verifies that the original uploaded project is not deleted or modified by cleanup
    assert original_backup.is_dir()
    original_files_after = {
        path.relative_to(original_backup): path.read_bytes()
        for path in original_backup.rglob("*")
        if path.is_file()
    }
    assert original_files_after == original_files_before


def test_destination_root_replacement_fails_closed(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_verify_copy_tree(cls, copied_project, destination_root=None, expected_root_identity=None):
        raise ChangeGuardException("Run workspace identity changed during copy.", status_code=500)

    monkeypatch.setattr(
        ProjectRunWorkspaceService,
        "_verify_copy_tree",
        classmethod(fail_verify_copy_tree),
    )

    with pytest.raises(ChangeGuardException, match="Run workspace identity changed during copy."):
        with service.create_run_workspace(original):
            pytest.fail("destination replacement must fail closed")

    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []

    assert original.is_dir()


def test_cleanup_refusing_altered_ownership_marker_fails_explicitly(tmp_path, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    retained_run_dir = None
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ChangeGuardException, match="Run directory cleanup refused: ownership verification failed"):
            with service.create_run_workspace(original) as run_project:
                retained_run_dir = run_project.parent
                marker = retained_run_dir / run_workspace_module.OWNER_MARKER
                assert marker.exists()
                marker.write_text(json.dumps({"token": "tampered_token", "run_dir": retained_run_dir.name}), encoding="utf-8")

    try:
        assert "ownership marker verification failed; refusing cleanup" in caplog.text
        assert retained_run_dir is not None and retained_run_dir.exists()
    finally:
        if retained_run_dir and retained_run_dir.exists():
            shutil.rmtree(retained_run_dir, ignore_errors=True)


def test_marker_creation_failure_cleans_up_safely(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_marker(*_args, **_kwargs):
        raise OSError("simulated marker creation failure")

    monkeypatch.setattr(
        ProjectRunWorkspaceService,
        "_write_owner_marker",
        classmethod(fail_marker),
    )

    with pytest.raises(ChangeGuardException, match="Unable to create an isolated project workspace"):
        with service.create_run_workspace(original):
            pytest.fail("marker creation failure must fail closed")

    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []

    assert original.is_dir()


def test_read_only_file_cleanup_succeeds(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    run_dir = None
    with service.create_run_workspace(original) as run_project:
        run_dir = run_project.parent
        ro_file = run_project / "sample_project" / "readonly_file.txt"
        ro_file.write_text("read-only data", encoding="utf-8")
        os.chmod(ro_file, stat.S_IREAD)

    assert run_dir is not None
    assert not run_dir.exists()
    assert original.is_dir()


def test_cleanup_failure_during_creation_preserves_creation_exception(tmp_path, monkeypatch, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_copy(*_args, **_kwargs):
        raise ChangeGuardException("simulated creation failure", status_code=500)

    def fail_rmtree(*_args, **_kwargs):
        raise PermissionError("simulated permission denied during cleanup")

    monkeypatch.setattr(ProjectRunWorkspaceService, "_copy_directory_contents", classmethod(fail_copy))
    monkeypatch.setattr(ProjectRunWorkspaceService, "_rmtree_safely", classmethod(fail_rmtree))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ChangeGuardException, match="simulated creation failure"):
            with service.create_run_workspace(original):
                pass

    for d in workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*"):
        shutil.rmtree(d, ignore_errors=True)

    assert "Failed to clean up run workspace directory" in caplog.text


def test_cleanup_failure_during_workflow_preserves_workflow_exception(tmp_path, monkeypatch, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_rmtree(*_args, **_kwargs):
        raise PermissionError("simulated permission denied during cleanup")

    monkeypatch.setattr(ProjectRunWorkspaceService, "_rmtree_safely", classmethod(fail_rmtree))

    retained_run_dir = None
    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="primary workflow error"):
            with service.create_run_workspace(original) as run_project:
                retained_run_dir = run_project.parent
                raise RuntimeError("primary workflow error")

    try:
        assert "Failed to clean up run workspace directory" in caplog.text
        assert retained_run_dir is not None and retained_run_dir.exists()
    finally:
        if retained_run_dir and retained_run_dir.exists():
            shutil.rmtree(retained_run_dir, ignore_errors=True)


def test_cleanup_only_failure_is_propagated(tmp_path, monkeypatch, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_rmtree(*_args, **_kwargs):
        raise PermissionError("simulated permission denied during cleanup")

    monkeypatch.setattr(ProjectRunWorkspaceService, "_rmtree_safely", classmethod(fail_rmtree))

    retained_run_dir = None
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ChangeGuardException, match="Failed to clean up run workspace directory"):
            with service.create_run_workspace(original) as run_project:
                retained_run_dir = run_project.parent
                assert (run_project / "sample_project" / "__init__.py").exists()

    try:
        assert "Failed to clean up run workspace directory" in caplog.text
        assert retained_run_dir is not None and retained_run_dir.exists()
    finally:
        if retained_run_dir and retained_run_dir.exists():
            shutil.rmtree(retained_run_dir, ignore_errors=True)


def test_keyboard_interrupt_preserves_base_exception_and_not_wrapped(tmp_path, monkeypatch):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_verify(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated interrupt")

    monkeypatch.setattr(ProjectRunWorkspaceService, "_verify_copy_tree", classmethod(fail_verify))

    with pytest.raises(KeyboardInterrupt):
        with service.create_run_workspace(original):
            pytest.fail("KeyboardInterrupt must propagate unwrapped")


def test_keyboard_interrupt_preserved_even_if_cleanup_fails(tmp_path, monkeypatch, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    def fail_copy(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated interrupt during copy")

    def fail_rmtree(*_args, **_kwargs):
        raise PermissionError("cleanup permission denied")

    monkeypatch.setattr(ProjectRunWorkspaceService, "_copy_directory_contents", classmethod(fail_copy))
    monkeypatch.setattr(ProjectRunWorkspaceService, "_rmtree_safely", classmethod(fail_rmtree))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(KeyboardInterrupt):
            with service.create_run_workspace(original):
                pytest.fail("KeyboardInterrupt must be preserved and not masked by cleanup failure")

    for d in workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*"):
        shutil.rmtree(d, ignore_errors=True)

    assert "Failed to clean up run workspace directory" in caplog.text


def test_rmtree_safely_walk_error_is_logged_and_raised(tmp_path, monkeypatch, caplog):
    test_dir = tmp_path / "walk_test"
    test_dir.mkdir()
    (test_dir / "file.txt").write_text("data", encoding="utf-8")

    orig_walk = os.walk

    def fail_walk(top, **kwargs):
        onerror = kwargs.get("onerror")
        if onerror:
            onerror(PermissionError("simulated traversal error"))
        return orig_walk(top, **kwargs)

    monkeypatch.setattr(run_workspace_module.os, "walk", fail_walk)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(PermissionError, match="simulated traversal error"):
            ProjectRunWorkspaceService._rmtree_safely(test_dir)

    assert "Traversal error during workspace cleanup walk" in caplog.text


def test_copy_file_unlink_failure_preserves_original_copy_exception(tmp_path, monkeypatch, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_copy_file = ProjectRunWorkspaceService._copy_file

    def fail_write_during_copy_file(cls, source_entry, destination_entry, destination_root, expected_stat):
        # Inject write failure specifically for project file copying, after owner marker was written
        def fail_write(fd, data):
            raise OSError("simulated disk write failure")
        monkeypatch.setattr(run_workspace_module.os, "write", fail_write)

        orig_unlink = Path.unlink
        def fail_unlink(self, *args, **kwargs):
            if self.name == "__init__.py" or self.suffix == ".py":
                raise PermissionError("simulated unlink failure")
            return orig_unlink(self, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", fail_unlink)

        return orig_copy_file(source_entry, destination_entry, destination_root, expected_stat)

    monkeypatch.setattr(ProjectRunWorkspaceService, "_copy_file", classmethod(fail_write_during_copy_file))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ChangeGuardException, match="Unable to copy|Unable to create an isolated project workspace"):
            with service.create_run_workspace(original):
                pytest.fail("original copy exception must be preserved")

    assert "Failed to unlink partial destination file" in caplog.text
    for d in workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*"):
        shutil.rmtree(d, ignore_errors=True)


def test_copy_file_close_failure_surfaces_when_no_active_exception(tmp_path, monkeypatch, caplog):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    orig_copy_file = ProjectRunWorkspaceService._copy_file
    orig_close = os.close
    close_failed = False

    def copy_file_with_failing_dest_close(cls, source_entry, destination_entry, destination_root, expected_stat):
        nonlocal close_failed
        # Target the close failure specifically to the destination file in _copy_file
        def fail_dest_close(fd):
            nonlocal close_failed
            if not close_failed:
                close_failed = True
                raise OSError("simulated close failure on destination")
            return orig_close(fd)

        monkeypatch.setattr(run_workspace_module.os, "close", fail_dest_close)
        return orig_copy_file(source_entry, destination_entry, destination_root, expected_stat)

    monkeypatch.setattr(ProjectRunWorkspaceService, "_copy_file", classmethod(copy_file_with_failing_dest_close))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ChangeGuardException, match="Failed to finalize file copying|Unable to copy|Unable to create"):
            with service.create_run_workspace(original):
                pytest.fail("close failure must surface when copy succeeded")

    assert "Failed to close destination file descriptor" in caplog.text
    for d in workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*"):
        shutil.rmtree(d, ignore_errors=True)


def test_real_overlapping_concurrent_runs_with_events(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    service = ProjectRunWorkspaceService(workspace_root)

    run1_started = threading.Event()
    run2_finished = threading.Event()
    results = {}
    errors = []

    def worker1():
        try:
            with service.create_run_workspace(original) as run1:
                results["run1_dir"] = run1.parent
                results["run1_content"] = (run1 / "sample_project" / "__init__.py").read_text(encoding="utf-8")
                run1_started.set()
                run2_finished.wait(timeout=10.0)
                assert run1.parent.exists()
                assert (run1 / "sample_project" / "__init__.py").read_text(encoding="utf-8") == "VALUE = 'original'\n"
        except Exception as e:
            errors.append(e)

    def worker2():
        try:
            run1_started.wait(timeout=10.0)
            with service.create_run_workspace(original) as run2:
                results["run2_dir"] = run2.parent
                (run2 / "sample_project" / "__init__.py").write_text("VALUE = 'run2'\n", encoding="utf-8")
                results["run2_content"] = (run2 / "sample_project" / "__init__.py").read_text(encoding="utf-8")
            assert not results["run2_dir"].exists()
            run2_finished.set()
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker1)
    t2 = threading.Thread(target=worker2)

    t1.start()
    t2.start()
    t1.join(timeout=15.0)
    t2.join(timeout=15.0)

    assert errors == []
    assert results["run1_dir"] != results["run2_dir"]
    assert results["run1_content"] == "VALUE = 'original'\n"
    assert results["run2_content"] == "VALUE = 'run2'\n"
    assert list(workspace_root.glob(f"{run_workspace_module.RUN_DIRECTORY_PREFIX}*")) == []



def test_cleanup_never_deletes_original_or_workspace_root_or_other_run(tmp_path):
    workspace_root = tmp_path / "private-workspaces"
    workspace_root.mkdir()
    original = _make_project(workspace_root)
    other_run = workspace_root / f"{run_workspace_module.RUN_DIRECTORY_PREFIX}other"
    other_run.mkdir()
    (other_run / "marker.txt").write_text("keep me", encoding="utf-8")

    try:
        with pytest.raises(ChangeGuardException, match="Run directory cleanup refused"):
            ProjectRunWorkspaceService._cleanup_run_directory(
                original, workspace_root, "invalid-token", source_root=original
            )
        assert original.is_dir()

        with pytest.raises(ChangeGuardException, match="Run directory cleanup refused"):
            ProjectRunWorkspaceService._cleanup_run_directory(
                workspace_root, workspace_root, "invalid-token", source_root=original
            )
        assert workspace_root.is_dir()

        with pytest.raises(ChangeGuardException, match="Run directory cleanup refused"):
            ProjectRunWorkspaceService._cleanup_run_directory(
                other_run, workspace_root, "token-does-not-match", source_root=original
            )
        assert other_run.is_dir()
        assert (other_run / "marker.txt").exists()
    finally:
        if other_run.exists():
            shutil.rmtree(other_run, ignore_errors=True)
