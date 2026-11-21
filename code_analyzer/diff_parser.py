"""
Git Diff Parser for ChangeGuard AI.

Parses standard unified Git diff output and extracts structured, JSON-compatible
information about changed files, change types, and added/deleted lines with line numbers.
"""

import re
from typing import Any, Dict, List, Optional


def _clean_file_path(path: Optional[str]) -> str:
    """
    Clean and normalize a file path extracted from Git diff metadata.

    Strips Git prefixes (a/, b/) and enclosing quotation marks, and normalizes
    backslashes to forward slashes.

    Args:
        path: Raw path string from diff headers.

    Returns:
        Cleaned relative file path.
    """
    if not path:
        return ""
    p = path.strip()
    # Normalize backslashes to forward slashes for cross-platform consistency
    p = p.replace("\\", "/")
    # Strip quotes if wrapped
    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
        p = p[1:-1]
    # Strip git prefix a/ or b/
    if p.startswith("a/") or p.startswith("b/"):
        p = p[2:]
    # Strip quotes again in case they were inside prefix (e.g. a/"file.py")
    if (p.startswith('"') and p.endswith('"')) or (p.startswith("'") and p.endswith("'")):
        p = p[1:-1]
    return p


def _split_diff_into_files(diff_text: str) -> List[str]:
    """
    Split unified diff text into per-file chunks.

    Supports standard 'diff --git' markers and fallback '--- a/' markers.

    Args:
        diff_text: Full diff text.

    Returns:
        List of diff chunks corresponding to each file.
    """
    if "diff --git " in diff_text:
        chunks = re.split(r"(?m)^(?=diff --git )", diff_text)
    elif re.search(r'(?m)^--- (?:[ab]/|/dev/null|"[ab]/)', diff_text):
        chunks = re.split(r'(?m)^(?=--- (?:[ab]/|/dev/null|"[ab]/))', diff_text)
    else:
        chunks = [diff_text]
    return [c for c in chunks if c.strip()]


def _parse_file_diff(file_diff_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a single file's diff text chunk.

    Args:
        file_diff_text: String representing diff for one file.

    Returns:
        Dict representation of changed file, or None if invalid.
    """
    lines = file_diff_text.splitlines()
    if not lines:
        return None

    git_a_path: Optional[str] = None
    git_b_path: Optional[str] = None
    old_file_line: Optional[str] = None
    new_file_line: Optional[str] = None
    rename_from: Optional[str] = None
    rename_to: Optional[str] = None
    copy_to: Optional[str] = None
    is_new = False
    is_deleted = False
    is_renamed = False
    is_binary = False
    is_mode_change = False

    hunk_start_idx = -1

    for idx, line in enumerate(lines):
        if line.startswith("diff --git "):
            # Match diff --git a/path b/path or quoted versions with a/ and b/
            m = re.match(r'^diff --git\s+(?:"a/(.+?)"|a/(.+?))\s+(?:"b/(.+?)"|b/(.+?))$', line)
            if m:
                git_a_path = m.group(1) or m.group(2)
                git_b_path = m.group(3) or m.group(4)
        elif line.startswith("new file mode"):
            is_new = True
        elif line.startswith("deleted file mode"):
            is_deleted = True
        elif line.startswith("old mode ") or line.startswith("new mode "):
            is_mode_change = True
        elif line.startswith("rename from "):
            rename_from = _clean_file_path(line[12:].strip())
            is_renamed = True
        elif line.startswith("rename to "):
            rename_to = _clean_file_path(line[10:].strip())
            is_renamed = True
        elif line.startswith("copy to "):
            copy_to = _clean_file_path(line[8:].strip())
            is_new = True
        elif line.startswith("similarity index "):
            is_renamed = True
        elif line.startswith("Binary files ") and " differ" in line:
            is_binary = True
        elif line.startswith("--- "):
            raw = line[4:].strip().split("\t")[0].strip()
            old_file_line = raw
        elif line.startswith("+++ "):
            raw = line[4:].strip().split("\t")[0].strip()
            new_file_line = raw
        elif line.startswith("@@"):
            hunk_start_idx = idx
            break

    clean_old = _clean_file_path(old_file_line) if old_file_line else None
    clean_new = _clean_file_path(new_file_line) if new_file_line else None

    # Determine change_type and file_path
    if is_renamed or rename_to or rename_from:
        change_type = "renamed"
        file_path = rename_to or clean_new or git_b_path or rename_from or clean_old or git_a_path
    elif is_new or copy_to or old_file_line == "/dev/null":
        change_type = "added"
        file_path = copy_to or clean_new or git_b_path or clean_old or git_a_path
    elif is_deleted or new_file_line == "/dev/null":
        change_type = "deleted"
        file_path = clean_old or git_a_path or clean_new or git_b_path
    else:
        change_type = "modified"
        file_path = clean_new or git_b_path or clean_old or git_a_path

    if not file_path or file_path == "/dev/null":
        return None

    # Validate that this is a recognized diff and not arbitrary text
    if (
        change_type == "modified"
        and hunk_start_idx == -1
        and not old_file_line
        and not new_file_line
        and not is_binary
        and not is_mode_change
    ):
        return None

    added_lines: List[Dict[str, Any]] = []
    deleted_lines: List[Dict[str, Any]] = []

    if hunk_start_idx != -1:
        in_hunk = False
        old_line = 0
        new_line = 0

        for line in lines[hunk_start_idx:]:
            if line.startswith("@@"):
                match = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", line)
                if match:
                    in_hunk = True
                    old_start = int(match.group(1))
                    new_start = int(match.group(3))
                    # Handle 0-indexed boundaries safely
                    old_line = max(1, old_start) if old_start == 0 and match.group(2) != "0" else old_start
                    new_line = max(1, new_start) if new_start == 0 and match.group(4) != "0" else new_start
                    continue
                else:
                    in_hunk = False
                    continue

            if not in_hunk:
                continue

            if line.startswith(r"\ No newline at end of file"):
                continue

            if line.startswith("+"):
                added_lines.append({
                    "line_number": new_line,
                    "content": line[1:]
                })
                new_line += 1
            elif line.startswith("-"):
                deleted_lines.append({
                    "line_number": old_line,
                    "content": line[1:]
                })
                old_line += 1
            elif line.startswith(" "):
                old_line += 1
                new_line += 1
            elif line == "":
                # Empty context line
                old_line += 1
                new_line += 1

    return {
        "file_path": file_path,
        "change_type": change_type,
        "added_lines": added_lines,
        "deleted_lines": deleted_lines
    }


def parse_git_diff(diff_text: str) -> Dict[str, Any]:
    """
    Parse a unified Git diff string and return structured JSON-compatible information.

    Args:
        diff_text: Unified Git diff output as a string.

    Returns:
        dict: A dictionary containing a 'files' list:
            {
                "files": [
                    {
                        "file_path": str,
                        "change_type": "added" | "modified" | "deleted" | "renamed",
                        "added_lines": [
                            {"line_number": int, "content": str},
                            ...
                        ],
                        "deleted_lines": [
                            {"line_number": int, "content": str},
                            ...
                        ]
                    },
                    ...
                ]
            }
    """
    if not diff_text or not isinstance(diff_text, str) or not diff_text.strip():
        return {"files": []}

    try:
        file_chunks = _split_diff_into_files(diff_text)
        parsed_files = []

        for chunk in file_chunks:
            parsed = _parse_file_diff(chunk)
            if parsed is not None:
                parsed_files.append(parsed)

        return {"files": parsed_files}
    except Exception:
        return {"files": []}
