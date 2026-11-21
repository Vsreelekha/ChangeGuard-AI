import io
import json
import os
import stat
import struct
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.exceptions import ChangeGuardException, InvalidInputError, WorkspaceQuotaError
from app.services.project_workspace_service import (
    OWNERSHIP_MARKER,
    RESERVATION_OVERHEAD_BYTES,
    STAGING_MARKER,
    ProjectWorkspaceService,
)


def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries:
            if isinstance(content, zipfile.ZipInfo):
                info = content
                info.filename = name
                archive.writestr(info, b"link-target")
            else:
                archive.writestr(name, content)
    buffer.seek(0)
    return buffer


@pytest.fixture
def workspace_service(tmp_path):
    approved_root = tmp_path / "approved"
    approved_root.mkdir()
    workspace_root = approved_root / "private-workspaces"
    workspace_root.mkdir()
    return ProjectWorkspaceService(
        str(workspace_root),
        [str(approved_root)],
        max_upload_bytes=2_000_000,
        max_extracted_bytes=1_000_000,
        max_file_bytes=500_000,
        max_files=100,
        max_entries=100,
        max_depth=8,
        workspace_ttl_hours=1,
        staging_ttl_hours=1,
    )


def test_creates_unpredictable_project_and_publishes_atomically(workspace_service):
    result = workspace_service.create_project(make_zip([
        ("src/app.py", "def run():\n    return 1\n"),
        ("tests/test_app.py", "def test_run():\n    assert True\n"),
    ]))

    assert len(result["project_id"]) == 64
    assert all(char in "0123456789abcdef" for char in result["project_id"])
    assert result["file_count"] == 2
    assert result["expires_at"].tzinfo == timezone.utc
    project_dir = workspace_service.resolve_project_id(result["project_id"])
    assert project_dir.name == "project"
    assert (project_dir / "src" / "app.py").is_file()
    assert not list(project_dir.parent.parent.glob(".staging-*"))


@pytest.mark.parametrize("name", [
    "../escape.py",
    "/absolute.py",
    "C:/drive.py",
    "folder\\..\\escape.py",
    "folder//empty-component.py",
    "folder/./dot.py",
    "folder/../parent.py",
    "CON.txt",
    "trailing-dot.py.",
])
def test_rejects_unsafe_zip_paths(workspace_service, name):
    with pytest.raises(InvalidInputError):
        workspace_service.create_project(make_zip([(name, "print('unsafe')")]))


def test_rejects_nul_in_archive_path(workspace_service):
    info = zipfile.ZipInfo("placeholder.py")
    info.filename = "bad\x00name.py"
    with pytest.raises(InvalidInputError, match="unsafe entry path"):
        workspace_service._validate_entries([info])


@pytest.mark.parametrize("file_type", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK])
def test_rejects_symlinks_and_special_entries(workspace_service, file_type):
    info = zipfile.ZipInfo("src/app.py")
    info.external_attr = (file_type | 0o777) << 16
    with pytest.raises(InvalidInputError, match="symlinks|special file"):
        workspace_service.create_project(make_zip([("src/app.py", info)]))


def test_rejects_duplicate_normalized_paths(workspace_service):
    with pytest.raises(InvalidInputError, match="duplicate normalized"):
        workspace_service.create_project(make_zip([
            ("src/app.py", "one"),
            ("SRC/APP.PY", "two"),
        ]))


def test_rejects_file_directory_collisions(workspace_service):
    with pytest.raises(InvalidInputError, match="parent directory|collision"):
        workspace_service.create_project(make_zip([
            ("src", "file"),
            ("src/app.py", "code"),
        ]))


def test_enforces_actual_upload_size(workspace_service):
    workspace_service.max_upload_bytes = 16
    with pytest.raises(InvalidInputError, match="upload exceeds"):
        workspace_service.create_project(make_zip([("app.py", "print('large enough')")]))


def test_enforces_extracted_and_per_file_limits(workspace_service):
    workspace_service.max_file_bytes = 10
    with pytest.raises(InvalidInputError, match="per-file"):
        workspace_service.create_project(make_zip([("app.py", "x" * 11)]))

    workspace_service.max_file_bytes = 100
    workspace_service.max_extracted_bytes = 12
    with pytest.raises(InvalidInputError, match="extracted-size"):
        workspace_service.create_project(make_zip([
            ("app.py", "x" * 7),
            ("test_app.py", "y" * 7),
        ]))


def test_enforces_entry_and_depth_limits(workspace_service):
    workspace_service.max_entries = 1
    with pytest.raises(InvalidInputError, match="entry limit"):
        workspace_service.create_project(make_zip([
            ("app.py", "pass"),
            ("test_app.py", "pass"),
        ]))

    workspace_service.max_entries = 10
    workspace_service.max_depth = 2
    with pytest.raises(InvalidInputError, match="nesting limit"):
        workspace_service.create_project(make_zip([("a/b/c/app.py", "pass")]))


def test_enforces_regular_file_count_limit(workspace_service):
    workspace_service.max_files = 1
    with pytest.raises(InvalidInputError, match="file limit"):
        workspace_service.create_project(make_zip([
            ("app.py", "pass"),
            ("tests/test_app.py", "pass"),
        ]))


def test_rejects_invalid_zip_and_cleans_staging(workspace_service):
    root = Path(workspace_service.workspace_root)
    with pytest.raises(InvalidInputError, match="valid, safely extractable"):
        workspace_service.create_project(io.BytesIO(b"not a zip"))
    assert list(root.iterdir()) == []


def test_requires_workspace_inside_approved_roots(tmp_path):
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    approved.mkdir()
    outside.mkdir()
    service = ProjectWorkspaceService(str(outside), [str(approved)])
    with pytest.raises(InvalidInputError, match="outside"):
        service.create_project(make_zip([("app.py", "pass")]))


def test_unconfigured_workspace_fails_closed():
    service = ProjectWorkspaceService("", [])
    with pytest.raises(ChangeGuardException) as raised:
        service.create_project(make_zip([("app.py", "pass")]))
    assert raised.value.status_code == 503


def test_rejects_unchecked_project_ids(workspace_service):
    for project_id in ("../other", "C:/other", "A" * 64, "1" * 63):
        with pytest.raises(InvalidInputError, match="invalid project identifier"):
            workspace_service.resolve_project_id(project_id)


def test_resolver_expires_and_removes_workspace(workspace_service):
    result = workspace_service.create_project(make_zip([("app.py", "pass")]))
    workspace = Path(workspace_service.workspace_root) / result["project_id"]
    metadata_path = workspace / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(InvalidInputError, match="expired"):
        workspace_service.resolve_project_id(result["project_id"])
    assert workspace.exists()


def test_cleanup_removes_expired_and_stale_incomplete_workspaces(workspace_service):
    result = workspace_service.create_project(make_zip([("app.py", "pass")]))
    root = Path(workspace_service.workspace_root)
    workspace = root / result["project_id"]
    metadata_path = workspace / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    staging = root / (".staging-" + "a" * 32)
    staging.mkdir()
    workspace_service._write_marker(staging / ".changeguard-staging.json", staging.name, kind="staging")
    old_time = (datetime.now().timestamp() - 7200, datetime.now().timestamp() - 7200)
    os.utime(staging, old_time)

    removed = workspace_service.cleanup_expired_workspaces()
    assert removed == 2
    assert not workspace.exists()
    assert not staging.exists()


def _expire_workspace(service, result):
    workspace = Path(service.workspace_root) / result["project_id"]
    metadata_path = workspace / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return workspace


def test_active_lease_prevents_cleanup_and_releases_after_failure(workspace_service):
    result = workspace_service.create_project(make_zip([("app.py", "pass")]))
    workspace = Path(workspace_service.workspace_root) / result["project_id"]
    with pytest.raises(RuntimeError):
        with workspace_service.lease_project_id(result["project_id"]) as project_dir:
            assert project_dir.is_dir()
            _expire_workspace(workspace_service, result)
            assert workspace_service.cleanup_expired_workspaces() == 0
            raise RuntimeError("simulated workflow failure")
    assert workspace.exists()
    assert workspace_service.cleanup_expired_workspaces() == 1
    assert not workspace.exists()


def test_expired_workspace_rejects_new_lease(workspace_service):
    result = workspace_service.create_project(make_zip([("app.py", "pass")]))
    _expire_workspace(workspace_service, result)
    with pytest.raises(InvalidInputError, match="expired"):
        with workspace_service.lease_project_id(result["project_id"]):
            pytest.fail("expired project was leased")


def test_cleanup_leaves_unowned_or_invalid_metadata_directories_untouched(workspace_service, caplog):
    root = Path(workspace_service.workspace_root)
    unowned = root / ("b" * 64)
    unowned.mkdir()
    invalid = root / ("c" * 64)
    invalid.mkdir()
    workspace_service._write_marker(invalid / ".changeguard-owner.json", "c" * 64, kind="workspace")
    invalid_marker = root / ("e" * 64)
    invalid_marker.mkdir()
    (invalid_marker / ".changeguard-owner.json").write_text("{}", encoding="utf-8")
    old = (datetime.now().timestamp() - 7200, datetime.now().timestamp() - 7200)
    os.utime(unowned, old)
    os.utime(invalid, old)
    assert workspace_service.cleanup_expired_workspaces() == 0
    assert unowned.exists() and invalid.exists() and invalid_marker.exists()
    assert "Leaving workspace" in caplog.text


def test_cleanup_does_not_remove_active_staging_extraction(workspace_service):
    root = Path(workspace_service.workspace_root)
    staging = root / (".staging-" + "d" * 32)
    staging.mkdir()
    workspace_service._write_marker(staging / ".changeguard-staging.json", staging.name, kind="staging")
    old = (datetime.now().timestamp() - 7200, datetime.now().timestamp() - 7200)
    os.utime(staging, old)
    key = (workspace_service._root_key(root), staging.name)
    with workspace_service._state_lock:
        workspace_service._active_staging.add(key)
    try:
        assert workspace_service.cleanup_expired_workspaces() == 0
        assert staging.exists()
    finally:
        with workspace_service._state_lock:
            workspace_service._active_staging.discard(key)


def test_aggregate_storage_quota_counts_existing_workspaces(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    root = approved / "workspaces"
    root.mkdir()
    service = ProjectWorkspaceService(
        str(root), [str(approved)], max_extracted_bytes=100_000, max_workspace_bytes=140_000,
        max_upload_bytes=1_000_000, max_file_bytes=100_000,
    )
    result = service.create_project(make_zip([("app.py", "x" * 50_000)]))
    published = root / result["project_id"]
    assert service._committed_workspace_bytes(root) >= (published / "project" / "app.py").stat().st_size
    with pytest.raises(WorkspaceQuotaError, match="storage capacity"):
        service.create_project(make_zip([("app.py", "small")]))


def test_reservation_includes_extracted_limit_and_generated_file_overhead(workspace_service):
    workspace_service.max_extracted_bytes = 512
    expected = 512 + RESERVATION_OVERHEAD_BYTES
    assert workspace_service._upload_reservation_bytes() == expected

    root = workspace_service._validated_workspace_root()
    token = "overhead-test"
    workspace_service.max_workspace_bytes = expected
    workspace_service._reserve_upload(root, token)
    assert ProjectWorkspaceService._reservations[workspace_service._root_key(root)][token] == expected
    workspace_service._release_reservation(root, token)


def test_upload_at_exact_configured_capacity_succeeds(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    root = approved / "workspaces"
    root.mkdir()
    service = ProjectWorkspaceService(
        str(root), [str(approved)], max_upload_bytes=100_000, max_extracted_bytes=1024,
        max_file_bytes=1024, max_workspace_bytes=1024 + RESERVATION_OVERHEAD_BYTES,
    )
    result = service.create_project(make_zip([("app.py", "pass")]))
    assert (root / result["project_id"]).is_dir()
    assert service._committed_workspace_bytes(root) <= service.max_workspace_bytes
    assert service._root_key(root) not in ProjectWorkspaceService._reservations


def test_active_staging_is_covered_by_reservation_without_double_counting(workspace_service):
    root = workspace_service._validated_workspace_root()
    workspace_service.max_extracted_bytes = 512
    workspace_service.max_workspace_bytes = workspace_service._upload_reservation_bytes()
    token = "active-stage-test"
    workspace_service._reserve_upload(root, token)
    stage = root / (".staging-" + "f" * 32)
    stage.mkdir()
    workspace_service._write_marker(stage / STAGING_MARKER, stage.name, kind="staging")
    (stage / "partial.py").write_bytes(b"partial")
    key = (workspace_service._root_key(root), stage.name)
    with workspace_service._state_lock:
        workspace_service._active_staging.add(key)
    try:
        assert workspace_service._committed_workspace_bytes(root) == 0
        assert sum(ProjectWorkspaceService._reservations[workspace_service._root_key(root)].values()) == (
            workspace_service._upload_reservation_bytes()
        )
    finally:
        with workspace_service._state_lock:
            workspace_service._active_staging.discard(key)
        workspace_service._release_reservation(root, token)


def test_invalid_active_staging_marker_fails_quota_check_closed(workspace_service):
    root = workspace_service._validated_workspace_root()
    stage = root / (".staging-" + "7" * 32)
    stage.mkdir()
    (stage / STAGING_MARKER).write_text("invalid", encoding="utf-8")
    key = (workspace_service._root_key(root), stage.name)
    with workspace_service._state_lock:
        workspace_service._active_staging.add(key)
    try:
        with pytest.raises(WorkspaceQuotaError, match="ownership is invalid"):
            workspace_service._committed_workspace_bytes(root)
    finally:
        with workspace_service._state_lock:
            workspace_service._active_staging.discard(key)


def test_crash_left_staging_is_counted_after_service_restart(workspace_service):
    root = workspace_service._validated_workspace_root()
    stage = root / (".staging-" + "9" * 32)
    stage.mkdir()
    workspace_service._write_marker(stage / STAGING_MARKER, stage.name, kind="staging")
    (stage / "partial.py").write_bytes(b"crash-left-bytes")
    key = workspace_service._root_key(root)
    with workspace_service._state_lock:
        ProjectWorkspaceService._active_staging.discard((key, stage.name))
        ProjectWorkspaceService._reservations.pop(key, None)

    restarted = ProjectWorkspaceService(
        str(root), workspace_service.approved_roots,
        max_extracted_bytes=32, max_workspace_bytes=128, max_concurrent_uploads=2,
    )
    expected = sum(item.stat().st_size for item in stage.iterdir() if item.is_file())
    assert restarted._committed_workspace_bytes(root) == expected
    with pytest.raises(WorkspaceQuotaError, match="storage capacity"):
        restarted._reserve_upload(root, "after-restart")


def test_unowned_staging_is_counted_but_never_cleaned(workspace_service):
    root = workspace_service._validated_workspace_root()
    stage = root / (".staging-" + "8" * 32)
    stage.mkdir()
    (stage / STAGING_MARKER).write_text("not valid ownership metadata", encoding="utf-8")
    (stage / "unowned.bin").write_bytes(b"x" * 64)
    usage = workspace_service._committed_workspace_bytes(root)
    assert usage >= 64
    workspace_service.max_workspace_bytes = usage + workspace_service._upload_reservation_bytes() - 1
    with pytest.raises(WorkspaceQuotaError, match="storage capacity"):
        workspace_service._reserve_upload(root, "unowned-stage")
    workspace_service.cleanup_expired_workspaces()
    assert stage.exists()


def test_failed_upload_releases_reservation(workspace_service):
    root = workspace_service._validated_workspace_root()
    key = workspace_service._root_key(root)
    with pytest.raises(InvalidInputError):
        workspace_service.create_project(io.BytesIO(b"not a zip"))
    assert key not in ProjectWorkspaceService._reservations


def test_successful_publication_is_visible_before_reservation_release(workspace_service, monkeypatch):
    root = workspace_service._validated_workspace_root()
    original_release = workspace_service._release_reservation
    observed = []

    def inspect_before_release(reservation_root, token):
        if token in ProjectWorkspaceService._reservations.get(workspace_service._root_key(root), {}):
            published = [child for child in root.iterdir() if child.is_dir() and len(child.name) == 64]
            assert len(published) == 1
            observed.append(workspace_service._committed_workspace_bytes(root))
        original_release(reservation_root, token)

    monkeypatch.setattr(workspace_service, "_release_reservation", inspect_before_release)
    result = workspace_service.create_project(make_zip([("app.py", "visible")]))
    assert observed and observed[0] > 0
    assert (root / result["project_id"] / OWNERSHIP_MARKER).is_file()
    assert workspace_service._root_key(root) not in ProjectWorkspaceService._reservations


def test_cleanup_reduces_scanned_usage_after_successful_deletion(workspace_service):
    result = workspace_service.create_project(make_zip([("app.py", "cleanup")]))
    workspace = _expire_workspace(workspace_service, result)
    before = workspace_service._committed_workspace_bytes(Path(workspace_service.workspace_root))
    assert before > 0
    assert workspace_service.cleanup_expired_workspaces() == 1
    assert not workspace.exists()
    assert workspace_service._committed_workspace_bytes(Path(workspace_service.workspace_root)) == 0


def test_concurrent_reservations_cannot_exceed_storage_capacity(workspace_service):
    root = workspace_service._validated_workspace_root()
    barrier = threading.Barrier(3)
    outcomes = []
    reservation_size = 10 + RESERVATION_OVERHEAD_BYTES
    service = ProjectWorkspaceService(
        str(root), workspace_service.approved_roots, max_extracted_bytes=10,
        max_workspace_bytes=reservation_size * 2 - 1, max_concurrent_uploads=2,
    )

    def reserve(token):
        barrier.wait()
        try:
            service._reserve_upload(root, token)
            outcomes.append((token, "reserved"))
        except Exception:
            outcomes.append((token, "rejected"))

    threads = [threading.Thread(target=reserve, args=(str(index),)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcome for _, outcome in outcomes) == ["rejected", "reserved"]
    reservations = ProjectWorkspaceService._reservations[service._root_key(root)]
    assert sum(reservations.values()) <= service.max_workspace_bytes
    for token, outcome in outcomes:
        if outcome == "reserved":
            service._release_reservation(root, token)


def _mutate_zip_name_nul(data):
    changed = bytearray(data)
    central = changed.index(b"PK\x01\x02")
    name_length = struct.unpack_from("<H", changed, central + 28)[0]
    local = changed.index(b"PK\x03\x04")
    assert name_length >= 2
    changed[central + 46 + 1] = 0
    changed[local + 30 + 1] = 0
    return io.BytesIO(changed)


def test_rejects_raw_nul_zip_filename_bytes(workspace_service):
    archive = make_zip([("app.py", "pass")])
    with pytest.raises(InvalidInputError, match="NUL byte"):
        workspace_service.create_project(_mutate_zip_name_nul(archive.getvalue()))


@pytest.mark.parametrize("corruption", ["deflate", "crc"])
def test_corrupt_deflate_and_crc_are_client_errors(workspace_service, corruption):
    archive = make_zip([("app.py", "compressible text " * 1000)])
    data = bytearray(archive.getvalue())
    local = data.index(b"PK\x03\x04")
    name_length, extra_length = struct.unpack_from("<HH", data, local + 26)
    payload = local + 30 + name_length + extra_length
    central = data.index(b"PK\x01\x02")
    if corruption == "deflate":
        data[payload + 1] ^= 0xFF
    else:
        data[local + 14] ^= 0x01
        data[central + 16] ^= 0x01
    with pytest.raises(InvalidInputError):
        workspace_service.create_project(io.BytesIO(data))


def test_failed_staging_cleanup_is_logged(workspace_service, monkeypatch, caplog):
    def fail_rmtree(_path):
        raise PermissionError("simulated cleanup failure")
    monkeypatch.setattr("app.services.project_workspace_service.shutil.rmtree", fail_rmtree)
    with pytest.raises(InvalidInputError):
        workspace_service.create_project(io.BytesIO(b"not a zip"))
    assert "Failed to remove incomplete project workspace" in caplog.text
