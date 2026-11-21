"""
Intelligent Test Selector for ChangeGuard AI.

Analyzes impact reports and test mappings to select only the relevant pytest
tests for changed and impacted functions, assigns priority tiers, and computes
test reduction metrics.
"""

import os
from typing import Any, Dict, List, Optional, Set, Tuple


PRIORITY_ORDER = {
    "high": 0,
    "medium": 1,
    "module-level": 2
}


def _to_pytest_node_id(test_file: str, qualified_name: str) -> str:
    """
    Format a test file and qualified name into a standard pytest node ID
    using '::' separators.

    Example:
        'tests/test_billing.py', 'test_tax' -> 'tests/test_billing.py::test_tax'
        'tests/test_billing.py', 'TestBilling.test_tax' -> 'tests/test_billing.py::TestBilling::test_tax'
    """
    norm_file = test_file.replace("\\", "/")
    node_part = qualified_name.replace(".", "::")
    return f"{norm_file}::{node_part}"


def select_tests(impact_report: Dict[str, Any], test_mapping: Dict[str, Any]) -> Dict[str, Any]:
    """
    Select relevant pytest tests based on change impact and test mapping.

    Priority logic:
        - High: Tests mapped directly to changed functions.
        - Medium: Tests mapped to transitively impacted functions.
        - Module-level: Tests that import or exercise a module whose changed
          lines could not be assigned to a specific function.

    If a test matches multiple affected functions, it is included only once
    with its highest priority retained.

    Args:
        impact_report: Output dictionary from analyze_code_impact().
        test_mapping: Output dictionary from map_tests_to_code().

    Returns:
        dict: A JSON-compatible dictionary containing:
            - success (bool)
            - selected_tests (list)
            - total_tests_discovered (int)
            - total_tests_selected (int)
            - reduction_percentage (float)
            - pytest_args (list)
            - selection_summary (dict)
            - errors (list)
    """
    errors: List[Dict[str, Any]] = []

    # Validate inputs
    if not isinstance(impact_report, dict):
        return {
            "success": False,
            "selected_tests": [],
            "total_tests_discovered": 0,
            "total_tests_selected": 0,
            "reduction_percentage": 0.0,
            "pytest_args": [],
            "selection_summary": {
                "high_priority_count": 0,
                "medium_priority_count": 0,
                "module_level_count": 0,
                "total_selected": 0,
                "total_discovered": 0
            },
            "errors": [{"error": "Invalid impact_report: expected dictionary"}]
        }

    if not isinstance(test_mapping, dict):
        return {
            "success": False,
            "selected_tests": [],
            "total_tests_discovered": 0,
            "total_tests_selected": 0,
            "reduction_percentage": 0.0,
            "pytest_args": [],
            "selection_summary": {
                "high_priority_count": 0,
                "medium_priority_count": 0,
                "module_level_count": 0,
                "total_selected": 0,
                "total_discovered": 0
            },
            "errors": [{"error": "Invalid test_mapping: expected dictionary"}]
        }

    # Propagate any existing errors from input reports
    for err in impact_report.get("errors", []):
        errors.append(err)
    for err in test_mapping.get("errors", []):
        errors.append(err)

    discovered_tests_list = test_mapping.get("tests", [])
    total_discovered = len(discovered_tests_list)

    # Index discovered tests by their test ID for fast lookup
    tests_by_id: Dict[str, Dict[str, Any]] = {
        t["id"]: t for t in discovered_tests_list if "id" in t
    }

    code_to_tests: Dict[str, List[str]] = test_mapping.get("code_to_tests", {})
    test_to_code: Dict[str, List[str]] = test_mapping.get("test_to_code", {})

    changed_functions = impact_report.get("changed_functions", [])
    impacted_functions = impact_report.get("impacted_functions", [])
    unassigned_changed_lines = impact_report.get("unassigned_changed_lines", [])

    # Map candidate tests: test_internal_id -> {
    #   "priority": "high" | "medium" | "module-level",
    #   "target_functions": set(),
    #   "selection_reason": str,
    #   "test_data": dict
    # }
    candidates: Dict[str, Dict[str, Any]] = {}

    def add_candidate(
        test_internal_id: str,
        priority: str,
        target_func_name: str,
        reason: str
    ) -> None:
        test_data = tests_by_id.get(test_internal_id)
        if not test_data:
            return

        if test_internal_id not in candidates:
            candidates[test_internal_id] = {
                "priority": priority,
                "target_functions": {target_func_name} if target_func_name else set(),
                "selection_reason": reason,
                "test_data": test_data
            }
        else:
            existing = candidates[test_internal_id]
            if target_func_name:
                existing["target_functions"].add(target_func_name)

            # Retain highest priority
            if PRIORITY_ORDER[priority] < PRIORITY_ORDER[existing["priority"]]:
                existing["priority"] = priority
                existing["selection_reason"] = reason

    # 1. High Priority: Tests for changed functions
    for func in changed_functions:
        func_id = func.get("id", "")
        func_name = func.get("name") or func.get("qualified_name") or func_id

        # Find matching tests in code_to_tests
        matching_tests: Set[str] = set()

        if func_id in code_to_tests:
            matching_tests.update(code_to_tests[func_id])
        else:
            # Suffix match if paths differ in prefix
            for code_id, t_ids in code_to_tests.items():
                if code_id.endswith(f":{func.get('qualified_name', '')}") or code_id == func_id:
                    matching_tests.update(t_ids)

        for tid in matching_tests:
            add_candidate(
                test_internal_id=tid,
                priority="high",
                target_func_name=func_name,
                reason=f"Directly tests changed function '{func_name}'"
            )

    # 2. Medium Priority: Tests for impacted functions
    for func in impacted_functions:
        func_id = func.get("id", "")
        func_name = func.get("name") or func.get("qualified_name") or func_id
        func_reason = func.get("reason", "transitive dependency")

        matching_tests = set()
        if func_id in code_to_tests:
            matching_tests.update(code_to_tests[func_id])
        else:
            for code_id, t_ids in code_to_tests.items():
                if code_id.endswith(f":{func.get('qualified_name', '')}") or code_id == func_id:
                    matching_tests.update(t_ids)

        for tid in matching_tests:
            add_candidate(
                test_internal_id=tid,
                priority="medium",
                target_func_name=func_name,
                reason=f"Tests impacted function '{func_name}' ({func_reason})"
            )

    # 3. Module-level Fallback: Unassigned changed lines
    for item in unassigned_changed_lines:
        unassigned_file = item.get("file_path", "")
        if not unassigned_file:
            continue

        norm_unassigned = os.path.normpath(unassigned_file).replace("\\", "/")
        base_mod = os.path.splitext(os.path.basename(norm_unassigned))[0]
        unassigned_lines_count = len(item.get("lines", []))

        module_tests_found = False

        for tid, tdata in tests_by_id.items():
            # Check if test exercises any function from this file
            test_app_funcs = test_to_code.get(tid, [])
            exercises_file = any(
                norm_unassigned in fid or fid.startswith(f"{norm_unassigned}:") or f"/{base_mod}.py:" in fid
                for fid in test_app_funcs
            )

            # Check if test imports this module
            imported_symbols = tdata.get("imported_application_symbols", [])
            imports_module = base_mod in imported_symbols

            # Check test file naming convention
            test_filename = os.path.basename(tdata.get("file_path", ""))
            name_matches = f"test_{base_mod}.py" == test_filename or f"test_{base_mod}" in test_filename

            if exercises_file or imports_module or name_matches:
                module_tests_found = True
                add_candidate(
                    test_internal_id=tid,
                    priority="module-level",
                    target_func_name=f"module:{base_mod}",
                    reason=f"Exercises module '{base_mod}' affected by unassigned changes ({unassigned_lines_count} lines)"
                )

        if not module_tests_found:
            errors.append({
                "file_path": unassigned_file,
                "message": f"No reliable module-level test mapping found for '{unassigned_file}'"
            })

    # Format selected tests
    selected_tests: List[Dict[str, Any]] = []

    for tid, cdata in candidates.items():
        tinfo = cdata["test_data"]
        test_file = tinfo.get("file_path", "")
        qname = tinfo.get("qualified_name", tinfo.get("name", ""))
        pytest_node_id = _to_pytest_node_id(test_file, qname)

        selected_tests.append({
            "test_id": pytest_node_id,
            "test_file": test_file,
            "test_name": tinfo.get("name", ""),
            "target_functions": sorted(list(cdata["target_functions"])),
            "selection_reason": cdata["selection_reason"],
            "priority": cdata["priority"]
        })

    # Deterministic sorting: by priority rank, then test_file, then test_name
    selected_tests.sort(
        key=lambda t: (
            PRIORITY_ORDER[t["priority"]],
            t["test_file"],
            t["test_name"],
            t["test_id"]
        )
    )

    total_selected = len(selected_tests)

    # Calculate reduction percentage
    if total_discovered > 0:
        reduction_percentage = round(
            ((total_discovered - total_selected) / total_discovered) * 100.0,
            2
        )
    else:
        reduction_percentage = 0.0

    pytest_args = [t["test_id"] for t in selected_tests]

    high_count = sum(1 for t in selected_tests if t["priority"] == "high")
    med_count = sum(1 for t in selected_tests if t["priority"] == "medium")
    mod_count = sum(1 for t in selected_tests if t["priority"] == "module-level")

    selection_summary = {
        "high_priority_count": high_count,
        "medium_priority_count": med_count,
        "module_level_count": mod_count,
        "total_selected": total_selected,
        "total_discovered": total_discovered
    }

    return {
        "success": True,
        "selected_tests": selected_tests,
        "total_tests_discovered": total_discovered,
        "total_tests_selected": total_selected,
        "reduction_percentage": reduction_percentage,
        "pytest_args": pytest_args,
        "selection_summary": selection_summary,
        "errors": errors
    }
