"""
Unit tests for the ChangeGuard AI Report Generator.

Covers report generation, risk scoring integration, evidence derivation,
error aggregation, Markdown formatting, JSON serialization, and edge cases.
"""

import json
import pytest

from reports.report_generator import generate_impact_report, format_markdown_report


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

def _impact(
    changed_funcs=None,
    impacted_funcs=None,
    unassigned_lines=None,
    changed_files=None,
    errors=None,
    success=True
):
    cf = changed_funcs or []
    return {
        "success": success,
        "changed_files": changed_files or [
            {"file_path": "billing.py", "change_type": "modified",
             "added_lines_count": 5, "deleted_lines_count": 2}
        ],
        "changed_functions": cf,
        "impacted_functions": impacted_funcs or [],
        "unassigned_changed_lines": unassigned_lines or [],
        "errors": errors or [],
        "summary": {
            "changed_files_count": len(changed_files or [1]),
            "changed_functions_count": len(cf),
            "impacted_functions_count": len(impacted_funcs or []),
            "unassigned_lines_count": sum(
                len(u.get("lines", [])) for u in (unassigned_lines or [])
            ),
            "errors_count": len(errors or [])
        }
    }


def _selection(selected_tests=None, total_discovered=10, errors=None):
    tests = selected_tests or []
    h = sum(1 for t in tests if t.get("priority") == "high")
    m = sum(1 for t in tests if t.get("priority") == "medium")
    ml = sum(1 for t in tests if t.get("priority") == "module-level")
    return {
        "success": True,
        "total_tests_discovered": total_discovered,
        "total_tests_selected": len(tests),
        "reduction_percentage": round(
            ((total_discovered - len(tests)) / total_discovered) * 100.0, 2
        ) if total_discovered else 0.0,
        "pytest_args": [t.get("test_id", "") for t in tests],
        "selected_tests": tests,
        "selection_summary": {
            "high_priority_count": h,
            "medium_priority_count": m,
            "module_level_count": ml,
            "total_selected": len(tests),
            "total_discovered": total_discovered
        },
        "errors": errors or []
    }


def _run_tests_result(status="passed", passed=1, failed=0, skipped=0, exit_code=0,
                      failure_details=None):
    """Flat run_tests() output shape."""
    return {
        "success": status == "passed" and failed == 0,
        "status": status,
        "exit_code": exit_code,
        "execution_time": 0.25,
        "summary": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "total": passed + failed + skipped
        },
        "failure_details": failure_details or ([{"test": "t", "message": "fail"}] if failed else []),
        "stdout": "1 passed in 0.25s",
        "stderr": "",
        "message": f"Status: {status}"
    }


def _run_selected_tests_result(status="passed", passed=1, failed=0, skipped=0,
                                exit_code=0, failure_details=None, selected_tests=None):
    """Nested run_selected_tests() output shape."""
    exec_inner = _run_tests_result(status, passed, failed, skipped, exit_code, failure_details)
    return {
        "success": exec_inner["success"],
        "status": status,
        "selection": {
            "total_tests_discovered": 10,
            "total_tests_selected": len(selected_tests or []),
            "reduction_percentage": 50.0,
            "pytest_args": [],
            "selected_tests": selected_tests or []
        },
        "execution": exec_inner
    }


CHANGED_FUNC_A = {
    "id": "billing.py:calc_tax",
    "name": "calc_tax",
    "qualified_name": "calc_tax",
    "file_path": "billing.py",
    "start_line": 10,
    "end_line": 20,
    "function_type": "function",
    "changed_lines": [12, 15]
}

CHANGED_FUNC_B = {
    "id": "billing.py:apply_coupon",
    "name": "apply_coupon",
    "qualified_name": "apply_coupon",
    "file_path": "billing.py",
    "start_line": 25,
    "end_line": 35,
    "function_type": "function",
    "changed_lines": [27]
}

IMPACTED_FUNC = {
    "id": "orders.py:submit_order",
    "name": "submit_order",
    "qualified_name": "submit_order",
    "file_path": "orders.py",
    "function_type": "function",
    "start_line": 5,
    "end_line": 20,
    "reason": "Calls changed function 'calc_tax'",
    "distance": 1
}

IMPACTED_TRANSITIVE = {
    "id": "api.py:checkout",
    "name": "checkout",
    "qualified_name": "checkout",
    "file_path": "api.py",
    "function_type": "function",
    "start_line": 1,
    "end_line": 10,
    "reason": "Transitively calls 'calc_tax'",
    "distance": 2
}


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestGenerateImpactReport:
    """Tests for generate_impact_report() structure and content."""

    def test_successful_report_generation(self):
        """Verify full report is produced with all required top-level keys."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A])
        selection = _selection(
            selected_tests=[{"test_id": "tests/t.py::test_tax", "target_functions": ["calc_tax"],
                             "priority": "high", "selection_reason": "covers calc_tax",
                             "test_name": "test_tax", "test_file": "tests/t.py"}]
        )
        execution = _run_tests_result(status="passed", passed=1)

        report = generate_impact_report(impact, selection, execution)

        for key in ("report_id", "generated_at", "success", "metadata",
                    "risk", "impact", "test_selection", "test_execution",
                    "evidence", "errors"):
            assert key in report, f"Missing key: {key}"

        assert report["success"] is True
        assert report["metadata"] is None
        assert isinstance(report["report_id"], str) and len(report["report_id"]) == 12

    def test_report_success_does_not_mean_safe_to_deploy(self):
        """Verify report.success reflects generation health, not risk level."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A, CHANGED_FUNC_B])
        selection = _selection(selected_tests=[])
        execution = _run_tests_result(status="skipped", passed=0, failed=0)

        report = generate_impact_report(impact, selection, execution)

        # Report generation succeeds even when risk is HIGH
        assert report["success"] is True
        # But risk level may be HIGH
        assert report["risk"]["level"] in ("MEDIUM", "HIGH")

    def test_metadata_passed_through(self):
        """Verify optional metadata dict is included verbatim."""
        meta = {"pr": "99", "branch": "feature/billing", "author": "dev@x.com", "commit": "abc123"}
        report = generate_impact_report(_impact(), _selection(), _run_tests_result(), metadata=meta)

        assert report["metadata"] == meta

    def test_risk_scorer_integration(self):
        """Verify risk section is populated by calculate_risk_score(), not hardcoded."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A])
        selection = _selection(
            selected_tests=[{"test_id": "t.py::test_tax", "target_functions": ["calc_tax"],
                             "priority": "high", "selection_reason": "r",
                             "test_name": "test_tax", "test_file": "t.py"}]
        )
        execution = _run_tests_result(status="passed", passed=1)

        report = generate_impact_report(impact, selection, execution)
        risk = report["risk"]

        for key in ("score", "level", "factors", "metrics", "safety_overrides",
                    "recommendation", "verification_status"):
            assert key in risk

        assert isinstance(risk["score"], int)
        assert risk["level"] in ("LOW", "MEDIUM", "HIGH")
        assert risk["verification_status"] == "VERIFIED"
        assert 0 <= risk["score"] <= 30  # 1 changed func + 1 test + passed → LOW


class TestExecutionNormalization:
    """Tests for handling both run_tests() and run_selected_tests() shapes."""

    def test_flat_run_tests_shape(self):
        """Verify flat run_tests() output is accepted without unwrapping."""
        execution = _run_tests_result(status="passed", passed=2)
        report = generate_impact_report(_impact(), _selection(), execution)

        assert report["test_execution"]["status"] == "passed"
        assert report["test_execution"]["summary"]["passed"] == 2

    def test_nested_run_selected_tests_shape(self):
        """Verify nested run_selected_tests() output is unwrapped from 'execution' key."""
        execution = _run_selected_tests_result(status="passed", passed=3)
        report = generate_impact_report(_impact(), _selection(), execution)

        assert report["test_execution"]["status"] == "passed"
        assert report["test_execution"]["summary"]["passed"] == 3

    def test_nested_failed_execution_normalized(self):
        """Verify failure data is extracted from nested execution block."""
        execution = _run_selected_tests_result(
            status="failed", passed=0, failed=2, exit_code=1,
            failure_details=[{"test": "t.py::test_x", "message": "AssertionError"}]
        )
        report = generate_impact_report(_impact(), _selection(), execution)

        assert report["test_execution"]["status"] == "failed"
        assert report["test_execution"]["summary"]["failed"] == 2
        assert len(report["test_execution"]["failures"]) == 1
        assert report["test_execution"]["failures"][0]["test"] == "t.py::test_x"


class TestEvidenceSection:
    """Tests for protected/exposed function and direct call path evidence."""

    def test_protected_functions_identified(self):
        """Verify changed functions with matching test coverage appear as protected."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A, CHANGED_FUNC_B])
        selection = _selection(
            selected_tests=[
                {"test_id": "t.py::test_tax", "target_functions": ["calc_tax"],
                 "priority": "high", "selection_reason": "r",
                 "test_name": "test_tax", "test_file": "t.py"},
            ]
        )
        execution = _run_tests_result()
        report = generate_impact_report(impact, selection, execution)

        evidence = report["evidence"]
        protected_names = {f["name"] for f in evidence["protected_functions"]}
        exposed_names = {f["name"] for f in evidence["exposed_functions"]}

        assert "calc_tax" in protected_names
        assert "apply_coupon" in exposed_names
        assert "calc_tax" not in exposed_names
        assert "apply_coupon" not in protected_names

    def test_exposed_functions_no_tests(self):
        """Verify changed functions with zero test coverage appear as exposed."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A, CHANGED_FUNC_B])
        selection = _selection(selected_tests=[])
        execution = _run_tests_result(status="skipped", passed=0)

        report = generate_impact_report(impact, selection, execution)

        evidence = report["evidence"]
        assert len(evidence["exposed_functions"]) == 2
        assert len(evidence["protected_functions"]) == 0

    def test_direct_call_paths_distance_one_only(self):
        """Verify only distance=1 impacted functions appear as direct call paths."""
        impact = _impact(
            changed_funcs=[CHANGED_FUNC_A],
            impacted_funcs=[IMPACTED_FUNC, IMPACTED_TRANSITIVE]
        )
        selection = _selection()
        execution = _run_tests_result()

        report = generate_impact_report(impact, selection, execution)

        paths = report["evidence"]["direct_call_paths"]
        callers = [p["caller"] for p in paths]

        assert "submit_order" in callers
        assert "checkout" not in callers  # distance=2, excluded

    def test_evidence_includes_function_ids(self):
        """Verify evidence entries include ID, name, qualified_name, and file_path."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A])
        selection = _selection(
            selected_tests=[{"test_id": "t.py::test_tax", "target_functions": ["calc_tax"],
                             "priority": "high", "selection_reason": "r",
                             "test_name": "test_tax", "test_file": "t.py"}]
        )
        execution = _run_tests_result()

        report = generate_impact_report(impact, selection, execution)

        for entry in report["evidence"]["protected_functions"]:
            assert "id" in entry
            assert "name" in entry
            assert "file_path" in entry


class TestErrorAggregation:
    """Tests for collecting and tagging errors from all three upstream modules."""

    def test_impact_errors_aggregated(self):
        """Verify impact analysis errors are collected and tagged."""
        impact = _impact(
            errors=[{"file_path": "foo.py", "error": "File not found"}]
        )
        report = generate_impact_report(impact, _selection(), _run_tests_result())

        sources = [e["source"] for e in report["errors"]]
        assert "impact_analyzer" in sources
        err = next(e for e in report["errors"] if e["source"] == "impact_analyzer")
        assert err["error"] == "File not found"

    def test_selection_errors_aggregated(self):
        """Verify test selection errors are collected and tagged."""
        selection = _selection(
            errors=[{"file_path": "bar.py", "message": "No test mapping found"}]
        )
        report = generate_impact_report(_impact(), selection, _run_tests_result())

        sources = [e["source"] for e in report["errors"]]
        assert "test_selector" in sources

    def test_execution_error_aggregated(self):
        """Verify test runner errors are collected and tagged."""
        execution = _run_tests_result(status="error", exit_code=-1)
        execution["stderr"] = "Process crashed"
        execution["message"] = "Subprocess execution failed"

        report = generate_impact_report(_impact(), _selection(), execution)

        sources = [e["source"] for e in report["errors"]]
        assert "test_runner" in sources

    def test_multiple_error_sources_combined(self):
        """Verify errors from all sources appear in one flat list."""
        impact = _impact(errors=[{"file_path": "a.py", "error": "AST parse error"}])
        selection = _selection(errors=[{"file_path": "b.py", "message": "No mapping"}])
        execution = _run_tests_result(status="error", exit_code=-1)
        execution["message"] = "Failed to execute"

        report = generate_impact_report(impact, selection, execution)

        sources = {e["source"] for e in report["errors"]}
        assert "impact_analyzer" in sources
        assert "test_selector" in sources
        assert "test_runner" in sources


class TestExecutionStatusHandling:
    """Tests for each execution status and its effect on the report."""

    def test_failed_execution(self):
        """Verify failed tests are captured in test_execution and risk is HIGH."""
        execution = _run_tests_result(
            status="failed", passed=1, failed=2, exit_code=1,
            failure_details=[
                {"test": "t.py::test_x", "message": "AssertionError: 1 != 2"},
                {"test": "t.py::test_y", "message": "RuntimeError: unexpected"}
            ]
        )
        report = generate_impact_report(_impact(changed_funcs=[CHANGED_FUNC_A]),
                                        _selection(), execution)

        assert report["test_execution"]["status"] == "failed"
        assert report["test_execution"]["summary"]["failed"] == 2
        assert len(report["test_execution"]["failures"]) == 2
        assert report["risk"]["level"] == "HIGH"
        assert report["risk"]["verification_status"] == "FAILED"
        assert report["risk"]["score"] >= 75

    def test_skipped_execution_not_verified(self):
        """Verify skipped execution is not marked VERIFIED."""
        execution = _run_tests_result(status="skipped", passed=0, skipped=1, exit_code=0)
        report = generate_impact_report(_impact(changed_funcs=[CHANGED_FUNC_A]),
                                        _selection(), execution)

        assert report["test_execution"]["status"] == "skipped"
        assert report["risk"]["verification_status"] == "SKIPPED"
        assert report["risk"]["verification_status"] != "VERIFIED"

    def test_timeout_execution(self):
        """Verify timeout sets HIGH risk and correct verification status."""
        execution = _run_tests_result(status="timeout", passed=0, failed=0, exit_code=-1)
        report = generate_impact_report(_impact(changed_funcs=[CHANGED_FUNC_A]),
                                        _selection(), execution)

        assert report["test_execution"]["status"] == "timeout"
        assert report["risk"]["level"] == "HIGH"
        assert report["risk"]["score"] >= 80
        assert report["risk"]["verification_status"] == "TIMEOUT"

    def test_error_execution(self):
        """Verify execution error sets HIGH risk."""
        execution = _run_tests_result(status="error", passed=0, failed=0, exit_code=-1)
        report = generate_impact_report(_impact(changed_funcs=[CHANGED_FUNC_A]),
                                        _selection(), execution)

        assert report["risk"]["level"] == "HIGH"
        assert report["risk"]["score"] >= 80
        assert report["risk"]["verification_status"] == "ERROR"

    def test_zero_selected_tests(self):
        """Verify report handles zero test selection gracefully."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A])
        selection = _selection(selected_tests=[])
        execution = _run_tests_result(status="skipped", passed=0)

        report = generate_impact_report(impact, selection, execution)

        assert report["test_selection"]["total_tests_selected"] == 0
        assert len(report["evidence"]["exposed_functions"]) == 1
        assert len(report["evidence"]["protected_functions"]) == 0
        assert report["risk"]["verification_status"] != "VERIFIED"


class TestRawOutputHandling:
    """Tests for stdout/stderr inclusion control."""

    def test_raw_output_excluded_by_default(self):
        """Verify stdout and stderr are absent from test_execution by default."""
        execution = _run_tests_result()
        report = generate_impact_report(_impact(), _selection(), execution)

        assert "stdout" not in report["test_execution"]
        assert "stderr" not in report["test_execution"]

    def test_raw_output_included_when_requested(self):
        """Verify stdout and stderr are included when include_raw_output=True."""
        execution = _run_tests_result()
        execution["stdout"] = "1 passed in 0.25s"
        execution["stderr"] = ""

        report = generate_impact_report(
            _impact(), _selection(), execution, include_raw_output=True
        )

        assert "stdout" in report["test_execution"]
        assert "stderr" in report["test_execution"]
        assert report["test_execution"]["stdout"] == "1 passed in 0.25s"


class TestMalformedInputs:
    """Tests for graceful handling of missing or malformed upstream data."""

    def test_none_impact_report(self):
        """Verify None impact_report does not crash the generator."""
        report = generate_impact_report(None, _selection(), _run_tests_result())  # type: ignore
        assert "report_id" in report
        assert report["risk"]["verification_status"] == "UNCERTAIN"

    def test_none_selection_result(self):
        """Verify None selection_result does not crash the generator."""
        report = generate_impact_report(_impact(), None, _run_tests_result())  # type: ignore
        assert "report_id" in report
        assert report["risk"]["verification_status"] == "UNCERTAIN"

    def test_none_execution_result(self):
        """Verify None execution_result does not crash and uses safe defaults."""
        report = generate_impact_report(_impact(), _selection(), None)  # type: ignore
        assert "report_id" in report
        # None → empty dict after normalization. Scorer sees no status, no counts.
        # Depending on selected_test_count, it will be SKIPPED or UNVERIFIED — never VERIFIED.
        assert report["risk"]["verification_status"] != "VERIFIED"

    def test_empty_dicts(self):
        """Verify empty dicts produce a valid report with safe defaults."""
        report = generate_impact_report({}, {}, {})
        assert isinstance(report, dict)
        assert "report_id" in report
        assert "risk" in report
        assert "errors" in report


class TestDeterminismAndSerialization:
    """Tests for report ID determinism and JSON serializability."""

    def test_deterministic_report_id(self):
        """Verify identical inputs always produce the same report_id."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A])
        selection = _selection()
        execution = _run_tests_result()

        r1 = generate_impact_report(impact, selection, execution)
        r2 = generate_impact_report(impact, selection, execution)

        assert r1["report_id"] == r2["report_id"]

    def test_different_inputs_different_ids(self):
        """Verify different inputs produce different report IDs."""
        r1 = generate_impact_report(_impact(changed_funcs=[CHANGED_FUNC_A]),
                                    _selection(), _run_tests_result())
        r2 = generate_impact_report(_impact(changed_funcs=[CHANGED_FUNC_B]),
                                    _selection(), _run_tests_result())

        assert r1["report_id"] != r2["report_id"]

    def test_json_serialization(self):
        """Verify full report output is strictly JSON serializable."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A], impacted_funcs=[IMPACTED_FUNC])
        selection = _selection(
            selected_tests=[{"test_id": "t.py::test_tax", "target_functions": ["calc_tax"],
                             "priority": "high", "selection_reason": "r",
                             "test_name": "test_tax", "test_file": "t.py"}]
        )
        execution = _run_tests_result(status="passed", passed=1)

        report = generate_impact_report(impact, selection, execution, metadata={"pr": "7"})

        dumped = json.dumps(report)
        assert isinstance(dumped, str)
        loaded = json.loads(dumped)
        assert loaded["report_id"] == report["report_id"]
        assert loaded["risk"]["score"] == report["risk"]["score"]


class TestMarkdownFormatting:
    """Tests for format_markdown_report() output content and structure."""

    def _make_full_report(self):
        impact = _impact(changed_funcs=[CHANGED_FUNC_A], impacted_funcs=[IMPACTED_FUNC])
        selection = _selection(
            selected_tests=[{"test_id": "t.py::test_tax", "target_functions": ["calc_tax"],
                             "priority": "high", "selection_reason": "covers calc_tax",
                             "test_name": "test_tax", "test_file": "t.py"}]
        )
        execution = _run_tests_result(status="passed", passed=1)
        return generate_impact_report(impact, selection, execution, metadata={"pr": "42"})

    def test_markdown_contains_key_sections(self):
        """Verify Markdown includes all major required sections."""
        report = self._make_full_report()
        md = format_markdown_report(report)

        assert "# ChangeGuard AI" in md
        assert "Risk Assessment" in md
        assert "Change Summary" in md
        assert "Test Selection" in md
        assert "Test Execution" in md
        assert "Evidence Audit Trail" in md
        assert "Risk Score Breakdown" in md

    def test_markdown_contains_risk_score(self):
        """Verify Markdown shows the risk score and level."""
        report = self._make_full_report()
        md = format_markdown_report(report)

        assert "/ 100" in md
        assert any(level in md for level in ("LOW", "MEDIUM", "HIGH"))

    def test_markdown_contains_recommendation(self):
        """Verify Markdown includes the actionable recommendation."""
        report = self._make_full_report()
        md = format_markdown_report(report)

        rec = report["risk"]["recommendation"]
        assert rec[:30] in md

    def test_markdown_contains_failures_on_failed_execution(self):
        """Verify Markdown shows failure details when tests failed."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A])
        selection = _selection()
        execution = _run_tests_result(
            status="failed", passed=0, failed=1, exit_code=1,
            failure_details=[{"test": "t.py::test_bad", "message": "AssertionError"}]
        )
        report = generate_impact_report(impact, selection, execution)
        md = format_markdown_report(report)

        assert "Test Failures" in md
        assert "test_bad" in md
        assert "AssertionError" in md

    def test_markdown_handles_malformed_report(self):
        """Verify format_markdown_report does not crash on None or non-dict input."""
        md_none = format_markdown_report(None)  # type: ignore
        assert "Error" in md_none

        md_empty = format_markdown_report({})
        assert "ChangeGuard AI" in md_empty

    def test_markdown_contains_exposed_functions(self):
        """Verify Markdown shows exposed (uncovered) functions."""
        impact = _impact(changed_funcs=[CHANGED_FUNC_A, CHANGED_FUNC_B])
        selection = _selection(selected_tests=[])
        execution = _run_tests_result(status="skipped", passed=0)
        report = generate_impact_report(impact, selection, execution)
        md = format_markdown_report(report)

        assert "Exposed Functions" in md or "exposed" in md.lower()
        assert "calc_tax" in md or "apply_coupon" in md

    def test_markdown_contains_metadata_when_supplied(self):
        """Verify Markdown includes metadata fields when provided."""
        report = self._make_full_report()
        md = format_markdown_report(report)

        assert "Metadata" in md
        assert "42" in md  # PR number

    def test_markdown_contains_direct_call_paths(self):
        """Verify Markdown shows direct caller relationships."""
        impact = _impact(
            changed_funcs=[CHANGED_FUNC_A],
            impacted_funcs=[IMPACTED_FUNC]
        )
        selection = _selection()
        execution = _run_tests_result()
        report = generate_impact_report(impact, selection, execution)
        md = format_markdown_report(report)

        assert "Direct Call Paths" in md or "submit_order" in md
