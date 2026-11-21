"""
Unit tests for Intelligent Test Selector (test_selector.selector).
"""

import json
import pytest
from test_selector.selector import select_tests


@pytest.fixture
def sample_test_mapping():
    return {
        "success": True,
        "tests": [
            {
                "id": "tests/test_billing.py:test_calculate_tax",
                "name": "test_calculate_tax",
                "qualified_name": "test_calculate_tax",
                "file_path": "tests/test_billing.py",
                "start_line": 5,
                "end_line": 8,
                "called_function_names": ["calculate_tax"],
                "imported_application_symbols": ["calculate_tax"]
            },
            {
                "id": "tests/test_order.py:test_process_order",
                "name": "test_process_order",
                "qualified_name": "test_process_order",
                "file_path": "tests/test_order.py",
                "start_line": 10,
                "end_line": 15,
                "called_function_names": ["process_order"],
                "imported_application_symbols": ["process_order"]
            },
            {
                "id": "tests/test_order.py:TestOrder.test_order_flow",
                "name": "test_order_flow",
                "qualified_name": "TestOrder.test_order_flow",
                "file_path": "tests/test_order.py",
                "start_line": 20,
                "end_line": 25,
                "called_function_names": ["calculate_tax", "process_order"],
                "imported_application_symbols": ["calculate_tax", "process_order"]
            },
            {
                "id": "tests/test_unrelated.py:test_unrelated_feature",
                "name": "test_unrelated_feature",
                "qualified_name": "test_unrelated_feature",
                "file_path": "tests/test_unrelated.py",
                "start_line": 5,
                "end_line": 8,
                "called_function_names": ["unrelated_feature"],
                "imported_application_symbols": ["unrelated_feature"]
            }
        ],
        "code_to_tests": {
            "app/billing.py:calculate_tax": [
                "tests/test_billing.py:test_calculate_tax",
                "tests/test_order.py:TestOrder.test_order_flow"
            ],
            "app/order.py:process_order": [
                "tests/test_order.py:test_process_order",
                "tests/test_order.py:TestOrder.test_order_flow"
            ],
            "app/unrelated.py:unrelated_feature": [
                "tests/test_unrelated.py:test_unrelated_feature"
            ]
        },
        "test_to_code": {
            "tests/test_billing.py:test_calculate_tax": ["app/billing.py:calculate_tax"],
            "tests/test_order.py:test_process_order": ["app/order.py:process_order"],
            "tests/test_order.py:TestOrder.test_order_flow": [
                "app/billing.py:calculate_tax",
                "app/order.py:process_order"
            ],
            "tests/test_unrelated.py:test_unrelated_feature": ["app/unrelated.py:unrelated_feature"]
        },
        "errors": []
    }


def test_direct_selection_changed_functions(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [
            {
                "id": "app/billing.py:calculate_tax",
                "name": "calculate_tax",
                "qualified_name": "calculate_tax",
                "file_path": "app/billing.py"
            }
        ],
        "impacted_functions": [],
        "unassigned_changed_lines": [],
        "errors": []
    }

    res = select_tests(impact_report, sample_test_mapping)
    assert res["success"] is True

    selected_ids = [t["test_id"] for t in res["selected_tests"]]
    assert "tests/test_billing.py::test_calculate_tax" in selected_ids
    assert "tests/test_order.py::TestOrder::test_order_flow" in selected_ids
    assert "tests/test_unrelated.py::test_unrelated_feature" not in selected_ids

    # All tests for calculate_tax should have high priority
    tax_test = [t for t in res["selected_tests"] if t["test_name"] == "test_calculate_tax"][0]
    assert tax_test["priority"] == "high"
    assert "Directly tests changed function" in tax_test["selection_reason"]


def test_medium_priority_impacted_functions(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [],
        "impacted_functions": [
            {
                "id": "app/order.py:process_order",
                "name": "process_order",
                "qualified_name": "process_order",
                "file_path": "app/order.py",
                "reason": "Directly calls 'calculate_tax'"
            }
        ],
        "unassigned_changed_lines": [],
        "errors": []
    }

    res = select_tests(impact_report, sample_test_mapping)
    assert res["success"] is True

    order_test = [t for t in res["selected_tests"] if t["test_name"] == "test_process_order"][0]
    assert order_test["priority"] == "medium"
    assert "Tests impacted function" in order_test["selection_reason"]


def test_test_mapped_to_multiple_functions_retains_highest_priority(sample_test_mapping):
    # TestOrder.test_order_flow calls calculate_tax (changed -> high) AND process_order (impacted -> medium)
    impact_report = {
        "success": True,
        "changed_functions": [
            {"id": "app/billing.py:calculate_tax", "name": "calculate_tax"}
        ],
        "impacted_functions": [
            {"id": "app/order.py:process_order", "name": "process_order"}
        ],
        "unassigned_changed_lines": [],
        "errors": []
    }

    res = select_tests(impact_report, sample_test_mapping)
    assert res["success"] is True

    flow_test = [t for t in res["selected_tests"] if "TestOrder" in t["test_id"]][0]
    # Retains high priority over medium
    assert flow_test["priority"] == "high"
    # Should only appear once
    flow_ids = [t["test_id"] for t in res["selected_tests"] if "TestOrder" in t["test_id"]]
    assert len(flow_ids) == 1


def test_unrelated_tests_excluded(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [
            {"id": "app/billing.py:calculate_tax", "name": "calculate_tax"}
        ],
        "impacted_functions": [],
        "unassigned_changed_lines": [],
        "errors": []
    }

    res = select_tests(impact_report, sample_test_mapping)
    selected_names = [t["test_name"] for t in res["selected_tests"]]
    assert "test_unrelated_feature" not in selected_names


def test_module_level_fallback(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [],
        "impacted_functions": [],
        "unassigned_changed_lines": [
            {"file_path": "app/billing.py", "lines": [2, 3]}
        ],
        "errors": []
    }

    res = select_tests(impact_report, sample_test_mapping)
    assert res["success"] is True

    selected_ids = [t["test_id"] for t in res["selected_tests"]]
    # Should select tests related to billing
    assert "tests/test_billing.py::test_calculate_tax" in selected_ids

    mod_test = [t for t in res["selected_tests"] if t["test_name"] == "test_calculate_tax"][0]
    assert mod_test["priority"] == "module-level"
    assert "Exercises module 'billing'" in mod_test["selection_reason"]


def test_unknown_module_mapping_reported_safely(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [],
        "impacted_functions": [],
        "unassigned_changed_lines": [
            {"file_path": "unknown/obscure_config.py", "lines": [10]}
        ],
        "errors": []
    }

    res = select_tests(impact_report, sample_test_mapping)
    assert res["success"] is True
    assert res["selected_tests"] == []

    # Should report in errors that no reliable mapping was found
    assert len(res["errors"]) >= 1
    err_msgs = [e.get("message", "") for e in res["errors"]]
    assert any("No reliable module-level test mapping found" in m for m in err_msgs)


def test_empty_impact_report(sample_test_mapping):
    empty_report = {
        "success": True,
        "changed_functions": [],
        "impacted_functions": [],
        "unassigned_changed_lines": [],
        "errors": []
    }
    res = select_tests(empty_report, sample_test_mapping)
    assert res["success"] is True
    assert res["selected_tests"] == []
    assert res["total_tests_selected"] == 0
    assert res["reduction_percentage"] == 100.0


def test_zero_discovered_tests():
    impact_report = {
        "success": True,
        "changed_functions": [{"id": "app.py:func", "name": "func"}],
        "impacted_functions": [],
        "unassigned_changed_lines": []
    }
    empty_mapping = {
        "success": True,
        "tests": [],
        "code_to_tests": {},
        "test_to_code": {},
        "errors": []
    }
    res = select_tests(impact_report, empty_mapping)
    assert res["success"] is True
    assert res["total_tests_discovered"] == 0
    assert res["total_tests_selected"] == 0
    assert res["reduction_percentage"] == 0.0


def test_missing_or_malformed_mapping_data():
    impact_report = {"success": True}
    res1 = select_tests(impact_report, None)
    assert res1["success"] is False
    assert len(res1["errors"]) >= 1

    res2 = select_tests(None, {})
    assert res2["success"] is False
    assert len(res2["errors"]) >= 1


def test_correct_pytest_node_ids(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [
            {"id": "app/billing.py:calculate_tax", "name": "calculate_tax"}
        ],
        "impacted_functions": [],
        "unassigned_changed_lines": []
    }
    res = select_tests(impact_report, sample_test_mapping)
    for test in res["selected_tests"]:
        # Pytest node IDs must contain '::'
        assert "::" in test["test_id"]
        if "TestOrder" in test["test_id"]:
            assert "tests/test_order.py::TestOrder::test_order_flow" == test["test_id"]


def test_correct_reduction_percentage(sample_test_mapping):
    # Total discovered = 4 tests. Select 1 test -> reduction = ((4 - 1) / 4) * 100 = 75.0%
    impact_report = {
        "success": True,
        "changed_functions": [],
        "impacted_functions": [],
        "unassigned_changed_lines": [
            {"file_path": "app/billing.py", "lines": [1]}
        ]
    }
    # Let's map only test_calculate_tax to billing
    mapping = {
        "success": True,
        "tests": sample_test_mapping["tests"],
        "test_to_code": {
            "tests/test_billing.py:test_calculate_tax": ["app/billing.py:tax"]
        },
        "code_to_tests": {},
        "errors": []
    }
    res = select_tests(impact_report, mapping)
    assert res["total_tests_discovered"] == 4
    assert res["total_tests_selected"] == 1
    assert res["reduction_percentage"] == 75.0


def test_json_serializable(sample_test_mapping):
    impact_report = {
        "success": True,
        "changed_functions": [
            {"id": "app/billing.py:calculate_tax", "name": "calculate_tax"}
        ],
        "impacted_functions": [],
        "unassigned_changed_lines": []
    }
    res = select_tests(impact_report, sample_test_mapping)
    serialized = json.dumps(res)
    deserialized = json.loads(serialized)
    assert deserialized == res
