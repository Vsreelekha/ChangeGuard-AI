"""Secure project path validation and bounded Python source discovery."""

import os
from pathlib import Path
from typing import List, Optional, Sequence

from app.core.config import get_settings
from app.core.exceptions import ChangeGuardException, InvalidInputError


MAX_SOURCE_DISCOVERY_DEPTH = 20
MAX_SOURCE_FILES = 10_000
MAX_TRAVERSED_ENTRIES = 100_000

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "site-packages",
    "node_modules",
    "bower_components",
    "__pypackages__",
    "build",
    "dist",
    "out",
    "target",
    "vendor",
    ".cache",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".nox",
    ".next",
    ".turbo",
    ".pants.d",
    "coverage",
    "htmlcov",
}


def _is_within(path: Path, root: Path) -> bool:
    """Return whether canonical path is root itself or a descendant of root."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _canonical_approved_roots(approved_roots: Optional[Sequence[str]]) -> List[Path]:
    if approved_roots is None:
        approved_roots = get_settings().APPROVED_PROJECT_ROOTS

    if not isinstance(approved_roots, (list, tuple)) or not approved_roots:
        raise ChangeGuardException(
            "APPROVED_PROJECT_ROOTS must be explicitly configured with one or more absolute directories.",
            status_code=500,
        )

    if len(approved_roots) == 1 and isinstance(approved_roots[0], str):
        if approved_roots[0].strip().replace("\\", "/") in {".", "./"}:
            raise ChangeGuardException(
                'APPROVED_PROJECT_ROOTS=["."] is unsafe; configure explicit absolute project roots.',
                status_code=500,
            )

    canonical_roots: List[Path] = []
    for configured_root in approved_roots:
        if not isinstance(configured_root, str) or not configured_root.strip():
            raise ChangeGuardException(
                "APPROVED_PROJECT_ROOTS contains an empty or invalid path.", status_code=500
            )
        root_path = Path(configured_root.strip())
        if not root_path.is_absolute():
            raise ChangeGuardException(
                "Every APPROVED_PROJECT_ROOTS entry must be an absolute path.", status_code=500
            )
        try:
            canonical_root = root_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ChangeGuardException(
                f"Configured approved project root is invalid: '{configured_root}'.", status_code=500
            ) from exc
        if not canonical_root.is_dir():
            raise ChangeGuardException(
                f"Configured approved project root is not a directory: '{configured_root}'.",
                status_code=500,
            )
        canonical_roots.append(canonical_root)

    return canonical_roots


def validate_project_path(
    project_path: str,
    approved_roots: Optional[Sequence[str]] = None,
) -> Path:
    """Resolve a project directory and ensure it is inside an explicitly approved root."""
    if not isinstance(project_path, str) or not project_path.strip():
        raise InvalidInputError("Project path must be a non-empty directory path.")
    try:
        resolved_path = Path(project_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InvalidInputError(f"Specified project path does not exist or cannot be resolved: '{project_path}'.") from exc

    if not resolved_path.is_dir():
        raise InvalidInputError(f"Specified project path is not a directory: '{project_path}'.")

    roots = _canonical_approved_roots(approved_roots)
    if not any(_is_within(resolved_path, root) for root in roots):
        raise InvalidInputError("Project path is outside the explicitly approved directory roots.")

    return resolved_path


def _is_directory_link(entry: os.DirEntry) -> bool:
    """Recognize symlinked directories and Windows junctions without traversing them."""
    if entry.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    return bool(is_junction and is_junction(entry.path))


def discover_python_source_files(
    project_path: str,
    approved_roots: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return absolute .py paths using a bounded walk that never traverses directory links."""
    project_root = validate_project_path(project_path, approved_roots)
    discovered: List[str] = []
    pending = [(project_root, 0)]
    traversed_entries = 0

    while pending:
        current_dir, depth = pending.pop()
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    traversed_entries += 1
                    if traversed_entries > MAX_TRAVERSED_ENTRIES:
                        raise InvalidInputError(
                            f"Project traversal exceeded the limit of {MAX_TRAVERSED_ENTRIES} entries."
                        )

                    entry_path = Path(entry.path)
                    if _is_directory_link(entry):
                        if entry.name.casefold() in EXCLUDED_DIRECTORY_NAMES:
                            continue
                        try:
                            is_file_link = entry.is_file(follow_symlinks=True)
                        except OSError as exc:
                            raise InvalidInputError(f"Cannot inspect project entry '{entry.path}'.") from exc
                        if not is_file_link or entry_path.suffix.casefold() != ".py":
                            continue
                    else:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name.casefold() in EXCLUDED_DIRECTORY_NAMES:
                                    continue
                                if depth >= MAX_SOURCE_DISCOVERY_DEPTH:
                                    raise InvalidInputError(
                                        f"Project traversal exceeded maximum depth {MAX_SOURCE_DISCOVERY_DEPTH}."
                                    )
                                pending.append((entry_path, depth + 1))
                                continue
                            if entry_path.suffix.casefold() != ".py" or not entry.is_file(follow_symlinks=False):
                                continue
                        except OSError as exc:
                            raise InvalidInputError(f"Cannot inspect project entry '{entry.path}'.") from exc

                    try:
                        resolved_file = entry_path.resolve(strict=True)
                    except (OSError, RuntimeError) as exc:
                        raise InvalidInputError(f"Cannot resolve Python source file '{entry.path}'.") from exc
                    if not _is_within(resolved_file, project_root):
                        raise InvalidInputError(
                            f"Python source file resolves outside the validated project directory: '{entry.path}'."
                        )
                    if not resolved_file.is_file() or not os.access(resolved_file, os.R_OK):
                        raise InvalidInputError(f"Python source file is not readable: '{entry.path}'.")

                    discovered.append(str(resolved_file))
                    if len(discovered) > MAX_SOURCE_FILES:
                        raise InvalidInputError(
                            f"Project contains more than the maximum of {MAX_SOURCE_FILES} Python source files."
                        )
        except InvalidInputError:
            raise
        except OSError as exc:
            raise InvalidInputError(f"Cannot read project directory '{current_dir}'.") from exc

    return sorted(set(discovered))
