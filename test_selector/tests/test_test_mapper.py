"""
Unit tests for Test Mapper (test_selector.test_mapper).
"""

import json
import os
import pytest
from test_selector.test_mapper import (
    discover_test_functions,
    map_tests_to_code
)


@pytest.fixture
def sample_project(tmp_path):
    """
    Creates a sample project with application files and test files:
    - app/billing.py: calculate_tax(), get_discount()
    - app/order.py: create_order()
    - tests/test_billing.py: tests for billing
    """
    app_dir = tmp_path / "app"
    tests_dir = tmp_path / "tests"
    app_dir.mkdir()
    tests_dir.mkdir()

    billing_code = """
def calculate_tax(amount):
    return amount * 0.18

def get_discount(tier):
    return 0.10 if tier == 'gold' else 0.0
"""
    order_code = """
from app.billing import calculate_tax

def create_order(price):
    tax = calculate_tax(price)
    return price + tax
"""
    (app_dir / "billing.py").write_text(billing_code, encoding="utf-8")
    (app_dir / "order.py").write_text(order_code, encoding="utf-8")

    test_billing_code = """
from app.billing import calculate_tax, get_discount
import pytest

def test_calculate_tax_basic():
    print("Testing tax calculation")
    assert calculate_tax(100) == 18.0

def test_get_discount():
    assert get_discount('gold') == 0.10
"""
    (tests_dir / "test_billing.py").write_text(test_billing_code, encoding="utf-8")

    return {
        "app_files": [str(app_dir / "billing.py"), str(app_dir / "order.py")],
        "test_files": [str(tests_dir / "test_billing.py")],
        "tmp_path": tmp_path
    }


def test_simple_test_calling_app_function(sample_project):
    res = map_tests_to_code(sample_project["test_files"], sample_project["app_files"])
    assert res["success"] is True
    assert len(res["tests"]) == 2

    # Verify test_to_code mapping
    test_tax_id = [t["id"] for t in res["tests"] if "test_calculate_tax_basic" in t["name"]][0]
    called_app_funcs = res["test_to_code"][test_tax_id]
    assert any("billing.py:calculate_tax" in fid for fid in called_app_funcs)

    # Verify code_to_tests reverse mapping
    tax_app_id = [fid for fid in res["code_to_tests"].keys() if "billing.py:calculate_tax" in fid][0]
    assert test_tax_id in res["code_to_tests"][tax_app_id]


def test_aliased_imports(tmp_path):
    app_code = """
def process_data(data):
    return data.strip()
"""
    test_code = """
from app_mod import process_data as clean_data
import app_mod as app

def test_aliased_from_import():
    assert clean_data("  hello  ") == "hello"

def test_aliased_module_import():
    assert app.process_data(" world ") == "world"
"""
    f_app = tmp_path / "app_mod.py"
    f_test = tmp_path / "test_aliased.py"
    f_app.write_text(app_code, encoding="utf-8")
    f_test.write_text(test_code, encoding="utf-8")

    res = map_tests_to_code([str(f_test)], [str(f_app)])
    assert res["success"] is True
    assert len(res["tests"]) == 2

    for t in res["tests"]:
        mapped = res["test_to_code"][t["id"]]
        assert any("app_mod.py:process_data" in fid for fid in mapped)


def test_multiple_app_functions_called_by_one_test(tmp_path):
    app_code = """
def step_one(): return 1
def step_two(): return 2
"""
    test_code = """
from app_flow import step_one, step_two

def test_pipeline():
    a = step_one()
    b = step_two()
    assert a + b == 3
"""
    f_app = tmp_path / "app_flow.py"
    f_test = tmp_path / "test_flow.py"
    f_app.write_text(app_code, encoding="utf-8")
    f_test.write_text(test_code, encoding="utf-8")

    res = map_tests_to_code([str(f_test)], [str(f_app)])
    assert res["success"] is True

    test_id = res["tests"][0]["id"]
    mapped_funcs = res["test_to_code"][test_id]
    assert len(mapped_funcs) == 2
    assert any("step_one" in fid for fid in mapped_funcs)
    assert any("step_two" in fid for fid in mapped_funcs)


def test_multiple_test_files(tmp_path):
    app_code = "def core_func(): return True"
    test1_code = "from myapp import core_func\ndef test_first(): assert core_func()"
    test2_code = "from myapp import core_func\ndef test_second(): assert core_func()"

    f_app = tmp_path / "myapp.py"
    f_t1 = tmp_path / "test_one.py"
    f_t2 = tmp_path / "test_two.py"

    f_app.write_text(app_code, encoding="utf-8")
    f_t1.write_text(test1_code, encoding="utf-8")
    f_t2.write_text(test2_code, encoding="utf-8")

    res = map_tests_to_code([str(f_t1), str(f_t2)], [str(f_app)])
    assert res["success"] is True
    assert len(res["tests"]) == 2

    app_id = [k for k in res["code_to_tests"].keys() if "core_func" in k][0]
    # Both tests should be mapped to the core application function
    assert len(res["code_to_tests"][app_id]) == 2


def test_test_methods_inside_class(tmp_path):
    app_code = """
def auth_user(): return True
def logout_user(): return True
"""
    test_code = """
from auth import auth_user, logout_user

class TestAuthentication:
    def test_login(self):
        assert auth_user()

    def test_logout(self):
        assert logout_user()

    def helper_setup(self):
        pass  # Not a test function
"""
    f_app = tmp_path / "auth.py"
    f_test = tmp_path / "test_auth.py"
    f_app.write_text(app_code, encoding="utf-8")
    f_test.write_text(test_code, encoding="utf-8")

    discovered = discover_test_functions([str(f_test)])
    assert discovered["success"] is True
    # helper_setup should not be discovered as a test
    assert len(discovered["tests"]) == 2
    test_names = [t["name"] for t in discovered["tests"]]
    assert "test_login" in test_names
    assert "test_logout" in test_names
    assert "helper_setup" not in test_names

    res = map_tests_to_code([str(f_test)], [str(f_app)])
    assert res["success"] is True
    login_id = [t["id"] for t in res["tests"] if "test_login" in t["name"]][0]
    assert any("auth_user" in fid for fid in res["test_to_code"][login_id])


def test_helper_functions_called_by_test_functions(tmp_path):
    app_code = "def db_insert(x): return x"
    test_code = """
from db import db_insert

def create_record(val):
    return db_insert(val)

def test_via_helper():
    res = create_record("item1")
    assert res == "item1"
"""
    f_app = tmp_path / "db.py"
    f_test = tmp_path / "test_db.py"
    f_app.write_text(app_code, encoding="utf-8")
    f_test.write_text(test_code, encoding="utf-8")

    res = map_tests_to_code([str(f_test)], [str(f_app)])
    assert res["success"] is True
    test_id = res["tests"][0]["id"]
    # The test calls create_record() which calls db_insert()
    assert any("db_insert" in fid for fid in res["test_to_code"][test_id])


def test_missing_test_files():
    res = discover_test_functions(["non_existent_test_123.py"])
    assert res["success"] is False
    assert len(res["errors"]) == 1
    assert "File not found" in res["errors"][0]["error"]

    res_map = map_tests_to_code(["non_existent_test_123.py"], [])
    assert res_map["success"] is False
    assert len(res_map["errors"]) >= 1


def test_invalid_python_syntax(tmp_path):
    broken_test = tmp_path / "broken_test.py"
    broken_test.write_text("def test_broken(\n    return 42", encoding="utf-8")

    discovered = discover_test_functions([str(broken_test)])
    assert discovered["success"] is False
    assert len(discovered["errors"]) == 1
    assert "Syntax error" in discovered["errors"][0]["error"]


def test_unrelated_external_and_builtin_calls(tmp_path):
    app_code = "def do_work(): return 1"
    test_code = """
import os, sys, json, math
from worker import do_work

def test_builtins_and_externals():
    # Built-in and library calls should not create mappings
    len([1, 2, 3])
    print("Log statement")
    os.path.join("a", "b")
    math.sqrt(16)
    do_work()
"""
    f_app = tmp_path / "worker.py"
    f_test = tmp_path / "test_worker.py"
    f_app.write_text(app_code, encoding="utf-8")
    f_test.write_text(test_code, encoding="utf-8")

    res = map_tests_to_code([str(f_test)], [str(f_app)])
    assert res["success"] is True
    test_id = res["tests"][0]["id"]
    mapped = res["test_to_code"][test_id]

    # Only do_work should be mapped, NOT len, print, os.path.join, math.sqrt
    assert len(mapped) == 1
    assert any("worker.py:do_work" in fid for fid in mapped)


def test_json_serializable(sample_project):
    res = map_tests_to_code(sample_project["test_files"], sample_project["app_files"])
    serialized = json.dumps(res)
    deserialized = json.loads(serialized)
    assert deserialized == res
