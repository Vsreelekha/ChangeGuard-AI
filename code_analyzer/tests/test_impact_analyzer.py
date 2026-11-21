"""
Unit tests for Impact Analyzer (code_analyzer.impact_analyzer).
"""

import json
import os
import pytest
from code_analyzer.impact_analyzer import analyze_code_impact


@pytest.fixture
def direct_caller_setup(tmp_path):
    """
    Setup where calculate_tax() is changed, and process_payment() calls calculate_tax().
    """
    billing_code = """
def calculate_tax(amount):
    return amount * 0.18

def process_payment(amount):
    tax = calculate_tax(amount)
    return amount + tax
"""
    f = tmp_path / "billing.py"
    f.write_text(billing_code, encoding="utf-8")

    diff = """diff --git a/billing.py b/billing.py
--- a/billing.py
+++ b/billing.py
@@ -2,2 +2,2 @@
 def calculate_tax(amount):
-    return amount * 0.10
+    return amount * 0.18
"""
    return str(f), diff


@pytest.fixture
def transitive_callers_setup(tmp_path):
    """
    Setup:
    leaf() -> called by mid() -> called by top()
    """
    code = """
def leaf():
    return 100

def mid():
    return leaf() + 10

def top():
    return mid() * 2
"""
    f = tmp_path / "chain.py"
    f.write_text(code, encoding="utf-8")

    diff = """diff --git a/chain.py b/chain.py
--- a/chain.py
+++ b/chain.py
@@ -2,2 +2,2 @@
 def leaf():
-    return 50
+    return 100
"""
    return str(f), diff


@pytest.fixture
def multiple_changed_files_setup(tmp_path):
    """
    Two files:
    pricing.py: get_base_price()
    order.py: make_order() -> calls get_base_price()
    """
    pricing_code = """
def get_base_price():
    return 20.0
"""
    order_code = """
from pricing import get_base_price

def make_order():
    return get_base_price() * 1.05
"""
    f_pricing = tmp_path / "pricing.py"
    f_order = tmp_path / "order.py"
    f_pricing.write_text(pricing_code, encoding="utf-8")
    f_order.write_text(order_code, encoding="utf-8")

    diff = """diff --git a/pricing.py b/pricing.py
--- a/pricing.py
+++ b/pricing.py
@@ -2,2 +2,2 @@
 def get_base_price():
-    return 10.0
+    return 20.0
diff --git a/order.py b/order.py
--- a/order.py
+++ b/order.py
@@ -4,2 +4,2 @@
 def make_order():
-    return get_base_price()
+    return get_base_price() * 1.05
"""
    return [str(f_pricing), str(f_order)], diff


def test_direct_caller(direct_caller_setup):
    file_path, diff = direct_caller_setup
    result = analyze_code_impact(diff, [file_path])

    assert result["success"] is True
    assert len(result["changed_files"]) == 1
    assert len(result["changed_functions"]) == 1
    assert result["changed_functions"][0]["name"] == "calculate_tax"

    assert len(result["impacted_functions"]) == 1
    assert result["impacted_functions"][0]["name"] == "process_payment"
    assert "Directly calls 'calculate_tax'" in result["impacted_functions"][0]["reason"]

    assert result["summary"]["changed_files_count"] == 1
    assert result["summary"]["changed_functions_count"] == 1
    assert result["summary"]["impacted_functions_count"] == 1


def test_transitive_callers(transitive_callers_setup):
    file_path, diff = transitive_callers_setup
    result = analyze_code_impact(diff, [file_path])

    assert result["success"] is True
    assert len(result["changed_functions"]) == 1
    assert result["changed_functions"][0]["name"] == "leaf"

    impacted_names = [f["name"] for f in result["impacted_functions"]]
    assert "mid" in impacted_names
    assert "top" in impacted_names
    assert "leaf" not in impacted_names  # Excluded itself

    reasons = {f["name"]: f["reason"] for f in result["impacted_functions"]}
    assert "Directly calls 'leaf'" in reasons["mid"]
    assert "Transitively calls 'leaf' via mid" in reasons["top"]


def test_multiple_changed_files(multiple_changed_files_setup):
    source_files, diff = multiple_changed_files_setup
    result = analyze_code_impact(diff, source_files)

    assert result["success"] is True
    assert len(result["changed_files"]) == 2
    changed_names = [f["name"] for f in result["changed_functions"]]
    assert "get_base_price" in changed_names
    assert "make_order" in changed_names


def test_changed_line_outside_function(tmp_path):
    code = """
TAX_RATE = 0.20

def calculate(amount):
    return amount * 1.05
"""
    f = tmp_path / "constants.py"
    f.write_text(code, encoding="utf-8")

    diff = """diff --git a/constants.py b/constants.py
--- a/constants.py
+++ b/constants.py
@@ -2,1 +2,1 @@
-TAX_RATE = 0.15
+TAX_RATE = 0.20
"""
    result = analyze_code_impact(diff, [str(f)])
    assert result["success"] is True
    assert result["changed_functions"] == []
    assert result["impacted_functions"] == []
    assert len(result["unassigned_changed_lines"]) == 1
    assert result["unassigned_changed_lines"][0]["lines"] == [2]


def test_file_with_no_functions(tmp_path):
    code = """
# Config only file
ENV = 'production'
PORT = 8080
"""
    f = tmp_path / "config.py"
    f.write_text(code, encoding="utf-8")

    diff = """diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -3,1 +3,1 @@
-PORT = 8000
+PORT = 8080
"""
    result = analyze_code_impact(diff, [str(f)])
    assert result["success"] is True
    assert result["changed_functions"] == []
    assert result["impacted_functions"] == []
    assert len(result["unassigned_changed_lines"]) == 1
    assert result["unassigned_changed_lines"][0]["lines"] == [3]


def test_empty_diff(tmp_path):
    code = "def sample(): pass"
    f = tmp_path / "sample.py"
    f.write_text(code, encoding="utf-8")

    result = analyze_code_impact("", [str(f)])
    assert result["success"] is True
    assert result["changed_files"] == []
    assert result["changed_functions"] == []
    assert result["impacted_functions"] == []
    assert result["summary"]["changed_files_count"] == 0


def test_missing_source_file():
    diff = """diff --git a/missing.py b/missing.py
--- a/missing.py
+++ b/missing.py
@@ -1,1 +1,1 @@
-old
+new
"""
    result = analyze_code_impact(diff, ["missing.py"])
    assert len(result["errors"]) >= 1
    err_msgs = [e["error"] for e in result["errors"]]
    assert any("not found" in msg.lower() for msg in err_msgs)


def test_invalid_python_syntax(tmp_path):
    broken_code = "def broken(\n   return 1"
    f = tmp_path / "broken.py"
    f.write_text(broken_code, encoding="utf-8")

    diff = """diff --git a/broken.py b/broken.py
--- a/broken.py
+++ b/broken.py
@@ -1,1 +1,1 @@
-a
+b
"""
    result = analyze_code_impact(diff, [str(f)])
    assert len(result["errors"]) >= 1
    err_msgs = [e["error"] for e in result["errors"]]
    assert any("syntax error" in msg.lower() for msg in err_msgs)


def test_added_and_deleted_files(tmp_path):
    # Added file exists on disk
    added_code = "def brand_new(): return 1"
    f_added = tmp_path / "new_feature.py"
    f_added.write_text(added_code, encoding="utf-8")

    diff = """diff --git a/new_feature.py b/new_feature.py
new file mode 100644
--- /dev/null
+++ b/new_feature.py
@@ -0,0 +1,1 @@
+def brand_new(): return 1
diff --git a/deleted_file.py b/deleted_file.py
deleted file mode 100644
--- a/deleted_file.py
+++ /dev/null
@@ -1,1 +0,0 @@
-def obsolete(): pass
"""
    result = analyze_code_impact(diff, [str(f_added)])
    assert result["success"] is True
    assert len(result["changed_files"]) == 2

    types = {f["file_path"]: f["change_type"] for f in result["changed_files"]}
    assert types["new_feature.py"] == "added"
    assert types["deleted_file.py"] == "deleted"

    # brand_new should be recognized as a changed function
    assert any(f["name"] == "brand_new" for f in result["changed_functions"])


def test_json_serializable(direct_caller_setup):
    file_path, diff = direct_caller_setup
    result = analyze_code_impact(diff, [file_path])

    serialized = json.dumps(result)
    deserialized = json.loads(serialized)
    assert deserialized == result
