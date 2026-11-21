"""Securely store and resolve temporary project workspaces from ZIP uploads."""

import json
import os
import re
import secrets
import shutil
import stat
import struct
import threading
import unicodedata
import zipfile
import zlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from typing import BinaryIO, Dict, Iterator, List, Optional, Sequence, Tuple

from app.core.config import get_settings
from app.core.exceptions import ChangeGuardException, InvalidInputError, UploadTooLargeError, WorkspaceQuotaError
from app.core.logging_config import logger
from app.services.project_path_service import validate_project_path


PROJECT_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STAGING_NAME_PATTERN = re.compile(r"^\.staging-[0-9a-f]{32}$")
OWNERSHIP_MARKER = ".changeguard-owner.json"
STAGING_MARKER = ".changeguard-staging.json"
APP_MARKER = "changeguard-ai-project-workspace-v1"
CHUNK_SIZE = 64 * 1024
RESERVATION_OVERHEAD_BYTES = 32 * 1024
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ProjectWorkspaceService:
    """Create short-lived workspaces without trusting archive paths or IDs."""

    # These guards coordinate threads in this Python process only. Deployments
    # with multiple workers need a shared reservation/lease coordinator.
    _state_lock = threading.RLock()
    _reservations: Dict[str, Dict[str, int]] = {}
    _active_staging: set[Tuple[str, str]] = set()
    _leases: Dict[Tuple[str, str], int] = {}

    def __init__(
        self,
        workspace_root: Optional[str] = None,
        approved_roots: Optional[Sequence[str]] = None,
        *,
        max_upload_bytes: Optional[int] = None,
        max_extracted_bytes: Optional[int] = None,
        max_file_bytes: Optional[int] = None,
        max_files: Optional[int] = None,
        max_entries: Optional[int] = None,
        max_depth: Optional[int] = None,
        workspace_ttl_hours: Optional[int] = None,
        staging_ttl_hours: Optional[int] = None,
        max_workspace_bytes: Optional[int] = None,
        max_concurrent_uploads: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self.workspace_root = workspace_root if workspace_root is not None else settings.PROJECT_WORKSPACE_ROOT
        self.approved_roots = approved_roots if approved_roots is not None else settings.APPROVED_PROJECT_ROOTS
        self.max_upload_bytes = max_upload_bytes or settings.PROJECT_UPLOAD_MAX_BYTES
        self.max_extracted_bytes = max_extracted_bytes or settings.PROJECT_EXTRACTED_MAX_BYTES
        self.max_file_bytes = max_file_bytes or settings.PROJECT_FILE_MAX_BYTES
        self.max_files = max_files or settings.PROJECT_ARCHIVE_MAX_FILES
        self.max_entries = max_entries or settings.PROJECT_ARCHIVE_MAX_ENTRIES
        self.max_depth = max_depth or settings.PROJECT_ARCHIVE_MAX_DEPTH
        self.workspace_ttl_hours = workspace_ttl_hours or settings.PROJECT_WORKSPACE_TTL_HOURS
        self.staging_ttl_hours = staging_ttl_hours or settings.PROJECT_STAGING_TTL_HOURS
        self.max_workspace_bytes = max_workspace_bytes or settings.PROJECT_WORKSPACE_MAX_BYTES
        self.max_concurrent_uploads = max_concurrent_uploads or settings.PROJECT_UPLOAD_MAX_CONCURRENT

    @staticmethod
    def _root_key(root: Path) -> str:
        return os.path.normcase(str(root))

    def _committed_workspace_bytes(self, root: Path) -> int:
        """Count disk files, including inactive staging, without following links.

        An active staging tree is represented by its full reservation instead;
        omitting that tree here prevents counting its extracted bytes twice.
        After a process restart its process-local active marker is gone, so its
        actual bytes are counted here until cleanup removes it.
        """
        total = 0

        def traversal_error(error: OSError) -> None:
            raise WorkspaceQuotaError("Cannot safely measure existing project workspace storage.") from error

        for current, directories, files in os.walk(root, followlinks=False, onerror=traversal_error):
            current_path = Path(current)
            retained_directories = []
            for name in directories:
                candidate_directory = current_path / name
                if candidate_directory.is_symlink() or bool(
                    getattr(os.path, "isjunction", lambda _: False)(candidate_directory)
                ):
                    continue
                try:
                    relative_parts = candidate_directory.relative_to(root).parts
                except ValueError as exc:
                    raise WorkspaceQuotaError("Workspace traversal escaped its configured root.") from exc
                active_staging = (
                    len(relative_parts) == 1
                    and STAGING_NAME_PATTERN.fullmatch(name)
                    and (self._root_key(root), name) in self._active_staging
                )
                staging_marker = candidate_directory / STAGING_MARKER
                if active_staging:
                    if not os.path.lexists(staging_marker) or self._valid_marker(staging_marker, name, "staging"):
                        # Its reservation covers the full extraction bound.
                        continue
                    raise WorkspaceQuotaError("Active staging workspace ownership is invalid; quota check failed closed.")
                retained_directories.append(name)
            directories[:] = retained_directories

            for name in files:
                candidate = current_path / name
                try:
                    info = candidate.lstat()
                    if stat.S_ISREG(info.st_mode):
                        total += info.st_size
                except OSError:
                    raise WorkspaceQuotaError("Cannot safely measure existing project workspace storage.")
        return total

    def _upload_reservation_bytes(self) -> int:
        """Bound extracted files plus all application-generated workspace files."""
        return self.max_extracted_bytes + RESERVATION_OVERHEAD_BYTES

    def _reserve_upload(self, root: Path, token: str) -> None:
        key = self._root_key(root)
        with self._state_lock:
            reservations = self._reservations.get(key, {})
            if len(reservations) >= self.max_concurrent_uploads:
                raise WorkspaceQuotaError("Project upload capacity is busy; retry later.")
            reserved = sum(reservations.values())
            committed = self._committed_workspace_bytes(root)
            new_reservation = self._upload_reservation_bytes()
            if committed + reserved + new_reservation > self.max_workspace_bytes:
                raise WorkspaceQuotaError("Project workspace storage capacity is exhausted.")
            self._reservations.setdefault(key, {})[token] = new_reservation

    def _release_reservation(self, root: Path, token: str) -> None:
        key = self._root_key(root)
        with self._state_lock:
            reservations = self._reservations.get(key)
            if reservations is not None:
                reservations.pop(token, None)
                if not reservations:
                    self._reservations.pop(key, None)

    def _validated_workspace_root(self) -> Path:
        if not isinstance(self.workspace_root, str) or not self.workspace_root.strip():
            raise ChangeGuardException(
                "Project uploads are not configured with a usable private workspace.",
                status_code=503,
            )
        try:
            return validate_project_path(self.workspace_root, self.approved_roots)
        except InvalidInputError:
            logger.exception("Configured project workspace is outside the approved roots or unavailable")
            raise InvalidInputError(
                "Configured project workspace is outside the approved roots or unavailable."
            ) from None
        except ChangeGuardException:
            logger.exception("Configured project workspace root is invalid")
            raise ChangeGuardException(
                "Project uploads are not configured with a usable private workspace.",
                status_code=503,
            ) from None

    def create_project(self, archive_file: BinaryIO) -> Dict[str, object]:
        """Validate and extract an uploaded ZIP, then atomically publish its workspace."""
        root = self._validated_workspace_root()
        self.cleanup_expired_workspaces()
        self._check_actual_upload_size(archive_file)

        project_id = secrets.token_hex(32)
        reservation = secrets.token_hex(16)
        self._reserve_upload(root, reservation)
        staging = root / f".staging-{secrets.token_hex(16)}"
        final_workspace = root / project_id
        project_dir = staging / "project"
        published = False
        completed = False
        staging_registered = False
        try:
            with self._state_lock:
                staging.mkdir(mode=0o700)
                self._active_staging.add((self._root_key(root), staging.name))
                staging_registered = True
            self._write_marker(staging / STAGING_MARKER, staging.name, kind="staging")
            project_dir.mkdir(mode=0o700)
            file_count = self._extract_zip(archive_file, project_dir)
            if file_count < 1 or not any(path.suffix.casefold() == ".py" for path in project_dir.rglob("*.py")):
                raise InvalidInputError("The ZIP archive must contain at least one Python source file.")

            extracted_bytes = sum(item.stat().st_size for item in project_dir.rglob("*") if item.is_file())

            expires_at = datetime.now(timezone.utc) + timedelta(hours=self.workspace_ttl_hours)
            metadata = {
                "project_id": project_id,
                "application": APP_MARKER,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": expires_at.isoformat(),
                "file_count": file_count,
                "extracted_bytes": extracted_bytes,
            }
            metadata_path = staging / "metadata.json"
            with metadata_path.open("x", encoding="utf-8") as output:
                json.dump(metadata, output, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            self._write_marker(staging / OWNERSHIP_MARKER, project_id, kind="workspace")

            # Validate before and after publication. Both locations are beneath
            # the same approved root, so os.replace is an atomic same-volume move.
            validate_project_path(str(project_dir), self.approved_roots)
            with self._state_lock:
                if final_workspace.exists():
                    raise ChangeGuardException("Unable to allocate a unique project workspace.", status_code=500)
                os.replace(staging, final_workspace)
                published = True
                (final_workspace / STAGING_MARKER).unlink(missing_ok=True)
                self._active_staging.discard((self._root_key(root), staging.name))
                staging_registered = False
                self._release_reservation(root, reservation)
            published_project = validate_project_path(str(final_workspace / "project"), self.approved_roots)
            if not self._is_within(published_project, root):
                raise InvalidInputError("Published project workspace is outside the configured root.")
            completed = True

            return {
                "project_id": project_id,
                "file_count": file_count,
                "expires_at": expires_at,
            }
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, OSError, EOFError, zlib.error) as exc:
            logger.warning("Project archive extraction failed", exc_info=True)
            raise InvalidInputError("The uploaded file is not a valid, safely extractable ZIP archive.") from exc
        finally:
            target = final_workspace if published else staging
            if not completed:
                try:
                    with self._state_lock:
                        is_owned_target = False
                        if published:
                            is_owned_target = self._valid_marker(
                                target / OWNERSHIP_MARKER, project_id, "workspace"
                            )
                        elif staging_registered:
                            marker_path = target / STAGING_MARKER
                            is_owned_target = (
                                not os.path.lexists(marker_path)
                                or self._valid_marker(marker_path, target.name, "staging")
                            )
                        if is_owned_target and target.exists() and not target.is_symlink():
                            target.resolve(strict=True).relative_to(root)
                            shutil.rmtree(target)
                        elif is_owned_target and target.is_symlink():
                            target.unlink()
                        elif target.exists():
                            logger.warning(
                                "Leaving incomplete workspace without a valid ownership marker untouched",
                                extra={"workspace_entry": target.name, "operation": "failed_upload_cleanup"},
                            )
                except FileNotFoundError:
                    pass
                except (OSError, ValueError):
                    logger.exception(
                        "Failed to remove incomplete project workspace",
                        extra={"workspace_entry": target.name, "operation": "failed_upload_cleanup"},
                    )
            if staging_registered:
                with self._state_lock:
                    self._active_staging.discard((self._root_key(root), staging.name))
            self._release_reservation(root, reservation)

    def resolve_project_id(self, project_id: str) -> Path:
        """Resolve a strictly validated opaque ID to its contained project directory."""
        return self._resolve_project(project_id)

    def _resolve_project(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not PROJECT_ID_PATTERN.fullmatch(project_id):
            raise InvalidInputError("Unknown or invalid project identifier.")
        root = self._validated_workspace_root()
        workspace = root / project_id
        if workspace.is_symlink():
            raise InvalidInputError("Unknown or invalid project identifier.")
        try:
            resolved_workspace = workspace.resolve(strict=True)
            resolved_workspace.relative_to(root)
            if not self._valid_marker(resolved_workspace / OWNERSHIP_MARKER, project_id, "workspace"):
                raise InvalidInputError("Unknown, incomplete, or invalid project identifier.")
            metadata = self._read_metadata(resolved_workspace, project_id)
            expires_at = datetime.fromisoformat(metadata["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise InvalidInputError("Project workspace has expired.")
            project_dir = validate_project_path(str(resolved_workspace / "project"), self.approved_roots)
            if not self._is_within(project_dir, root):
                raise InvalidInputError("Unknown or invalid project identifier.")
            return project_dir
        except InvalidInputError:
            raise
        except (OSError, ValueError, KeyError, json.JSONDecodeError, ChangeGuardException) as exc:
            raise InvalidInputError("Unknown, incomplete, or invalid project identifier.") from exc

    @contextmanager
    def lease_project_id(self, project_id: str) -> Iterator[Path]:
        """Lease a live workspace for the full duration of a workflow.

        Callers must use this context manager (not resolve_project_id) around
        every run so release happens on success, exception, and timeout.
        """
        root = self._validated_workspace_root()
        with self._state_lock:
            project_dir = self._resolve_project(project_id)
            key = (self._root_key(root), project_id)
            self._leases[key] = self._leases.get(key, 0) + 1
        try:
            yield project_dir
        finally:
            with self._state_lock:
                remaining = self._leases.get(key, 0) - 1
                if remaining > 0:
                    self._leases[key] = remaining
                else:
                    self._leases.pop(key, None)

    def cleanup_expired_workspaces(self, now: Optional[datetime] = None) -> int:
        """Remove only app-owned expired workspaces and stale app-owned staging trees."""
        if not isinstance(self.workspace_root, str) or not self.workspace_root.strip():
            return 0
        root = self._validated_workspace_root()
        current_time = now or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        removed = 0

        with self._state_lock:
            try:
                children = list(root.iterdir())
            except OSError as exc:
                raise ChangeGuardException("Cannot inspect the configured project workspace.", status_code=500) from exc

            for child in children:
                if child.is_symlink() or not child.is_dir():
                    continue
                try:
                    resolved_child = child.resolve(strict=True)
                    if resolved_child.parent != root:
                        continue
                    if STAGING_NAME_PATTERN.fullmatch(child.name):
                        if (self._root_key(root), child.name) in self._active_staging:
                            continue
                        if not self._valid_marker(resolved_child / STAGING_MARKER, child.name, "staging"):
                            logger.warning("Leaving unowned or invalid staging directory untouched: %s", child.name)
                            continue
                        age = current_time.timestamp() - child.stat().st_mtime
                        if age >= self.staging_ttl_hours * 3600:
                            try:
                                self._remove_workspace(resolved_child, root)
                                removed += 1
                            except OSError:
                                logger.exception(
                                    "Failed to clean stale staging directory",
                                    extra={"workspace_entry": child.name, "operation": "staging_cleanup"},
                                )
                        continue
                    if not PROJECT_ID_PATTERN.fullmatch(child.name):
                        continue
                    try:
                        if not self._valid_marker(resolved_child / OWNERSHIP_MARKER, child.name, "workspace"):
                            logger.warning("Leaving workspace without a valid ownership marker untouched: %s", child.name)
                            continue
                        metadata = self._read_metadata(resolved_child, child.name)
                        expires_at = datetime.fromisoformat(metadata["expires_at"])
                        if expires_at.tzinfo is None:
                            expires_at = expires_at.replace(tzinfo=timezone.utc)
                        expired = expires_at <= current_time
                    except (OSError, ValueError, KeyError, json.JSONDecodeError):
                        logger.warning("Leaving workspace with invalid metadata untouched: %s", child.name, exc_info=True)
                        continue
                    if expired:
                        lease_key = (self._root_key(root), child.name)
                        if self._leases.get(lease_key, 0):
                            continue
                        try:
                            self._remove_workspace(resolved_child, root)
                            removed += 1
                        except OSError:
                            logger.exception(
                                "Failed to clean expired workspace",
                                extra={"workspace_entry": child.name, "operation": "expired_workspace_cleanup"},
                            )
                except OSError:
                    logger.exception("Unable to inspect workspace entry %s", child.name)
        return removed

    def _check_actual_upload_size(self, archive_file: BinaryIO) -> None:
        total = 0
        try:
            archive_file.seek(0)
            while True:
                chunk = archive_file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_upload_bytes:
                    raise UploadTooLargeError(
                        f"ZIP upload exceeds the {self.max_upload_bytes}-byte limit."
                    )
            archive_file.seek(0)
        except InvalidInputError:
            raise
        except (OSError, ValueError) as exc:
            raise InvalidInputError("Unable to read the uploaded ZIP archive.") from exc

    def _preflight_zip_entry_count(self, archive_file: BinaryIO) -> List[bytes]:
        """Bound directory parsing and reject NULs in raw central/local names."""
        try:
            archive_file.seek(0, os.SEEK_END)
            archive_size = archive_file.tell()
            tail_size = min(archive_size, 22 + 65_535)
            archive_file.seek(archive_size - tail_size)
            tail = archive_file.read(tail_size)
            signature = b"PK\x05\x06"
            position = tail.rfind(signature)
            while position >= 0:
                if position + 22 <= len(tail):
                    comment_length = struct.unpack_from("<H", tail, position + 20)[0]
                    if position + 22 + comment_length == len(tail):
                        break
                position = tail.rfind(signature, 0, position)
            if position < 0:
                raise InvalidInputError("The uploaded file is not a valid, safely extractable ZIP archive.")

            disk_number, central_disk = struct.unpack_from("<HH", tail, position + 4)
            disk_entries, total_entries = struct.unpack_from("<HH", tail, position + 8)
            central_size, central_offset = struct.unpack_from("<II", tail, position + 12)
            if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
                raise InvalidInputError("Multi-volume ZIP archives are not supported.")
            if total_entries == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
                raise InvalidInputError("ZIP64 archives are not supported by the configured upload limits.")
            if total_entries > self.max_entries:
                raise InvalidInputError(f"ZIP archive exceeds the {self.max_entries}-entry limit.")
            if central_size > archive_size or central_offset > archive_size:
                raise InvalidInputError("The uploaded file has an invalid ZIP directory record.")
            absolute_eocd = archive_size - tail_size + position
            central_start = absolute_eocd - central_size
            if central_start < central_offset:
                raise InvalidInputError("The uploaded file has an invalid ZIP directory record.")
            archive_file.seek(central_start)
            central_data = archive_file.read(central_size)
            if len(central_data) != central_size:
                raise InvalidInputError("The uploaded file has a truncated ZIP directory.")
            names: List[bytes] = []
            cursor = 0
            for _ in range(total_entries):
                if cursor + 46 > len(central_data) or central_data[cursor:cursor + 4] != b"PK\x01\x02":
                    raise InvalidInputError("The uploaded file has a malformed ZIP directory.")
                name_length, extra_length, comment_length = struct.unpack_from("<HHH", central_data, cursor + 28)
                end = cursor + 46 + name_length + extra_length + comment_length
                if end > len(central_data):
                    raise InvalidInputError("The uploaded file has a truncated ZIP directory entry.")
                raw_name = central_data[cursor + 46:cursor + 46 + name_length]
                if b"\x00" in raw_name:
                    raise InvalidInputError("ZIP archive contains a NUL byte in a raw entry path.")
                names.append(raw_name)
                cursor = end
            if cursor != len(central_data):
                raise InvalidInputError("The uploaded file has an invalid ZIP directory length.")
            archive_file.seek(0)
            return names
        except InvalidInputError:
            raise
        except (OSError, ValueError, struct.error) as exc:
            raise InvalidInputError("Unable to inspect the uploaded ZIP directory.") from exc

    def _extract_zip(self, archive_file: BinaryIO, project_dir: Path) -> int:
        try:
            raw_names = self._preflight_zip_entry_count(archive_file)
            with zipfile.ZipFile(archive_file) as archive:
                infos = archive.infolist()
                if not infos:
                    raise InvalidInputError("The ZIP archive is empty.")
                if len(infos) > self.max_entries:
                    raise InvalidInputError(f"ZIP archive exceeds the {self.max_entries}-entry limit.")
                if len(infos) != len(raw_names):
                    raise InvalidInputError("ZIP directory entries do not match the archive index.")
                self._validate_local_names(archive, infos, raw_names)
                validated = self._validate_entries(infos)
                archived_files = sum(not is_dir for _, _, is_dir in validated)
                if archived_files > self.max_files:
                    raise InvalidInputError(f"ZIP archive exceeds the {self.max_files}-file limit.")
                claimed_total = sum(info.file_size for info, _, is_dir in validated if not is_dir)
                if claimed_total > self.max_extracted_bytes:
                    raise UploadTooLargeError(
                        f"ZIP archive exceeds the {self.max_extracted_bytes}-byte extracted-size limit."
                    )

                actual_total = 0
                file_count = 0
                for info, safe_parts, is_dir in validated:
                    target = project_dir.joinpath(*safe_parts)
                    if is_dir:
                        self._ensure_safe_directory(project_dir, safe_parts)
                        continue

                    per_file_total = 0
                    with archive.open(info, "r") as source, self._open_safe_output(project_dir, safe_parts) as destination:
                        while True:
                            chunk = source.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            per_file_total += len(chunk)
                            actual_total += len(chunk)
                            if per_file_total > self.max_file_bytes:
                                raise UploadTooLargeError(
                                    f"ZIP file exceeds the {self.max_file_bytes}-byte per-file limit."
                                )
                            if actual_total > self.max_extracted_bytes:
                                raise UploadTooLargeError(
                                    f"ZIP archive exceeds the {self.max_extracted_bytes}-byte extracted-size limit."
                                )
                            destination.write(chunk)
                    if per_file_total != info.file_size:
                        raise InvalidInputError("ZIP entry size does not match its archive metadata.")
                    file_count += 1
                return file_count
        except InvalidInputError:
            raise
        except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
            logger.warning("Malformed or corrupted project ZIP entry", exc_info=True)
            raise InvalidInputError("The uploaded file is not a valid, safely extractable ZIP archive.") from exc

    @staticmethod
    def _validate_local_names(archive: zipfile.ZipFile, infos: List[zipfile.ZipInfo], raw_names: List[bytes]) -> None:
        for info, central_name in zip(infos, raw_names):
            archive.fp.seek(info.header_offset)
            header = archive.fp.read(30)
            if len(header) != 30 or header[:4] != b"PK\x03\x04":
                raise InvalidInputError("ZIP archive contains an invalid local file header.")
            name_length, extra_length = struct.unpack_from("<HH", header, 26)
            local_name = archive.fp.read(name_length)
            if len(local_name) != name_length or b"\x00" in local_name:
                raise InvalidInputError("ZIP archive contains a NUL or truncated local entry path.")
            if local_name != central_name:
                raise InvalidInputError("ZIP local and central entry names do not match.")
            if len(archive.fp.read(extra_length)) != extra_length:
                raise InvalidInputError("ZIP archive contains a truncated local file header.")

    @staticmethod
    def _supports_dir_fd() -> bool:
        return (
            os.name == "posix"
            and hasattr(os, "O_NOFOLLOW")
            and hasattr(os, "O_DIRECTORY")
            and os.open in os.supports_dir_fd
            and os.mkdir in os.supports_dir_fd
        )

    @classmethod
    def _ensure_safe_directory(cls, project_dir: Path, parts: Tuple[str, ...]) -> None:
        if cls._supports_dir_fd():
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(project_dir, flags)
            try:
                for part in parts:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = next_descriptor
            finally:
                os.close(descriptor)
            return

        # Windows fallback: private ACLs on the workspace root are required.
        current = project_dir
        for part in parts:
            current = current / part
            if current.is_symlink() or bool(getattr(os.path, "isjunction", lambda _: False)(current)):
                raise InvalidInputError("ZIP entry path contains a directory link.")
            current.mkdir(mode=0o700, exist_ok=True)
            if not ProjectWorkspaceService._is_within(current.resolve(), project_dir.resolve()):
                raise InvalidInputError("ZIP entry resolves outside its project workspace.")

    @classmethod
    @contextmanager
    def _open_safe_output(cls, project_dir: Path, parts: Tuple[str, ...]) -> Iterator[BinaryIO]:
        if cls._supports_dir_fd():
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(project_dir, flags)
            output_descriptor = None
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = next_descriptor
                output_descriptor = os.open(
                    parts[-1],
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=descriptor,
                )
                with os.fdopen(output_descriptor, "wb") as output:
                    output_descriptor = None
                    yield output
            finally:
                if output_descriptor is not None:
                    os.close(output_descriptor)
                os.close(descriptor)
            return

        # Windows lacks portable openat/O_NOFOLLOW support; ACL isolation is
        # the primary boundary and this check narrows, but cannot remove, races.
        parent = project_dir
        for part in parts[:-1]:
            parent = parent / part
            if parent.is_symlink() or bool(getattr(os.path, "isjunction", lambda _: False)(parent)):
                raise InvalidInputError("ZIP entry path contains a directory link.")
            parent.mkdir(mode=0o700, exist_ok=True)
            if not cls._is_within(parent.resolve(), project_dir.resolve()):
                raise InvalidInputError("ZIP entry resolves outside its project workspace.")
        destination = parent / parts[-1]
        if destination.is_symlink() or bool(getattr(os.path, "isjunction", lambda _: False)(destination)):
            raise InvalidInputError("ZIP entry path contains a file link.")
        with destination.open("xb") as output:
            yield output

    def _validate_entries(
        self, infos: List[zipfile.ZipInfo]
    ) -> List[Tuple[zipfile.ZipInfo, Tuple[str, ...], bool]]:
        validated: List[Tuple[zipfile.ZipInfo, Tuple[str, ...], bool]] = []
        kinds: Dict[str, bool] = {}
        for info in infos:
            raw_name = info.filename
            if not raw_name or "\x00" in raw_name or "\\" in raw_name:
                raise InvalidInputError("ZIP archive contains an unsafe entry path.")
            if info.flag_bits & 0x1:
                raise InvalidInputError("Encrypted ZIP entries are not supported.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise InvalidInputError("ZIP archive uses an unsupported compression method.")
            if raw_name.startswith("/") or PureWindowsPath(raw_name).is_absolute() or PureWindowsPath(raw_name).drive:
                raise InvalidInputError("ZIP archive contains an absolute or drive-qualified path.")

            is_dir = info.is_dir()
            stripped_name = raw_name[:-1] if is_dir and raw_name.endswith("/") else raw_name
            raw_parts = stripped_name.split("/")
            parts = tuple(unicodedata.normalize("NFC", part) for part in raw_parts)
            if not parts or any(part in {"", ".", ".."} for part in parts):
                raise InvalidInputError("ZIP archive contains a traversal or empty path component.")
            for part in parts:
                device_name = part.split(".", 1)[0].rstrip(" .").upper()
                if (
                    ":" in part
                    or part.endswith((".", " "))
                    or device_name in WINDOWS_RESERVED_NAMES
                ):
                    raise InvalidInputError("ZIP archive contains a platform-unsafe path component.")
            if len(parts) > self.max_depth:
                raise InvalidInputError(f"ZIP archive exceeds the {self.max_depth}-level nesting limit.")

            mode = (info.external_attr >> 16) & 0xFFFF
            file_type = stat.S_IFMT(mode)
            if file_type == stat.S_IFLNK:
                raise InvalidInputError("ZIP archive symlinks are not supported.")
            allowed_types = {0, stat.S_IFREG, stat.S_IFDIR}
            if file_type not in allowed_types:
                raise InvalidInputError("ZIP archive contains a special file entry.")
            if is_dir and file_type == stat.S_IFREG or not is_dir and file_type == stat.S_IFDIR:
                raise InvalidInputError("ZIP archive entry type does not match its filename.")
            if is_dir and info.file_size != 0:
                raise InvalidInputError("ZIP directory entries must not contain file data.")
            if not is_dir and info.file_size > self.max_file_bytes:
                raise UploadTooLargeError(f"ZIP file exceeds the {self.max_file_bytes}-byte per-file limit.")

            key = "/".join(parts).casefold()
            if key in kinds:
                raise InvalidInputError("ZIP archive contains duplicate normalized paths.")
            for index in range(1, len(parts)):
                parent_key = "/".join(parts[:index]).casefold()
                if kinds.get(parent_key) is False:
                    raise InvalidInputError("ZIP archive has a file used as a parent directory.")
            if not is_dir and any(existing.startswith(key + "/") for existing in kinds):
                raise InvalidInputError("ZIP archive has a file/directory path collision.")
            kinds[key] = is_dir
            validated.append((info, parts, is_dir))
        return validated

    @staticmethod
    def _write_marker(path: Path, project_id: str, *, kind: str) -> None:
        with path.open("x", encoding="utf-8") as output:
            json.dump(
                {"application": APP_MARKER, "project_id": project_id, "kind": kind},
                output,
                separators=(",", ":"),
            )
            output.flush()
            os.fsync(output.fileno())

    @staticmethod
    def _valid_marker(path: Path, expected_id: str, expected_kind: str) -> bool:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
                return False
            with path.open("r", encoding="utf-8") as source:
                marker = json.load(source)
            return (
                isinstance(marker, dict)
                and marker.get("application") == APP_MARKER
                and marker.get("project_id") == expected_id
                and marker.get("kind") == expected_kind
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @staticmethod
    def _read_metadata(workspace: Path, expected_project_id: str) -> Dict[str, object]:
        metadata_path = workspace / "metadata.json"
        if metadata_path.is_symlink() or not metadata_path.is_file() or metadata_path.stat().st_size > 16_384:
            raise ValueError("Workspace metadata is missing.")
        with metadata_path.open("r", encoding="utf-8") as source:
            metadata = json.load(source)
        if (
            not isinstance(metadata, dict)
            or metadata.get("project_id") != expected_project_id
            or metadata.get("application") != APP_MARKER
            or not isinstance(metadata.get("extracted_bytes"), int)
            or metadata["extracted_bytes"] < 0
        ):
            raise ValueError("Workspace metadata does not match the project identifier.")
        if not isinstance(metadata.get("expires_at"), str):
            raise ValueError("Workspace expiration metadata is invalid.")
        return metadata

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @classmethod
    def _remove_workspace(cls, workspace: Path, root: Path) -> None:
        if workspace.is_symlink():
            return
        resolved = workspace.resolve(strict=True)
        if resolved.parent != root or not cls._is_within(resolved, root):
            return
        key = cls._root_key(root)
        if PROJECT_ID_PATTERN.fullmatch(resolved.name) and cls._leases.get((key, resolved.name), 0):
            return
        if STAGING_NAME_PATTERN.fullmatch(resolved.name) and (key, resolved.name) in cls._active_staging:
            return
        shutil.rmtree(resolved)
