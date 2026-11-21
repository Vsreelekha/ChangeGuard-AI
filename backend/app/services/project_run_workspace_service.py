"""Create isolated, temporary copies of uploaded projects for workflow runs."""

import json
import os
import shutil
import stat
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple, Union

from app.core.config import get_settings
from app.core.exceptions import ChangeGuardException, InvalidInputError
from app.core.logging_config import logger


PathInput = Union[str, os.PathLike[str]]
RUN_DIRECTORY_PREFIX = ".changeguard-run-"
OWNER_MARKER = ".changeguard-run-owner.json"
PROJECT_DIRECTORY = "project"
REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
COPY_CHUNK_SIZE = 64 * 1024


class ProjectRunWorkspaceService:
    """Make one disposable working copy per workflow execution.

    Security & Deployment Assumptions:
    - POSIX Permissions vs. Windows DACLs:
      On POSIX systems, `chmod(0o700)` on directories and `chmod(0o600)` on files enforces private,
      single-user ownership. On Windows NTFS filesystems, `os.chmod` only controls the read-only attribute
      and does not configure or enforce Discretionary Access Control Lists (DACLs).
    - Deployment Precondition:
      The configured `PROJECT_WORKSPACE_ROOT` must be explicitly provisioned in the host operating system
      with a restrictive Windows DACL that limits access strictly to SYSTEM, Administrators, and the
      application service account. Temporary run workspaces inherit this parent DACL upon creation.
    - Windows TOCTOU Residual Limitations:
      Python on Windows does not provide atomic, race-free `openat(2)` or `O_NOFOLLOW` semantics across
      arbitrary recursive directory operations. While handle-based copying, exclusive destination creation
      (`O_CREAT | O_EXCL`), pre/post-stat comparisons, and ancestor reparse-point revalidations narrow
      exploitation windows and detect tampering, ordinary user-space path checks cannot guarantee complete
      race immunity against a local adversary who possesses write privileges inside the workspace root.
    """

    def __init__(self, workspace_root: Optional[PathInput] = None) -> None:
        configured_root = workspace_root if workspace_root is not None else get_settings().PROJECT_WORKSPACE_ROOT
        self.workspace_root = Path(configured_root) if configured_root else None

    @contextmanager
    def create_run_workspace(self, source_project_path: PathInput) -> Iterator[Path]:
        """Yield a copied project tree and remove its unique run directory on exit.

        The source must be an existing project directory beneath ``PROJECT_WORKSPACE_ROOT``.
        Each invocation gets an exclusively created, uniquely identified run directory.
        Preserves original creation/workflow exceptions (including BaseExceptions such as
        KeyboardInterrupt and SystemExit) if cleanup also fails; propagates cleanup failures
        when no prior exception occurred.
        """
        workspace_root = self._resolve_workspace_root()
        source_root = self._resolve_source_project(source_project_path, workspace_root)
        run_directory: Optional[Path] = None
        run_dir_identity: Optional[Tuple[int, int]] = None
        owner_token = uuid.uuid4().hex
        marker_written = False
        primary_exc: Optional[BaseException] = None

        try:
            try:
                run_directory = Path(
                    tempfile.mkdtemp(prefix=RUN_DIRECTORY_PREFIX, dir=str(workspace_root))
                )
                run_directory = self._verify_run_directory(run_directory, workspace_root)
                self._apply_restrictive_permissions(run_directory)
                run_stat = run_directory.lstat()
                run_dir_identity = (run_stat.st_dev, run_stat.st_ino)

                self._write_owner_marker(run_directory, owner_token)
                marker_written = True

                copied_project = run_directory / PROJECT_DIRECTORY
                copied_project.mkdir(mode=0o700)
                self._apply_restrictive_permissions(copied_project)

                source_snapshot = self._verify_source_tree(source_root, source_root)
                self._copy_directory_contents(
                    source_root, copied_project, source_root, run_directory, source_snapshot
                )
                self._verify_copy_tree(copied_project, run_directory, run_dir_identity)
            except (ChangeGuardException, InvalidInputError) as exc:
                primary_exc = exc
                raise
            except (KeyboardInterrupt, SystemExit) as exc:
                primary_exc = exc
                raise
            except Exception as exc:
                wrapped = ChangeGuardException(
                    "Unable to create an isolated project workspace for this run.",
                    status_code=500,
                )
                wrapped.__cause__ = exc
                primary_exc = wrapped
                raise wrapped from exc
            except BaseException as exc:
                primary_exc = exc
                raise

            try:
                yield copied_project
            except BaseException as exc:
                primary_exc = exc
                raise
        finally:
            if run_directory is not None:
                try:
                    self._cleanup_run_directory(
                        run_directory,
                        workspace_root,
                        owner_token,
                        expected_identity=run_dir_identity,
                        marker_written=marker_written,
                        source_root=source_root,
                    )
                except Exception as cleanup_exc:
                    logger.error(
                        "Failed to clean up run workspace directory %s: %s",
                        run_directory,
                        cleanup_exc,
                        exc_info=True,
                    )
                    if primary_exc is None:
                        raise

    def _resolve_workspace_root(self) -> Path:
        """Resolve PROJECT_WORKSPACE_ROOT after validating it and all ancestors for links/reparse points."""
        configured_root = self.workspace_root
        if configured_root is None:
            raise ChangeGuardException(
                "PROJECT_WORKSPACE_ROOT must be configured before running an uploaded project.",
                status_code=500,
            )
        try:
            candidate = Path(configured_root)

            # Inspect candidate and each existing ancestor component BEFORE resolving
            curr: Optional[Path] = candidate
            while curr is not None:
                if self._is_link_or_junction(curr):
                    raise InvalidInputError("The configured project workspace root cannot be a link or contain links.")
                if curr == curr.parent:
                    break
                curr = curr.parent

            cand_stat = candidate.lstat()
            if not stat.S_ISDIR(cand_stat.st_mode):
                raise ChangeGuardException(
                    "The configured project workspace root is not a directory.", status_code=500
                )

            root = candidate.resolve(strict=True)

            # Revalidate resolved root and each ancestor
            curr_resolved: Optional[Path] = root
            while curr_resolved is not None:
                if self._is_link_or_junction(curr_resolved):
                    raise InvalidInputError("The configured project workspace root cannot be a link.")
                if curr_resolved == curr_resolved.parent:
                    break
                curr_resolved = curr_resolved.parent

        except InvalidInputError:
            raise
        except (OSError, RuntimeError) as exc:
            raise ChangeGuardException(
                "The configured project workspace root is unavailable.", status_code=500
            ) from exc

        if not root.is_dir():
            raise ChangeGuardException(
                "The configured project workspace root is not a directory.", status_code=500
            )
        return root

    def _resolve_source_project(self, source_path: PathInput, workspace_root: Path) -> Path:
        """Validate source directory without resolving away evidence of symlinks in ancestors."""
        try:
            candidate = Path(source_path)
            if not candidate.is_absolute():
                candidate = workspace_root / candidate

            canonical_workspace_root = workspace_root.resolve(strict=True)

            # Inspect candidate and each existing ancestor BEFORE resolving away symlinks
            curr: Optional[Path] = candidate
            while curr is not None:
                if self._is_link_or_junction(curr):
                    raise InvalidInputError(
                        "Uploaded project workspaces cannot contain symlinks or junctions."
                    )
                if curr == curr.parent:
                    break
                curr = curr.parent

            cand_stat = candidate.lstat()
            if not stat.S_ISDIR(cand_stat.st_mode):
                raise InvalidInputError(
                    "The uploaded project must be a directory below PROJECT_WORKSPACE_ROOT."
                )

            resolved = candidate.resolve(strict=True)
            resolved.relative_to(canonical_workspace_root)
            if resolved == canonical_workspace_root or not resolved.is_dir():
                raise InvalidInputError(
                    "The uploaded project must be a directory below PROJECT_WORKSPACE_ROOT."
                )

            # Revalidate all resolved path components down to workspace root
            curr_resolved = resolved
            while curr_resolved != canonical_workspace_root:
                if self._is_link_or_junction(curr_resolved):
                    raise InvalidInputError(
                        "Uploaded project workspaces cannot contain symlinks or junctions."
                    )
                curr_resolved = curr_resolved.parent

        except InvalidInputError:
            raise
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            raise InvalidInputError(
                "The uploaded project must be an existing directory inside PROJECT_WORKSPACE_ROOT."
            ) from exc

        self._verify_source_tree(resolved, resolved)
        return resolved

    @staticmethod
    def _is_link_or_junction(path: Path, entry: Optional[os.DirEntry] = None) -> bool:
        try:
            if entry is not None and entry.is_symlink():
                return True
            if path.is_symlink() or bool(getattr(os.path, "isjunction", lambda _: False)(path)):
                return True
            metadata = entry.stat(follow_symlinks=False) if entry is not None else path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                return True
            return bool(getattr(metadata, "st_file_attributes", 0) & REPARSE_POINT_ATTRIBUTE)
        except FileNotFoundError:
            return False
        except OSError:
            return True

    @staticmethod
    def _write_all(fd: int, data: Union[bytes, bytearray, memoryview]) -> int:
        """Write all bytes to a file descriptor using a memoryview loop.

        Continues until every byte is written. Treats 0 or negative write returns as an OSError.
        """
        view = memoryview(data)
        total_written = 0
        total_bytes = len(view)
        while total_written < total_bytes:
            written = os.write(fd, view[total_written:])
            if written <= 0:
                raise OSError(f"os.write returned {written} bytes before writing the full buffer")
            total_written += written
        return total_written

    @classmethod
    def _verify_source_tree(cls, directory: Path, source_root: Path) -> Dict[Path, Tuple]:
        """Reject links and special files before copying and snapshot source identities."""
        try:
            snapshot: Dict[Path, Tuple] = {}
            cls._scan_and_snapshot(directory, source_root, snapshot)
            return snapshot
        except InvalidInputError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise InvalidInputError(
                "Uploaded project contents must remain inside the source workspace."
            ) from exc

    @classmethod
    def _scan_and_snapshot(
        cls, directory: Path, source_root: Path, snapshot: Dict[Path, Tuple]
    ) -> None:
        if cls._is_link_or_junction(directory):
            raise InvalidInputError("Uploaded project workspaces cannot contain symlinks or junctions.")
        resolved_dir = directory.resolve(strict=True)
        resolved_dir.relative_to(source_root)
        dir_stat = directory.lstat()
        snapshot[directory.relative_to(source_root)] = (
            "dir",
            dir_stat.st_dev,
            dir_stat.st_ino,
        )

        with os.scandir(directory) as entries:
            for entry in entries:
                child = Path(entry.path)
                if cls._is_link_or_junction(child, entry):
                    raise InvalidInputError(
                        "Uploaded project workspaces cannot contain symlinks or junctions."
                    )
                # Use Path.lstat() consistently for device/inode identity retrieval without following symlinks
                child_stat = child.lstat()
                rel_child = child.relative_to(source_root)
                if stat.S_ISDIR(child_stat.st_mode):
                    cls._scan_and_snapshot(child, source_root, snapshot)
                elif stat.S_ISREG(child_stat.st_mode):
                    resolved_file = child.resolve(strict=True)
                    resolved_file.relative_to(source_root)
                    snapshot[rel_child] = (
                        "file",
                        child_stat.st_dev,
                        child_stat.st_ino,
                        child_stat.st_mtime_ns,
                        child_stat.st_size,
                    )
                else:
                    raise InvalidInputError(
                        "Uploaded project workspaces cannot contain special files."
                    )

    @classmethod
    def _copy_directory_contents(
        cls,
        source: Path,
        destination: Path,
        source_root: Path,
        destination_root: Optional[Path] = None,
        snapshot: Optional[Dict[Path, Tuple]] = None,
    ) -> None:
        """Copy regular files and directories, never following source links."""
        if destination_root is None:
            destination_root = destination.parent

        try:
            if cls._is_link_or_junction(source):
                raise InvalidInputError(
                    "Uploaded project workspaces cannot contain symlinks or junctions."
                )
            if cls._is_link_or_junction(destination):
                raise ChangeGuardException(
                    "The isolated project copy contains an unsafe link.", status_code=500
                )

            source_stat = source.lstat()
            if not stat.S_ISDIR(source_stat.st_mode):
                raise InvalidInputError("Uploaded project workspaces cannot contain special files.")

            if snapshot is not None:
                rel_source = source.relative_to(source_root)
                expected_dir = snapshot.get(rel_source)
                if expected_dir is None:
                    raise ChangeGuardException(
                        "Source directory identity changed during copying.", status_code=500
                    )
                if expected_dir[2] != 0:
                    if (source_stat.st_dev, source_stat.st_ino) != (expected_dir[1], expected_dir[2]):
                        raise ChangeGuardException(
                            "Source directory identity changed during copying.", status_code=500
                        )

            resolved_source = source.resolve(strict=True)
            resolved_source.relative_to(source_root)

            resolved_dest = destination.resolve(strict=True)
            resolved_dest.relative_to(destination_root)

            with os.scandir(source) as entries:
                for entry in entries:
                    source_entry = Path(entry.path)
                    destination_entry = destination / entry.name
                    rel_entry = source_entry.relative_to(source_root)

                    if cls._is_link_or_junction(source_entry, entry):
                        raise InvalidInputError(
                            "Uploaded project workspaces cannot contain symlinks or junctions."
                        )

                    if snapshot is not None and rel_entry not in snapshot:
                        raise ChangeGuardException(
                            "Source workspace was modified during copying.", status_code=500
                        )

                    # Retrieve metadata via Path.lstat() to ensure consistent dev/inode identity
                    source_entry_stat = source_entry.lstat()
                    if stat.S_ISDIR(source_entry_stat.st_mode):
                        if snapshot is not None:
                            expected_entry = snapshot[rel_entry]
                            if expected_entry[0] != "dir":
                                raise ChangeGuardException(
                                    "Source entry type changed during copying.", status_code=500
                                )
                            if expected_entry[2] != 0 and (
                                source_entry_stat.st_dev,
                                source_entry_stat.st_ino,
                            ) != (
                                expected_entry[1],
                                expected_entry[2],
                            ):
                                raise ChangeGuardException(
                                    "Source directory identity changed during copying.", status_code=500
                                )

                        resolved_directory = source_entry.resolve(strict=True)
                        resolved_directory.relative_to(source_root)

                        destination_entry.mkdir(mode=0o700)
                        cls._apply_restrictive_permissions(destination_entry)
                        if cls._is_link_or_junction(destination_entry):
                            raise ChangeGuardException(
                                "The isolated project copy contains an unsafe link.", status_code=500
                            )

                        cls._copy_directory_contents(
                            source_entry, destination_entry, source_root, destination_root, snapshot
                        )
                    elif stat.S_ISREG(source_entry_stat.st_mode):
                        if snapshot is not None:
                            expected_entry = snapshot[rel_entry]
                            if expected_entry[0] != "file":
                                raise ChangeGuardException(
                                    "Source entry type changed during copying.", status_code=500
                                )
                            if expected_entry[2] != 0 and (
                                source_entry_stat.st_dev,
                                source_entry_stat.st_ino,
                            ) != (
                                expected_entry[1],
                                expected_entry[2],
                            ):
                                raise ChangeGuardException(
                                    "Source file identity changed during copying.", status_code=500
                                )
                            if (
                                source_entry_stat.st_mtime_ns != expected_entry[3]
                                or source_entry_stat.st_size != expected_entry[4]
                            ):
                                raise ChangeGuardException(
                                    "Source file was modified during copying.", status_code=500
                                )

                        resolved_file = source_entry.resolve(strict=True)
                        resolved_file.relative_to(source_root)

                        cls._copy_file(source_entry, destination_entry, destination_root, source_entry_stat)
                    else:
                        raise InvalidInputError(
                            "Uploaded project workspaces cannot contain special files."
                        )
        except (InvalidInputError, ChangeGuardException):
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise ChangeGuardException(
                "Unable to copy the uploaded project into an isolated run workspace.",
                status_code=500,
            ) from exc

    @classmethod
    def _copy_file(
        cls,
        source_entry: Path,
        destination_entry: Path,
        destination_root: Path,
        expected_stat: os.stat_result,
    ) -> None:
        """Copy file content directly from verified open source handle to exclusive destination handle."""
        if cls._is_link_or_junction(source_entry):
            raise InvalidInputError("Uploaded project workspaces cannot contain symlinks or junctions.")
        if cls._is_link_or_junction(destination_entry):
            raise ChangeGuardException("Destination file cannot be a link.", status_code=500)

        src_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            src_flags |= os.O_NOFOLLOW

        dst_flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
        )
        if hasattr(os, "O_NOFOLLOW"):
            dst_flags |= os.O_NOFOLLOW

        src_fd = -1
        dst_fd = -1
        copy_exc: Optional[BaseException] = None
        cleanup_error: Optional[Exception] = None

        try:
            try:
                src_fd = os.open(source_entry, src_flags)
            except OSError as exc:
                if isinstance(exc, (ChangeGuardException, InvalidInputError)):
                    raise
                raise ChangeGuardException(
                    f"Unable to open source file for copying: {source_entry}", status_code=500
                ) from exc

            # Verify source handle identity and type
            fstat_init = os.fstat(src_fd)
            if not stat.S_ISREG(fstat_init.st_mode):
                raise InvalidInputError("Uploaded project workspaces cannot contain special files.")

            if cls._is_link_or_junction(source_entry):
                raise InvalidInputError("Uploaded project workspaces cannot contain symlinks or junctions.")

            if expected_stat.st_ino != 0 and (fstat_init.st_dev, fstat_init.st_ino) != (
                expected_stat.st_dev,
                expected_stat.st_ino,
            ):
                raise ChangeGuardException(
                    "Source file identity changed during copying.", status_code=500
                )
            if (
                fstat_init.st_mtime_ns != expected_stat.st_mtime_ns
                or fstat_init.st_size != expected_stat.st_size
            ):
                raise ChangeGuardException(
                    "Source file was modified during copying.", status_code=500
                )

            # Create destination file exclusively
            try:
                dst_fd = os.open(destination_entry, dst_flags, 0o600)
            except FileExistsError as exc:
                raise ChangeGuardException(
                    f"Destination file already exists and cannot be safely overwritten: {destination_entry}",
                    status_code=500,
                ) from exc
            except OSError as exc:
                raise ChangeGuardException(
                    f"Unable to create destination file: {destination_entry}", status_code=500
                ) from exc

            # Copy content from verified source handle to destination handle using memoryview complete writes
            bytes_copied = 0
            while True:
                chunk = os.read(src_fd, COPY_CHUNK_SIZE)
                if not chunk:
                    break
                cls._write_all(dst_fd, chunk)
                bytes_copied += len(chunk)

            if bytes_copied != expected_stat.st_size:
                raise ChangeGuardException(
                    f"Source file size mismatch during copy: expected {expected_stat.st_size}, copied {bytes_copied}",
                    status_code=500,
                )

            # Post-copy revalidation of source handle
            fstat_post = os.fstat(src_fd)
            if (
                fstat_post.st_size != fstat_init.st_size
                or fstat_post.st_mtime_ns != fstat_init.st_mtime_ns
            ):
                raise ChangeGuardException(
                    "Source file was modified while copying.", status_code=500
                )
            if expected_stat.st_ino != 0 and (fstat_post.st_dev, fstat_post.st_ino) != (
                fstat_init.st_dev,
                fstat_init.st_ino,
            ):
                raise ChangeGuardException(
                    "Source file identity changed during copying.", status_code=500
                )

            if cls._is_link_or_junction(source_entry):
                raise InvalidInputError("Uploaded project workspaces cannot contain symlinks or junctions.")

            # Validate destination handle
            dst_fstat = os.fstat(dst_fd)
            if not stat.S_ISREG(dst_fstat.st_mode) or dst_fstat.st_size != bytes_copied:
                raise ChangeGuardException(
                    "Destination file verification failed after copy.", status_code=500
                )

            os.fsync(dst_fd)

            # Preserve timestamps only when descriptor-based os.utime is safely supported;
            # avoid pathname-based fallback.
            if hasattr(os, "utime") and os.utime in getattr(os, "supports_fd", set()):
                try:
                    os.utime(dst_fd, ns=(fstat_init.st_atime_ns, fstat_init.st_mtime_ns))
                except OSError as exc:
                    logger.debug("Could not preserve descriptor timestamp for %s: %s", destination_entry, exc)

            # Close handles while still in try block
            try:
                os.close(dst_fd)
            except OSError as exc:
                logger.error("Failed to close destination file descriptor %s: %s", destination_entry, exc)
                cleanup_error = exc
            dst_fd = -1

            try:
                os.close(src_fd)
            except OSError as exc:
                logger.error("Failed to close source file descriptor %s: %s", source_entry, exc)
                if cleanup_error is None:
                    cleanup_error = exc
            src_fd = -1

            if cleanup_error is not None:
                raise ChangeGuardException(
                    f"Failed to finalize file copying for {destination_entry.name}",
                    status_code=500,
                ) from cleanup_error

            if cls._is_link_or_junction(destination_entry):
                raise ChangeGuardException("Destination file cannot be a link.", status_code=500)

            resolved_dest = destination_entry.resolve(strict=True)
            resolved_dest.relative_to(destination_root)
            cls._apply_restrictive_permissions(destination_entry)

        except BaseException as exc:
            copy_exc = exc
            raise
        finally:
            if src_fd != -1:
                try:
                    os.close(src_fd)
                except OSError as exc:
                    logger.error("Failed to close source file descriptor %s: %s", source_entry, exc)
                    if copy_exc is None and cleanup_error is None:
                        cleanup_error = exc
            if dst_fd != -1:
                try:
                    os.close(dst_fd)
                except OSError as exc:
                    logger.error("Failed to close destination file descriptor %s: %s", destination_entry, exc)
                    if copy_exc is None and cleanup_error is None:
                        cleanup_error = exc
            if copy_exc is not None:
                try:
                    if destination_entry.exists() or destination_entry.is_symlink():
                        destination_entry.unlink()
                except OSError as exc:
                    logger.error("Failed to unlink partial destination file %s: %s", destination_entry, exc)
            elif cleanup_error is not None:
                raise ChangeGuardException(
                    f"Failed to finalize file copying for {destination_entry.name}",
                    status_code=500,
                ) from cleanup_error

    @classmethod
    def _verify_copy_tree(
        cls,
        directory: Path,
        destination_root: Optional[Path] = None,
        expected_root_identity: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Ensure the completed copy contains no links or special files, and destination wasn't replaced."""
        if destination_root is None:
            destination_root = directory.parent

        try:
            if cls._is_link_or_junction(destination_root):
                raise ChangeGuardException(
                    "The run workspace contains an unsafe link.", status_code=500
                )
            root_stat = destination_root.lstat()
            if expected_root_identity is not None and expected_root_identity[1] != 0:
                if (root_stat.st_dev, root_stat.st_ino) != expected_root_identity:
                    raise ChangeGuardException(
                        "Run workspace identity changed during copy.", status_code=500
                    )

            resolved_root = destination_root.resolve(strict=True)

            with os.scandir(directory) as entries:
                for entry in entries:
                    child = Path(entry.path)
                    if cls._is_link_or_junction(child, entry):
                        raise ChangeGuardException(
                            "The isolated project copy contains an unsafe link.", status_code=500
                        )
                    metadata = entry.stat(follow_symlinks=False)
                    resolved_child = child.resolve(strict=True)
                    resolved_child.relative_to(resolved_root)
                    if stat.S_ISDIR(metadata.st_mode):
                        cls._verify_copy_tree(child, destination_root, expected_root_identity)
                    elif not stat.S_ISREG(metadata.st_mode):
                        raise ChangeGuardException(
                            "The isolated project copy contains an unsupported file.", status_code=500
                        )
        except ChangeGuardException:
            raise
        except (OSError, RuntimeError) as exc:
            raise ChangeGuardException(
                "Unable to verify the isolated project copy.", status_code=500
            ) from exc

    @staticmethod
    def _verify_run_directory(run_directory: Path, workspace_root: Path) -> Path:
        try:
            if ProjectRunWorkspaceService._is_link_or_junction(run_directory):
                raise InvalidInputError("The run workspace path cannot be a link.")
            resolved = run_directory.resolve(strict=True)
            if resolved.parent != workspace_root or not resolved.name.startswith(RUN_DIRECTORY_PREFIX):
                raise InvalidInputError("The run workspace is outside PROJECT_WORKSPACE_ROOT.")
            if ProjectRunWorkspaceService._is_link_or_junction(resolved):
                raise InvalidInputError("The run workspace path cannot be a link.")
            return resolved
        except InvalidInputError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise InvalidInputError("The run workspace could not be safely resolved.") from exc

    @classmethod
    def _apply_restrictive_permissions(cls, path: Path) -> None:
        """Apply restrictive POSIX permissions (0o700 for directories, 0o600 for files).

        Note: On Windows, chmod controls the read-only attribute and does not enforce DACLs.
        The host PROJECT_WORKSPACE_ROOT must be pre-provisioned with restrictive Windows DACLs.
        """
        try:
            if path.is_dir():
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            else:
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            logger.error("Failed to apply restrictive permissions to %s: %s", path, exc)
            raise ChangeGuardException(
                f"Failed to apply restrictive permissions to workspace entry: {path.name}",
                status_code=500,
            ) from exc

    @classmethod
    def _write_owner_marker(cls, run_directory: Path, token: str) -> None:
        """Create ownership marker exclusively inside the run directory using complete writes."""
        marker = run_directory / OWNER_MARKER
        if cls._is_link_or_junction(marker):
            raise ChangeGuardException("Ownership marker path cannot be a link.", status_code=500)

        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_BINARY", 0)
        )
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        fd = os.open(marker, flags, 0o600)
        try:
            fstat = os.fstat(fd)
            if not stat.S_ISREG(fstat.st_mode):
                raise ChangeGuardException("Ownership marker must be a regular file.", status_code=500)
            payload = json.dumps(
                {"token": token, "run_dir": run_directory.name},
                separators=(",", ":"),
            ).encode("utf-8")
            cls._write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

        cls._apply_restrictive_permissions(marker)

    @classmethod
    def _owns_run_directory(cls, run_directory: Path, token: str) -> bool:
        """Verify ownership marker existence, size, type, and token without following links."""
        marker = run_directory / OWNER_MARKER
        try:
            if cls._is_link_or_junction(marker):
                return False
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW

            fd = os.open(marker, flags)
            try:
                fstat = os.fstat(fd)
                if not stat.S_ISREG(fstat.st_mode) or fstat.st_size <= 0 or fstat.st_size > 4096:
                    return False
                if cls._is_link_or_junction(marker):
                    return False
                content = os.read(fd, 4096)
                data = json.loads(content.decode("utf-8"))
                return (
                    isinstance(data, dict)
                    and data.get("token") == token
                    and data.get("run_dir") == run_directory.name
                )
            finally:
                os.close(fd)
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    @classmethod
    def _cleanup_run_directory(
        cls,
        run_directory: Path,
        workspace_root: Path,
        token: str,
        expected_identity: Optional[Tuple[int, int]] = None,
        marker_written: bool = True,
        source_root: Optional[Path] = None,
    ) -> None:
        """Remove only this service's exact, still-contained run directory.

        Fails explicitly if containment, identity, or ownership verification fails.
        """
        if cls._is_link_or_junction(run_directory):
            logger.error(
                "Run directory %s is a symlink or junction; refusing cleanup.",
                run_directory,
            )
            raise ChangeGuardException(
                f"Run directory cleanup refused: {run_directory} is a link or junction.",
                status_code=500,
            )

        if not run_directory.exists():
            return

        if not run_directory.is_dir():
            logger.error("Run directory %s is not a directory; refusing cleanup.", run_directory)
            raise ChangeGuardException(
                f"Run directory cleanup refused: {run_directory} is not a directory.",
                status_code=500,
            )

        try:
            resolved = run_directory.resolve(strict=True)
        except OSError as exc:
            logger.error("Run directory %s could not be resolved: %s", run_directory, exc)
            raise ChangeGuardException(
                f"Run directory cleanup refused: could not resolve {run_directory}.",
                status_code=500,
            ) from exc

        # Never delete workspace root, source root, or non-run directories
        if (
            resolved == workspace_root
            or (source_root is not None and resolved == source_root)
            or resolved.parent != workspace_root
            or not resolved.name.startswith(RUN_DIRECTORY_PREFIX)
        ):
            logger.error(
                "Run directory %s failed containment verification; refusing cleanup.",
                run_directory,
            )
            raise ChangeGuardException(
                f"Run directory cleanup refused: containment verification failed for {run_directory}.",
                status_code=500,
            )

        curr_stat = run_directory.lstat()
        if expected_identity is not None and expected_identity[1] != 0:
            if (curr_stat.st_dev, curr_stat.st_ino) != expected_identity:
                logger.error(
                    "Run directory %s identity changed before cleanup; refusing cleanup.",
                    run_directory,
                )
                raise ChangeGuardException(
                    f"Run directory cleanup refused: identity mismatch for {run_directory}.",
                    status_code=500,
                )

        if marker_written:
            if not cls._owns_run_directory(resolved, token):
                logger.error(
                    "Run directory %s ownership marker verification failed; refusing cleanup.",
                    run_directory,
                )
                raise ChangeGuardException(
                    f"Run directory cleanup refused: ownership verification failed for {run_directory}.",
                    status_code=500,
                )

        try:
            cls._rmtree_safely(resolved)
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.error(
                "Failed to clean up run workspace directory %s: %s",
                run_directory,
                exc,
                exc_info=True,
            )
            raise ChangeGuardException(
                f"Failed to clean up run workspace directory: {run_directory}",
                status_code=500,
            ) from exc

    @classmethod
    def _rmtree_safely(cls, directory: Path) -> None:
        """Remove a directory tree safely, clearing read-only attributes on Windows without following links."""
        def _handle_readonly(func, path, exc):
            if isinstance(exc, (PermissionError, OSError)):
                try:
                    os.chmod(path, stat.S_IWRITE | stat.S_IWUSR)
                    func(path)
                    return
                except Exception:
                    pass
            raise exc

        def _walk_error(error: OSError) -> None:
            logger.error("Traversal error during workspace cleanup walk on %s: %s", directory, error)
            raise error

        for current_root, dirs, files in os.walk(directory, followlinks=False, onerror=_walk_error):
            retained_dirs = []
            for d in dirs:
                dir_path = Path(current_root) / d
                if cls._is_link_or_junction(dir_path):
                    try:
                        os.unlink(dir_path)
                    except OSError:
                        try:
                            os.rmdir(dir_path)
                        except OSError as e:
                            logger.error("Failed to remove junction/link %s: %s", dir_path, e)
                            raise
                else:
                    retained_dirs.append(d)
            dirs[:] = retained_dirs

            for file_name in files:
                file_path = Path(current_root) / file_name
                if not cls._is_link_or_junction(file_path):
                    try:
                        mode = file_path.lstat().st_mode
                        if not (mode & stat.S_IWRITE):
                            os.chmod(file_path, mode | stat.S_IWRITE | stat.S_IWUSR)
                    except OSError as exc:
                        logger.error("Failed to clear read-only attribute on %s: %s", file_path, exc)
                        raise

        if sys.version_info >= (3, 12):
            shutil.rmtree(
                directory,
                onexc=lambda fn, p, exc: _handle_readonly(fn, p, exc),
            )
        else:
            shutil.rmtree(
                directory,
                onerror=lambda fn, p, exc_info: _handle_readonly(
                    fn, p, exc_info[1] if isinstance(exc_info, tuple) else exc_info
                ),
            )
