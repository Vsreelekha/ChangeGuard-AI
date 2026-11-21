"""
Unit tests for NetworkX Dependency Graph (code_analyzer.dependency_graph).
"""

import json
import os
import pytest
from code_analyzer.dependency_graph import (
    build_dependency_graph,
    build_networkx_digraph,
    get_impacted_functions
)


@pytest.fixture
def simple_chain_files(tmp_path):
    """
    Creates files representing:
    f_a() -> f_b() -> f_c()
    """
    code = """
def f_c():
    return 42

def f_b():
    return f_c() + 1

def f_a():
    return f_b() * 2
"""
    file_path = tmp_path / "chain.py"
    file_path.write_text(code, encoding="utf-8")
    return [str(file_path)]


@pytest.fixture
def multiple_callers_files(tmp_path):
    """
    Creates files representing:
    caller1() -> shared()
    caller2() -> shared()
    """
    code = """
def shared():
    return "shared result"

def caller1():
    return shared()

def caller2():
    return shared()
"""
    file_path = tmp_path / "callers.py"
    file_path.write_text(code, encoding="utf-8")
    return [str(file_path)]


@pytest.fixture
def multi_file_project(tmp_path):
    """
    Creates a multi-file setup:
    utils.py: format_value()
    billing.py: compute_tax() -> uses utils.format_value()
    order.py: create_order() -> uses billing.compute_tax()
    """
    utils_code = """
def format_value(val):
    return f"${val:.2f}"
"""
    billing_code = """
from utils import format_value

def compute_tax(amount):
    tax = amount * 0.18
    return format_value(tax)
"""
    order_code = """
from billing import compute_tax

def create_order(price):
    tax = compute_tax(price)
    return tax
"""
    f_utils = tmp_path / "utils.py"
    f_billing = tmp_path / "billing.py"
    f_order = tmp_path / "order.py"

    f_utils.write_text(utils_code, encoding="utf-8")
    f_billing.write_text(billing_code, encoding="utf-8")
    f_order.write_text(order_code, encoding="utf-8")

    return [str(f_utils), str(f_billing), str(f_order)]


@pytest.fixture
def class_methods_file(tmp_path):
    code = """
class PaymentProcessor:
    def validate(self, amount):
        return amount > 0

    def process(self, amount):
        if self.validate(amount):
            return "paid"
        return "declined"
"""
    file_path = tmp_path / "payment.py"
    file_path.write_text(code, encoding="utf-8")
    return [str(file_path)]


@pytest.fixture
def nested_functions_file(tmp_path):
    code = """
def outer():
    def inner():
        return 1
    return inner() + 2
"""
    file_path = tmp_path / "nested.py"
    file_path.write_text(code, encoding="utf-8")
    return [str(file_path)]


@pytest.fixture
def duplicate_names_files(tmp_path):
    code_mod1 = """
def calculate():
    return 100
"""
    code_mod2 = """
def calculate():
    return 200

def run():
    return calculate()
"""
    f1 = tmp_path / "mod1.py"
    f2 = tmp_path / "mod2.py"
    f1.write_text(code_mod1, encoding="utf-8")
    f2.write_text(code_mod2, encoding="utf-8")
    return [str(f1), str(f2)]


def test_simple_dependency_chain(simple_chain_files):
    result = build_dependency_graph(simple_chain_files)
    assert result["success"] is True
    assert len(result["nodes"]) == 3
    assert len(result["edges"]) == 2

    # Edges should be: f_a -> f_b, and f_b -> f_c
    edge_pairs = [(e["caller"].split(":")[-1], e["callee"].split(":")[-1]) for e in result["edges"]]
    assert ("f_a", "f_b") in edge_pairs
    assert ("f_b", "f_c") in edge_pairs

    # When f_c changes: f_b and f_a are impacted
    impact = get_impacted_functions(result, ["f_c"])
    assert impact["success"] is True
    impacted_names = [f["name"] for f in impact["impacted_functions"]]
    assert "f_b" in impacted_names
    assert "f_a" in impacted_names
    assert "f_c" not in impacted_names

    # Check reasons
    reasons = {f["name"]: f["reason"] for f in impact["impacted_functions"]}
    assert "Directly calls 'f_c'" in reasons["f_b"]
    assert "Transitively calls 'f_c' via f_b" in reasons["f_a"]


def test_multiple_callers(multiple_callers_files):
    result = build_dependency_graph(multiple_callers_files)
    assert result["success"] is True

    impact = get_impacted_functions(result, ["shared"])
    impacted_names = [f["name"] for f in impact["impacted_functions"]]
    assert len(impacted_names) == 2
    assert "caller1" in impacted_names
    assert "caller2" in impacted_names


def test_independent_functions(tmp_path):
    code = """
def standalone_a():
    return 1

def standalone_b():
    return 2
"""
    f = tmp_path / "independent.py"
    f.write_text(code, encoding="utf-8")

    result = build_dependency_graph([str(f)])
    assert result["success"] is True
    assert len(result["edges"]) == 0

    impact = get_impacted_functions(result, ["standalone_a"])
    assert impact["impacted_functions"] == []


def test_multiple_source_files(multi_file_project):
    result = build_dependency_graph(multi_file_project)
    assert result["success"] is True

    # When format_value in utils.py changes, both compute_tax and create_order are impacted
    impact = get_impacted_functions(result, ["format_value"])
    impacted_names = [f["name"] for f in impact["impacted_functions"]]
    assert "compute_tax" in impacted_names
    assert "create_order" in impacted_names


def test_class_methods(class_methods_file):
    result = build_dependency_graph(class_methods_file)
    assert result["success"] is True

    # process() calls self.validate()
    edge_pairs = [(e["caller"].split(":")[-1], e["callee"].split(":")[-1]) for e in result["edges"]]
    assert ("PaymentProcessor.process", "PaymentProcessor.validate") in edge_pairs

    # When validate changes, process is impacted
    impact = get_impacted_functions(result, ["PaymentProcessor.validate"])
    impacted_names = [f["name"] for f in impact["impacted_functions"]]
    assert "process" in impacted_names


def test_nested_functions(nested_functions_file):
    result = build_dependency_graph(nested_functions_file)
    assert result["success"] is True

    # outer() calls inner()
    edge_pairs = [(e["caller"].split(":")[-1], e["callee"].split(":")[-1]) for e in result["edges"]]
    assert ("outer", "outer.inner") in edge_pairs

    impact = get_impacted_functions(result, ["inner"])
    impacted_names = [f["name"] for f in impact["impacted_functions"]]
    assert "outer" in impacted_names


def test_transitive_dependencies(simple_chain_files):
    result = build_dependency_graph(simple_chain_files)

    # When f_b changes, only f_a is impacted (f_c is callee, not caller)
    impact_b = get_impacted_functions(result, ["f_b"])
    names_b = [f["name"] for f in impact_b["impacted_functions"]]
    assert names_b == ["f_a"]

    # When f_c changes, both f_b and f_a are impacted
    impact_c = get_impacted_functions(result, ["f_c"])
    names_c = [f["name"] for f in impact_c["impacted_functions"]]
    assert set(names_c) == {"f_b", "f_a"}


def test_duplicate_function_names(duplicate_names_files):
    result = build_dependency_graph(duplicate_names_files)
    assert result["success"] is True
    assert len(result["nodes"]) == 3

    # mod2.py:run calls mod2.py:calculate, NOT mod1.py:calculate
    f2_calc_id = [n["id"] for n in result["nodes"] if "mod2.py:calculate" in n["id"]][0]
    f1_calc_id = [n["id"] for n in result["nodes"] if "mod1.py:calculate" in n["id"]][0]

    # Changing mod1.py:calculate should NOT impact mod2.py:run
    impact1 = get_impacted_functions(result, [f1_calc_id])
    assert impact1["impacted_functions"] == []

    # Changing mod2.py:calculate SHOULD impact mod2.py:run
    impact2 = get_impacted_functions(result, [f2_calc_id])
    assert len(impact2["impacted_functions"]) == 1
    assert impact2["impacted_functions"][0]["name"] == "run"


def test_missing_files():
    result = build_dependency_graph(["non_existent_file_9999.py"])
    assert result["success"] is False
    assert len(result["errors"]) == 1
    assert "File not found" in result["errors"][0]["error"]


def test_invalid_python_syntax(tmp_path):
    broken_file = tmp_path / "broken.py"
    broken_file.write_text("def broken_syntax(\n    return 1", encoding="utf-8")

    result = build_dependency_graph([str(broken_file)])
    assert result["success"] is False
    assert len(result["errors"]) == 1
    assert "Syntax error" in result["errors"][0]["error"]


def test_unknown_changed_function_identifier(simple_chain_files):
    result = build_dependency_graph(simple_chain_files)

    # Unknown identifier handled safely without crashing
    impact = get_impacted_functions(result, ["completely_unknown_func"])
    assert impact["success"] is True
    assert impact["impacted_functions"] == []
    assert impact["unknown_functions"] == ["completely_unknown_func"]


def test_accepts_networkx_digraph_directly(simple_chain_files):
    graph, errors = build_networkx_digraph(simple_chain_files)
    assert len(errors) == 0

    impact = get_impacted_functions(graph, ["f_c"])
    assert impact["success"] is True
    impacted_names = [f["name"] for f in impact["impacted_functions"]]
    assert "f_b" in impacted_names
    assert "f_a" in impacted_names


def test_json_serializable(simple_chain_files):
    result = build_dependency_graph(simple_chain_files)
    serialized = json.dumps(result)
    deserialized = json.loads(serialized)
    assert deserialized == result

    impact = get_impacted_functions(result, ["f_c"])
    serialized_impact = json.dumps(impact)
    deserialized_impact = json.loads(serialized_impact)
    assert deserialized_impact == impact
