"""
Unit tests for Git Diff Parser (code_analyzer.diff_parser).
"""

import json
import pytest
from code_analyzer.diff_parser import parse_git_diff


SAMPLE_MODIFIED_DIFF = """diff --git a/billing.py b/billing.py
index e69de29..b6fc4c6 100644
--- a/billing.py
+++ b/billing.py
@@ -1,2 +1,2 @@
 def calculate():
-    return price * quantity
+    return price * quantity * 1.18
"""

SAMPLE_ADDED_DIFF = """diff --git a/services/payment.py b/services/payment.py
new file mode 100644
index 0000000..abcdef1
--- /dev/null
+++ b/services/payment.py
@@ -0,0 +1,3 @@
+def process_payment(amount):
+    print(f"Processing: {amount}")
+    return True
"""

SAMPLE_DELETED_DIFF = """diff --git a/legacy/old_service.py b/legacy/old_service.py
deleted file mode 100644
index abcdef1..0000000
--- a/legacy/old_service.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def deprecated_func():
-    pass
"""

SAMPLE_PURE_RENAME_DIFF = """diff --git a/old_utils.py b/new_utils.py
similarity index 100%
rename from old_utils.py
rename to new_utils.py
"""

SAMPLE_RENAME_WITH_MODS_DIFF = """diff --git a/config.py b/app_config.py
similarity index 80%
rename from config.py
rename to app_config.py
index 1234567..89abcde 100644
--- a/config.py
+++ b/app_config.py
@@ -1,2 +1,2 @@
-DEBUG = False
+DEBUG = True
"""

SAMPLE_MULTIPLE_FILES_DIFF = """diff --git a/billing.py b/billing.py
index 1111111..2222222 100644
--- a/billing.py
+++ b/billing.py
@@ -1,2 +1,2 @@
-TAX = 0.10
+TAX = 0.18
diff --git a/new_module.py b/new_module.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/new_module.py
@@ -0,0 +1,2 @@
+def init():
+    pass
diff --git a/old_module.py b/old_module.py
deleted file mode 100644
index 4444444..0000000
--- a/old_module.py
+++ /dev/null
@@ -1,1 +0,0 @@
-unused = 1
"""

SAMPLE_MULTIPLE_HUNKS_DIFF = """diff --git a/math_ops.py b/math_ops.py
index 1234567..89abcde 100644
--- a/math_ops.py
+++ b/math_ops.py
@@ -2,3 +2,3 @@
 def add(a, b):
-    return a - b
+    return a + b
 
@@ -10,3 +10,4 @@
 def multiply(a, b):
-    return 0
+    res = a * b
+    return res
"""

SAMPLE_QUOTED_PATH_WITH_SPACES_DIFF = """diff --git "a/my directory/billing config.py" "b/my directory/billing config.py"
index 1234567..89abcde 100644
--- "a/my directory/billing config.py"
+++ "b/my directory/billing config.py"
@@ -1,2 +1,2 @@
-PORT = 8000
+PORT = 8080
"""

SAMPLE_BINARY_FILE_DIFF = """diff --git a/assets/icon.png b/assets/icon.png
new file mode 100644
index 0000000..abcdef1
Binary files /dev/null and b/assets/icon.png differ
"""

SAMPLE_MODE_CHANGE_DIFF = """diff --git a/scripts/deploy.sh b/scripts/deploy.sh
old mode 100644
new mode 100755
"""

SAMPLE_CRLF_DIFF = "diff --git a/crlf.py b/crlf.py\r\n--- a/crlf.py\r\n+++ b/crlf.py\r\n@@ -1,2 +1,2 @@\r\n-a = 1\r\n+a = 2\r\n"

SAMPLE_TIMESTAMPS_DIFF = """--- a/billing.py\t2026-01-01 12:00:00.000000000 +0000
+++ b/billing.py\t2026-01-01 12:05:00.000000000 +0000
@@ -1,2 +1,2 @@
-v = 1
+v = 2
"""

SAMPLE_EMPTY_LINE_ADDITION_DIFF = """diff --git a/empty_lines.py b/empty_lines.py
--- a/empty_lines.py
+++ b/empty_lines.py
@@ -1,2 +1,3 @@
 line1
+
 line2
"""


def test_modified_file():
    result = parse_git_diff(SAMPLE_MODIFIED_DIFF)
    assert "files" in result
    assert len(result["files"]) == 1

    file_info = result["files"][0]
    assert file_info["file_path"] == "billing.py"
    assert file_info["change_type"] == "modified"

    assert len(file_info["added_lines"]) == 1
    assert file_info["added_lines"][0]["line_number"] == 2
    assert file_info["added_lines"][0]["content"] == "    return price * quantity * 1.18"

    assert len(file_info["deleted_lines"]) == 1
    assert file_info["deleted_lines"][0]["line_number"] == 2
    assert file_info["deleted_lines"][0]["content"] == "    return price * quantity"


def test_added_file():
    result = parse_git_diff(SAMPLE_ADDED_DIFF)
    assert len(result["files"]) == 1

    file_info = result["files"][0]
    assert file_info["file_path"] == "services/payment.py"
    assert file_info["change_type"] == "added"
    assert len(file_info["added_lines"]) == 3
    assert file_info["added_lines"][0]["line_number"] == 1
    assert file_info["added_lines"][0]["content"] == "def process_payment(amount):"
    assert file_info["added_lines"][1]["line_number"] == 2
    assert file_info["added_lines"][2]["line_number"] == 3
    assert len(file_info["deleted_lines"]) == 0


def test_deleted_file():
    result = parse_git_diff(SAMPLE_DELETED_DIFF)
    assert len(result["files"]) == 1

    file_info = result["files"][0]
    assert file_info["file_path"] == "legacy/old_service.py"
    assert file_info["change_type"] == "deleted"
    assert len(file_info["added_lines"]) == 0
    assert len(file_info["deleted_lines"]) == 2
    assert file_info["deleted_lines"][0]["line_number"] == 1
    assert file_info["deleted_lines"][0]["content"] == "def deprecated_func():"
    assert file_info["deleted_lines"][1]["line_number"] == 2


def test_pure_rename():
    result = parse_git_diff(SAMPLE_PURE_RENAME_DIFF)
    assert len(result["files"]) == 1

    file_info = result["files"][0]
    assert file_info["file_path"] == "new_utils.py"
    assert file_info["change_type"] == "renamed"
    assert file_info["added_lines"] == []
    assert file_info["deleted_lines"] == []


def test_rename_with_modifications():
    result = parse_git_diff(SAMPLE_RENAME_WITH_MODS_DIFF)
    assert len(result["files"]) == 1

    file_info = result["files"][0]
    assert file_info["file_path"] == "app_config.py"
    assert file_info["change_type"] == "renamed"
    assert len(file_info["added_lines"]) == 1
    assert file_info["added_lines"][0]["line_number"] == 1
    assert file_info["added_lines"][0]["content"] == "DEBUG = True"
    assert len(file_info["deleted_lines"]) == 1
    assert file_info["deleted_lines"][0]["line_number"] == 1
    assert file_info["deleted_lines"][0]["content"] == "DEBUG = False"


def test_multiple_files():
    result = parse_git_diff(SAMPLE_MULTIPLE_FILES_DIFF)
    assert len(result["files"]) == 3

    f1, f2, f3 = result["files"]
    assert f1["file_path"] == "billing.py"
    assert f1["change_type"] == "modified"

    assert f2["file_path"] == "new_module.py"
    assert f2["change_type"] == "added"

    assert f3["file_path"] == "old_module.py"
    assert f3["change_type"] == "deleted"


def test_multiple_hunks_in_single_file():
    result = parse_git_diff(SAMPLE_MULTIPLE_HUNKS_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]

    assert f["file_path"] == "math_ops.py"
    assert f["change_type"] == "modified"

    # First hunk starts at line 2: line 2 is context 'def add(a, b):', line 3 is changed
    assert any(line["line_number"] == 3 and line["content"] == "    return a + b" for line in f["added_lines"])
    assert any(line["line_number"] == 3 and line["content"] == "    return a - b" for line in f["deleted_lines"])

    # Second hunk starts at line 10: line 10 is context 'def multiply(a, b):', line 11 and 12 are changed
    assert any(line["line_number"] == 11 and line["content"] == "    res = a * b" for line in f["added_lines"])
    assert any(line["line_number"] == 12 and line["content"] == "    return res" for line in f["added_lines"])
    assert any(line["line_number"] == 11 and line["content"] == "    return 0" for line in f["deleted_lines"])


def test_quoted_paths_with_spaces():
    result = parse_git_diff(SAMPLE_QUOTED_PATH_WITH_SPACES_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]
    assert f["file_path"] == "my directory/billing config.py"
    assert f["change_type"] == "modified"
    assert f["added_lines"][0]["content"] == "PORT = 8080"


def test_binary_file():
    result = parse_git_diff(SAMPLE_BINARY_FILE_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]
    assert f["file_path"] == "assets/icon.png"
    assert f["change_type"] == "added"
    assert f["added_lines"] == []
    assert f["deleted_lines"] == []


def test_mode_change():
    result = parse_git_diff(SAMPLE_MODE_CHANGE_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]
    assert f["file_path"] == "scripts/deploy.sh"
    assert f["change_type"] == "modified"
    assert f["added_lines"] == []
    assert f["deleted_lines"] == []


def test_crlf_endings():
    result = parse_git_diff(SAMPLE_CRLF_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]
    assert f["file_path"] == "crlf.py"
    assert f["change_type"] == "modified"
    assert f["added_lines"][0]["content"] == "a = 2"


def test_timestamps_in_header():
    result = parse_git_diff(SAMPLE_TIMESTAMPS_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]
    assert f["file_path"] == "billing.py"
    assert f["change_type"] == "modified"
    assert f["added_lines"][0]["content"] == "v = 2"


def test_empty_line_addition():
    result = parse_git_diff(SAMPLE_EMPTY_LINE_ADDITION_DIFF)
    assert len(result["files"]) == 1
    f = result["files"][0]
    assert f["file_path"] == "empty_lines.py"
    assert any(line["line_number"] == 2 and line["content"] == "" for line in f["added_lines"])


def test_windows_backslash_paths():
    diff_with_backslashes = """diff --git a\\services\\billing.py b\\services\\billing.py
--- a\\services\\billing.py
+++ b\\services\\billing.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = parse_git_diff(diff_with_backslashes)
    assert len(result["files"]) == 1
    assert result["files"][0]["file_path"] == "services/billing.py"


def test_git_show_with_commit_log():
    diff_with_commit = """commit 1234567890abcdef1234567890abcdef12345678
Author: Developer <developer@example.com>
Date:   Mon Nov 17 12:00:00 2026 +0530

    feat: update tax calculations

diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = parse_git_diff(diff_with_commit)
    assert len(result["files"]) == 1
    assert result["files"][0]["file_path"] == "billing.py"


def test_rename_across_directories():
    rename_dir_diff = """diff --git a/src/old_dir/service.py b/lib/new_dir/service.py
similarity index 100%
rename from src/old_dir/service.py
rename to lib/new_dir/service.py
"""
    result = parse_git_diff(rename_dir_diff)
    assert len(result["files"]) == 1
    assert result["files"][0]["file_path"] == "lib/new_dir/service.py"
    assert result["files"][0]["change_type"] == "renamed"


def test_raw_patch_multiple_files_without_diff_git():
    patch_diff = """--- a/mod1.py
+++ b/mod1.py
@@ -1,1 +1,1 @@
-1
+2
--- a/mod2.py
+++ b/mod2.py
@@ -1,1 +1,1 @@
-a
+b
"""
    result = parse_git_diff(patch_diff)
    assert len(result["files"]) == 2
    assert result["files"][0]["file_path"] == "mod1.py"
    assert result["files"][1]["file_path"] == "mod2.py"


def test_empty_and_whitespace_input():
    assert parse_git_diff("") == {"files": []}
    assert parse_git_diff("   \n\t  \n  ") == {"files": []}


def test_none_input():
    assert parse_git_diff(None) == {"files": []}


def test_invalid_type_input():
    assert parse_git_diff(12345) == {"files": []}
    assert parse_git_diff(["diff --git"]) == {"files": []}
    assert parse_git_diff({"diff": "text"}) == {"files": []}


def test_invalid_text_input():
    assert parse_git_diff("This is just some random text with no diff formatting at all.") == {"files": []}
    assert parse_git_diff("diff --git without valid paths") == {"files": []}
    assert parse_git_diff("diff --git a/only_one") == {"files": []}


def test_json_serializable():
    result = parse_git_diff(SAMPLE_MODIFIED_DIFF)
    serialized = json.dumps(result)
    deserialized = json.loads(serialized)
    assert deserialized == result
