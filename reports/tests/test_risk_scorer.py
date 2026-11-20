"""
Unit tests for the Risk Scoring module of ChangeGuard AI.

Validates deterministic risk score calculation, factor attribution,
safety overrides, coverage gap detection, caller distance weighting,
edge case handling, and JSON serialization.
"""

import json
import pytest

from reports.risk_scorer import calculate_risk_score


def _make_impact(
    changed_funcs=None,
    impacted_funcs=None,
    unassigned_lines=None,
    changed_files=None
):
    return {
        "success": True,
        "changed_files": changed_files or [{"file_path": "billing.py", "change_type": "modified"}],
        "changed_functions": changed_funcs or [],
        "impacted_functions": impacted_funcs or [],
        "unassigned_changed_lines": unassigned_lines or [],
        "errors": [],
        "summary": {}
    }


def _make_selection(selected_tests=None, total_discovered=10):
    tests = selected_tests or []
    return {
        "success": True,
        "total_tests_discovered": total_discovered,
        "total_tests_selected": len(tests),
        "reduction_percentage": 50.0,
        "pytest_args": [t.get("test_id", "") for t in tests],
        "selected_tests": tests,
        "selection_summary": {}
    }


def _make_execution(status="passed", passed=1, failed=0, skipped=0, exit_code=0):
    return {
        "success": (status == "passed" and failed == 0),
        "status": status,
        "exit_code": exit_code,
        "execution_time": 0.12,
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": passed + failed + skipped
        },
        "failure_details": [{"test": "test_x", "message": "fail"}] if failed > 0 else [],
        "stdout": "1 passed",
        "stderr": "",
        "message": f"Execution status: {status}"
    }


class TestRiskScoringBasics:
    """Tests for core scoring formula and levels."""

    def test_low_risk_scenario(self):
        """Verify small change with full test coverage and passing tests is LOW risk."""
        impact = _make_impact(
            changed_funcs=[
                {"id": "billing.py:calc_tax", "name": "calc_tax", "file_path": "billing.py"}
            ]
        )
        selection = _make_selection(
            selected_tests=[
                {
                    "test_id": "tests/test_billing.py::test_calc_tax",
                    "target_functions": ["calc_tax"]
                }
            ]
        )
        execution = _make_execution(status="passed", passed=1, failed=0)

        result = calculate_risk_score(impact, selection, execution)

        assert result["score"] <= 30
        assert result["level"] == "LOW"
        assert result["verification_status"] == "VERIFIED"
        assert len(result["safety_overrides"]) == 0
        assert result["metrics"]["uncovered_changed_function_count"] == 0
        assert "SAFE TO DEPLOY" in result["recommendation"]

    def test_medium_risk_scenario(self):
        """Verify moderate blast radius and partial test coverage results in MEDIUM risk."""
        impact = _make_impact(
            changed_funcs=[
                {"id": "billing.py:calc_tax", "name": "calc_tax", "file_path": "billing.py"},
                {"id": "billing.py:calc_discount", "name": "calc_discount", "file_path": "billing.py"},
                {"id": "billing.py:apply_coupon", "name": "apply_coupon", "file_path": "billing.py"}
            ],
            impacted_funcs=[
                {"id": "orders.py:submit", "name": "submit", "distance": 1, "file_path": "orders.py"},
                {"id": "checkout.py:pay", "name": "pay", "distance": 1, "file_path": "checkout.py"},
                {"id": "api.py:order_endpoint", "name": "order_endpoint", "distance": 2, "file_path": "api.py"}
            ],
            unassigned_lines=[{"file_path": "billing.py", "lines": list(range(1, 11))}]  # 10 lines -> +2
        )
        # 3 changed (+15), 2 direct (+6), 1 transitive (+2), 10 unassigned lines (+2) -> Section A = 25 pts
        # Tests cover 2 of the 3 functions (1 uncovered -> +10) -> Section B = 10 pts
        # Execution passed -> Section C = 0 pts
        # Base score = 25 + 10 + 0 = 35. Safety override for uncovered changed func -> min 35.
        selection = _make_selection(
            selected_tests=[
                {"test_id": "test_1", "target_functions": ["calc_tax"]},
                {"test_id": "test_2", "target_functions": ["calc_discount"]}
            ]
        )
        execution = _make_execution(status="passed", passed=2, failed=0)

        result = calculate_risk_score(impact, selection, execution)

        assert 31 <= result["score"] <= 69
        assert result["level"] == "MEDIUM"
        assert result["metrics"]["uncovered_changed_function_count"] == 1
        assert "PROCEED WITH CAUTION" in result["recommendation"]

    def test_high_risk_scenario(self):
        """Verify large blast radius, zero tests, or failures result in HIGH risk."""
        impact = _make_impact(
            changed_funcs=[
                {"id": f"core.py:func_{i}", "name": f"func_{i}", "file_path": "core.py"}
                for i in range(4)  # 4 * 5 = 20 -> capped at 15
            ],
            impacted_funcs=[
                {"id": f"caller.py:c_{i}", "name": f"c_{i}", "distance": 1, "file_path": "caller.py"}
                for i in range(4)  # 4 * 3 = 12 -> capped at 10
            ] + [
                {"id": f"deep.py:d_{i}", "name": f"d_{i}", "distance": 2, "file_path": "deep.py"}
                for i in range(3)  # 3 * 2 = 6 -> capped at 5
            ],
            unassigned_lines=[{"file_path": "core.py", "lines": list(range(1, 30))}]  # 29 // 5 = 5 (max 5)
        )
        # Section A: 15 + 10 + 5 + 5 = 35 pts (max)
        # 0 tests selected: Section B = 20 (uncovered) + 15 (zero tests) = 35 -> capped at 25 pts
        # Execution skipped: Section C = 10 pts
        # Total = 35 + 25 + 10 = 70 pts -> HIGH
        selection = _make_selection(selected_tests=[])
        execution = _make_execution(status="skipped", passed=0, failed=0, skipped=0)

        result = calculate_risk_score(impact, selection, execution)

        assert result["score"] >= 70
        assert result["level"] == "HIGH"
        assert "DO NOT DEPLOY" in result["recommendation"]


class TestHardSafetyOverrides:
    """Tests for hard safety override rules."""

    def test_failed_test_safety_override(self):
        """Verify that any test failure forces score to at least 75 (HIGH)."""
        # Small change (+5), covered (+0), but 1 test failed
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "test_foo", "target_functions": ["foo"]}]
        )
        execution = _make_execution(status="failed", passed=0, failed=1, exit_code=1)

        result = calculate_risk_score(impact, selection, execution)

        assert result["score"] >= 75
        assert result["level"] == "HIGH"
        assert result["verification_status"] == "FAILED"
        assert any("75" in override for override in result["safety_overrides"])
        assert "DO NOT DEPLOY" in result["recommendation"]

    def test_timeout_safety_override(self):
        """Verify that timeout forces score to at least 80 (HIGH)."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "test_foo", "target_functions": ["foo"]}]
        )
        execution = _make_execution(status="timeout", passed=0, failed=0, exit_code=-1)

        result = calculate_risk_score(impact, selection, execution)

        assert result["score"] >= 80
        assert result["level"] == "HIGH"
        assert result["verification_status"] == "TIMEOUT"
        assert any("80" in override for override in result["safety_overrides"])

    def test_execution_error_safety_override(self):
        """Verify that execution error forces score to at least 80 (HIGH)."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "test_foo", "target_functions": ["foo"]}]
        )
        execution = _make_execution(status="error", passed=0, failed=0, exit_code=-1)

        result = calculate_risk_score(impact, selection, execution)

        assert result["score"] >= 80
        assert result["level"] == "HIGH"
        assert result["verification_status"] == "ERROR"
        assert any("80" in override for override in result["safety_overrides"])

    def test_uncovered_changed_functions_override(self):
        """Verify that changed functions with zero tests cannot be LOW risk (min 35)."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        # No test mapped to foo, but a test was selected for something else
        selection = _make_selection(
            selected_tests=[{"test_id": "test_other", "target_functions": ["other_func"]}]
        )
        execution = _make_execution(status="passed", passed=1, failed=0)

        result = calculate_risk_score(impact, selection, execution)

        # Base: changed (+5) + uncovered (+10) + pass (+0) = 15 -> overridden to 35
        assert result["score"] >= 35
        assert result["level"] in ("MEDIUM", "HIGH")
        assert any("35" in override for override in result["safety_overrides"])


class TestCoverageAndCallerCalculations:
    """Tests for coverage gaps, caller distances, and unassigned lines."""

    def test_no_selected_tests_penalty(self):
        """Verify +15 penalty when code changed but 0 tests were selected."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        selection = _make_selection(selected_tests=[])
        execution = _make_execution(status="skipped", passed=0, failed=0)

        result = calculate_risk_score(impact, selection, execution)

        zero_tests_factor = next(f for f in result["factors"] if f["name"] == "Zero Tests Selected")
        assert zero_tests_factor["points"] == 15

    def test_unassigned_changed_lines(self):
        """Verify unassigned changed lines earn +1 per 5 lines up to max 5."""
        impact = _make_impact(
            changed_funcs=[],
            unassigned_lines=[
                {"file_path": "globals.py", "lines": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]}  # 14 lines -> 2 pts
            ]
        )
        selection = _make_selection(selected_tests=[])
        execution = _make_execution(status="skipped")

        result = calculate_risk_score(impact, selection, execution)

        unassigned_factor = next(f for f in result["factors"] if f["name"] == "Unassigned Changed Lines")
        assert unassigned_factor["points"] == 2
        assert result["metrics"]["unassigned_line_count"] == 14

    def test_direct_and_transitive_callers_weighting(self):
        """Verify direct callers earn +3 (max 10) and transitive earn +2 (max 5)."""
        impact = _make_impact(
            changed_funcs=[],
            impacted_funcs=[
                {"id": "d1", "distance": 1},
                {"id": "d2", "distance": 1},
                {"id": "t1", "distance": 2},
                {"id": "t2", "distance": 3}
            ]
        )
        selection = _make_selection(selected_tests=[])
        execution = _make_execution(status="skipped")

        result = calculate_risk_score(impact, selection, execution)

        direct_factor = next(f for f in result["factors"] if f["name"] == "Direct Callers")
        assert direct_factor["points"] == 6  # 2 * 3 = 6
        assert result["metrics"]["direct_caller_count"] == 2

        transitive_factor = next(f for f in result["factors"] if f["name"] == "Transitive Callers")
        assert transitive_factor["points"] == 4  # 2 * 2 = 4
        assert result["metrics"]["transitive_caller_count"] == 2

    def test_duplicate_function_ids_deduplication(self):
        """Verify duplicate function IDs in input are properly deduplicated."""
        impact = _make_impact(
            changed_funcs=[
                {"id": "mod.py:foo", "name": "foo", "file_path": "mod.py"},
                {"id": "mod.py:foo", "name": "foo", "file_path": "mod.py"},  # Duplicate
                {"id": "mod.py:bar", "name": "bar", "file_path": "mod.py"}
            ],
            impacted_funcs=[
                {"id": "mod.py:foo", "name": "foo", "distance": 1},  # Overlaps with changed func!
                {"id": "mod.py:caller1", "name": "caller1", "distance": 1},
                {"id": "mod.py:caller1", "name": "caller1", "distance": 1}  # Duplicate
            ]
        )
        selection = _make_selection(
            selected_tests=[
                {"test_id": "test_1", "target_functions": ["foo", "bar"]}
            ]
        )
        execution = _make_execution(status="passed", passed=1)

        result = calculate_risk_score(impact, selection, execution)

        # 2 unique changed functions (foo, bar)
        assert result["metrics"]["changed_function_count"] == 2
        # 1 unique impacted function (caller1; foo excluded because already changed)
        assert result["metrics"]["impacted_function_count"] == 1


class TestEdgeCasesAndSafetyRules:
    """Tests for edge cases, malformed input, and status verification."""

    def test_missing_or_malformed_input(self):
        """Verify missing or non-dict input returns UNCERTAIN without crashing."""
        for invalid_input in [None, "invalid", 123, []]:
            res = calculate_risk_score(invalid_input, {}, {})  # type: ignore
            assert res["verification_status"] == "UNCERTAIN"
            assert res["score"] == 50
            assert "missing or malformed" in res["safety_overrides"][0].lower()

    def test_skipped_execution_not_treated_as_passed(self):
        """Verify skipped execution is penalized with +10 and not marked VERIFIED."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "t1", "target_functions": ["foo"]}]
        )
        execution = _make_execution(status="skipped", passed=0, skipped=1)

        result = calculate_risk_score(impact, selection, execution)

        assert result["verification_status"] == "SKIPPED"
        exec_factor = next(f for f in result["factors"] if f["name"] == "Test Execution")
        assert exec_factor["points"] == 10

    def test_status_passed_with_failures_not_trusted(self):
        """Verify status='passed' with failed > 0 is treated as failed."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "t1", "target_functions": ["foo"]}]
        )
        # Buggy/dishonest runner claiming 'passed' but failed=1
        execution = {
            "status": "passed",
            "summary": {"passed": 2, "failed": 1, "skipped": 0, "total": 3}
        }

        result = calculate_risk_score(impact, selection, execution)

        assert result["verification_status"] == "FAILED"
        assert result["score"] >= 75
        assert result["level"] == "HIGH"

    def test_score_never_exceeds_100(self):
        """Verify that cumulative scores and overrides never exceed 100."""
        impact = _make_impact(
            changed_funcs=[{"id": f"f_{i}", "name": f"f_{i}"} for i in range(10)],
            impacted_funcs=[{"id": f"c_{i}", "distance": 1} for i in range(10)],
            unassigned_lines=[{"lines": list(range(100))}]
        )
        selection = _make_selection(selected_tests=[])
        execution = _make_execution(status="error", exit_code=-1)

        result = calculate_risk_score(impact, selection, execution)

        assert result["score"] <= 100
        assert result["level"] == "HIGH"

    def test_status_passed_with_zero_executed_tests_is_unverified(self):
        """Verify status='passed' with passed=0 and total=0 is UNVERIFIED, not VERIFIED."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "t1", "target_functions": ["foo"]}]
        )
        execution = {
            "status": "passed",
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "total": 0
            }
        }

        result = calculate_risk_score(impact, selection, execution)

        assert result["verification_status"] == "UNVERIFIED"
        assert result["verification_status"] != "VERIFIED"
        exec_factor = next(f for f in result["factors"] if f["name"] == "Test Execution")
        assert exec_factor["points"] == 10

    def test_empty_execution_result_is_unverified(self):
        """Verify empty execution dict {} and missing status are both UNVERIFIED, not VERIFIED."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo", "file_path": "a.py"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "t1", "target_functions": ["foo"]}]
        )

        for empty_exec in [{}, {"status": ""}]:
            result = calculate_risk_score(impact, selection, empty_exec)

            assert result["verification_status"] != "VERIFIED", (
                f"Expected UNVERIFIED but got {result['verification_status']} for execution_result={empty_exec!r}"
            )
            assert result["verification_status"] == "UNVERIFIED", (
                f"Expected UNVERIFIED but got {result['verification_status']} for execution_result={empty_exec!r}"
            )
            exec_factor = next(f for f in result["factors"] if f["name"] == "Test Execution")
            assert exec_factor["points"] == 10, (
                f"Expected 10 pts but got {exec_factor['points']} for execution_result={empty_exec!r}"
            )

    def test_json_serialization(self):
        """Verify output dictionary is strictly JSON serializable."""
        impact = _make_impact(
            changed_funcs=[{"id": "a.py:foo", "name": "foo"}]
        )
        selection = _make_selection(
            selected_tests=[{"test_id": "t1", "target_functions": ["foo"]}]
        )
        execution = _make_execution(status="passed")

        result = calculate_risk_score(impact, selection, execution)

        dumped = json.dumps(result)
        assert isinstance(dumped, str)
        loaded = json.loads(dumped)
        assert loaded["score"] == result["score"]
        assert loaded["level"] == result["level"]
        assert isinstance(loaded["factors"], list)
        assert isinstance(loaded["metrics"], dict)
