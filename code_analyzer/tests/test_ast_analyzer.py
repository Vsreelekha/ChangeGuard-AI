"""
Unit tests for Python AST Analyzer (code_analyzer.ast_analyzer).
"""

import json
import os
import tempfile
import pytest
from code_analyzer.ast_analyzer import (
    analyze_changed_functions,
    analyze_changed_functions_from_source
)


SAMPLE_PYTHON_CODE = '''"""Sample module for AST testing."""

GLOBAL_TAX = 0.18

def calculate_total(price, quantity):
    subtotal = price * quantity
    total = subtotal * (1 + GLOBAL_TAX)
    return total

class OrderService:
    service_name = "OrderManager"

    def __init__(self, currency="USD"):
        self.currency = currency
        self.items = []

    def process_order(self, order_id, price, qty):
        def validate(pid):
            if pid <= 0:
                raise ValueError("Invalid order id")
            return True

        validate(order_id)
        total = calculate_total(price, qty)
        self.items.append((order_id, total))
        return total

    async def fetch_status(self):
        return "completed"

def helper_func():
    return "done"

TRAILING_CONSTANT = 999
'''


@pytest.fixture
def sample_file(tmp_path):
    """Creates a temporary python file with sample source code."""
    file_path = tmp_path / "sample_module.py"
    file_path.write_text(SAMPLE_PYTHON_CODE, encoding="utf-8")
    return str(file_path)


def test_top_level_function_single_change(sample_file):
    # Line 7 is: total = subtotal * (1 + GLOBAL_TAX)
    result = analyze_changed_functions(sample_file, [7])
    assert result["success"] is True
    assert result["error"] is None
    assert len(result["functions"]) == 1

    fn = result["functions"][0]
    assert fn["name"] == "calculate_total"
    assert fn["qualified_name"] == "calculate_total"
    assert fn["start_line"] == 5
    assert fn["end_line"] == 8
    assert fn["parent_class"] is None
    assert fn["is_method"] is False
    assert fn["changed_lines"] == [7]
    assert result["unassigned_lines"] == []


def test_multiple_changed_lines_same_function(sample_file):
    # Lines 6, 7, 8 are all inside calculate_total
    result = analyze_changed_functions(sample_file, [6, 7, 8])
    assert result["success"] is True
    assert len(result["functions"]) == 1

    fn = result["functions"][0]
    assert fn["name"] == "calculate_total"
    assert fn["changed_lines"] == [6, 7, 8]
    assert result["unassigned_lines"] == []


def test_changes_in_multiple_functions(sample_file):
    # Line 6 is in calculate_total, Line 32 is in helper_func
    result = analyze_changed_functions(sample_file, [6, 32])
    assert result["success"] is True
    assert len(result["functions"]) == 2

    func_names = [f["name"] for f in result["functions"]]
    assert func_names == ["calculate_total", "helper_func"]
    assert result["unassigned_lines"] == []


def test_class_method_change(sample_file):
    # Line 15 is: self.items = [] inside OrderService.__init__
    result = analyze_changed_functions(sample_file, [15])
    assert result["success"] is True
    assert len(result["functions"]) == 1

    fn = result["functions"][0]
    assert fn["name"] == "__init__"
    assert fn["qualified_name"] == "OrderService.__init__"
    assert fn["parent_class"] == "OrderService"
    assert fn["is_method"] is True
    assert fn["start_line"] == 13
    assert fn["end_line"] == 15
    assert fn["changed_lines"] == [15]


def test_nested_function_change(sample_file):
    # Lines 19, 20 are inside nested validate() function in process_order()
    result = analyze_changed_functions(sample_file, [20])
    assert result["success"] is True
    assert len(result["functions"]) == 1

    fn = result["functions"][0]
    assert fn["name"] == "validate"
    assert fn["qualified_name"] == "OrderService.process_order.validate"
    assert fn["is_method"] is False
    assert fn["changed_lines"] == [20]


def test_enclosing_method_outside_nested_function(sample_file):
    # Line 24 is: total = calculate_total(price, qty) inside process_order() outside validate()
    result = analyze_changed_functions(sample_file, [24])
    assert result["success"] is True
    assert len(result["functions"]) == 1

    fn = result["functions"][0]
    assert fn["name"] == "process_order"
    assert fn["qualified_name"] == "OrderService.process_order"
    assert fn["parent_class"] == "OrderService"
    assert fn["is_method"] is True


def test_async_method_change(sample_file):
    # Line 29 is: return "completed" inside async def fetch_status(self)
    result = analyze_changed_functions(sample_file, [29])
    assert result["success"] is True
    assert len(result["functions"]) == 1

    fn = result["functions"][0]
    assert fn["name"] == "fetch_status"
    assert fn["qualified_name"] == "OrderService.fetch_status"
    assert fn["is_method"] is True


def test_changes_outside_functions(sample_file):
    # Line 3 is GLOBAL_TAX = 0.18 (module-level)
    # Line 11 is service_name = "OrderManager" (class-level attribute)
    # Line 34 is TRAILING_CONSTANT = 999
    result = analyze_changed_functions(sample_file, [3, 11, 34])
    assert result["success"] is True
    assert len(result["functions"]) == 0
    assert result["unassigned_lines"] == [3, 11, 34]


def test_mixed_function_and_unassigned_lines(sample_file):
    # Line 3 is outside, Line 6 is inside calculate_total
    result = analyze_changed_functions(sample_file, [3, 6])
    assert result["success"] is True
    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "calculate_total"
    assert result["unassigned_lines"] == [3]


def test_empty_changed_lines(sample_file):
    result = analyze_changed_functions(sample_file, [])
    assert result["success"] is True
    assert result["error"] is None
    assert result["functions"] == []
    assert result["unassigned_lines"] == []


def test_missing_file():
    result = analyze_changed_functions("non_existent_file_12345.py", [10])
    assert result["success"] is False
    assert "File not found" in result["error"]
    assert result["functions"] == []
    assert result["unassigned_lines"] == []


def test_invalid_python_syntax(tmp_path):
    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def broken_syntax(\n    return 42\n", encoding="utf-8")

    result = analyze_changed_functions(str(broken_file), [2])
    assert result["success"] is False
    assert "Syntax error" in result["error"]
    assert result["functions"] == []
    assert result["unassigned_lines"] == []


def test_decorated_function(tmp_path):
    code = """@staticmethod
@some_decorator
def decorated_func():
    return 1
"""
    file_path = tmp_path / "decorated.py"
    file_path.write_text(code, encoding="utf-8")

    # Line 1 is decorator, Line 4 is body
    result = analyze_changed_functions(str(file_path), [1, 4])
    assert result["success"] is True
    assert len(result["functions"]) == 1
    assert result["functions"][0]["name"] == "decorated_func"
    assert result["functions"][0]["changed_lines"] == [1, 4]


def test_invalid_inputs():
    assert analyze_changed_functions("", [1])["success"] is False
    assert analyze_changed_functions(None, [1])["success"] is False
    assert analyze_changed_functions_from_source(None, [1])["success"] is False
    assert analyze_changed_functions_from_source("x = 1", "not a list")["success"] is False
    assert analyze_changed_functions_from_source("x = 1", ["not an int"])["success"] is False


def test_json_serializable(sample_file):
    result = analyze_changed_functions(sample_file, [6, 15, 3])
    serialized = json.dumps(result)
    deserialized = json.loads(serialized)
    assert deserialized == result
