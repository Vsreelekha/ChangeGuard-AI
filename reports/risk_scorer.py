"""
Risk Scoring Engine for ChangeGuard AI.

Computes a deterministic, explainable 0–100 risk score and classification (LOW, MEDIUM, HIGH)
by combining static blast radius analysis, intelligent test selection coverage,
and pytest subprocess execution results.
"""

from typing import Any, Dict, List, Optional, Set


def calculate_risk_score(
    impact_report: Dict[str, Any],
    selection_result: Dict[str, Any],
    execution_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Calculate an explainable, deterministic 0–100 risk score.

    Scoring Dimensions:
        A. Blast Radius & Complexity (Max 35 points)
           - Changed functions: +5 each, max 15
           - Direct callers (distance = 1): +3 each, max 10
           - Transitive callers (distance > 1): +2 each, max 5
           - Unassigned changed lines: +1 per 5 lines, max 5
        B. Test Coverage Gaps (Max 25 points)
           - Each changed function without mapped tests: +10, max 20
           - Code changed but zero tests selected: +15
           - (Total coverage gap score capped at 25 points)
        C. Test Execution (Max 40 points)
           - All selected tests passed: +0
           - Execution skipped / unverified: +10
           - Test failure: +35
           - Timeout or execution error: +40

    Hard Safety Overrides:
        - If execution failed or failed_count > 0: score >= 75 (HIGH)
        - If execution status is timeout or error: score >= 80 (HIGH)
        - If changed functions have no mapped tests: score >= 35 (MEDIUM or HIGH)
        - Final score clamped to 0–100.

    Classification:
        - 0–30: LOW
        - 31–69: MEDIUM
        - 70–100: HIGH

    Args:
        impact_report: Output dictionary from code_analyzer.impact_analyzer.
        selection_result: Output dictionary from test_selector.selector.
        execution_result: Output dictionary from test_runner.runner.

    Returns:
        JSON-serializable dictionary with score, level, factors, metrics,
        safety_overrides, recommendation, and verification_status.
    """
    # -------------------------------------------------------------------------
    # 0. Validate Inputs & Report Uncertainty on Malformed Data
    # -------------------------------------------------------------------------
    is_impact_valid = isinstance(impact_report, dict)
    is_selection_valid = isinstance(selection_result, dict)
    is_exec_valid = isinstance(execution_result, dict)

    if not (is_impact_valid and is_selection_valid and is_exec_valid):
        missing = []
        if not is_impact_valid:
            missing.append("impact_report")
        if not is_selection_valid:
            missing.append("selection_result")
        if not is_exec_valid:
            missing.append("execution_result")

        return {
            "score": 50,
            "level": "MEDIUM",
            "factors": [
                {
                    "name": "Input Integrity",
                    "points": 50,
                    "max_points": 50,
                    "explanation": f"Input data missing or malformed for: {', '.join(missing)}."
                }
            ],
            "metrics": {
                "changed_function_count": 0,
                "impacted_function_count": 0,
                "direct_caller_count": 0,
                "transitive_caller_count": 0,
                "unassigned_line_count": 0,
                "discovered_test_count": 0,
                "selected_test_count": 0,
                "uncovered_changed_function_count": 0,
                "failed_test_count": 0,
                "skipped_test_count": 0
            },
            "safety_overrides": ["Input data missing or malformed; uncertainty reported."],
            "recommendation": "ACTION REQUIRED: Unable to verify change safety due to missing or malformed input data.",
            "verification_status": "UNCERTAIN"
        }

    # -------------------------------------------------------------------------
    # 1. Parse & Deduplicate Blast Radius Data (Impact Analyzer)
    # -------------------------------------------------------------------------
    raw_changed = impact_report.get("changed_functions") or []
    unique_changed_funcs: Dict[str, Dict[str, Any]] = {}
    for f in raw_changed:
        if not isinstance(f, dict):
            continue
        fid = f.get("id") or f"{f.get('file_path', '')}:{f.get('qualified_name', f.get('name', ''))}"
        if fid:
            unique_changed_funcs[fid] = f

    raw_impacted = impact_report.get("impacted_functions") or []
    unique_impacted_funcs: Dict[str, Dict[str, Any]] = {}
    for f in raw_impacted:
        if not isinstance(f, dict):
            continue
        fid = f.get("id") or f"{f.get('file_path', '')}:{f.get('qualified_name', f.get('name', ''))}"
        # Ensure impacted functions do not duplicate changed functions
        if fid and fid not in unique_changed_funcs:
            unique_impacted_funcs[fid] = f

    direct_callers = [f for f in unique_impacted_funcs.values() if f.get("distance", 1) == 1]
    transitive_callers = [f for f in unique_impacted_funcs.values() if f.get("distance", 1) > 1]

    raw_unassigned = impact_report.get("unassigned_changed_lines") or []
    unassigned_lines_count = sum(
        len(item.get("lines", [])) for item in raw_unassigned if isinstance(item, dict)
    )

    # -------------------------------------------------------------------------
    # 2. Section A: Blast Radius & Complexity (Max 35 points)
    # -------------------------------------------------------------------------
    pts_changed = min(15, len(unique_changed_funcs) * 5)
    pts_direct = min(10, len(direct_callers) * 3)
    pts_transitive = min(5, len(transitive_callers) * 2)
    pts_unassigned = min(5, unassigned_lines_count // 5)

    pts_section_a = min(35, pts_changed + pts_direct + pts_transitive + pts_unassigned)

    # -------------------------------------------------------------------------
    # 3. Section B: Test Coverage Gaps (Max 25 points)
    # -------------------------------------------------------------------------
    selected_tests = selection_result.get("selected_tests") or []
    covered_targets: Set[str] = set()
    for t in selected_tests:
        if isinstance(t, dict):
            for tf in t.get("target_functions", []):
                if isinstance(tf, str):
                    covered_targets.add(tf.strip())

    uncovered_changed_funcs: List[Dict[str, Any]] = []
    for fid, f in unique_changed_funcs.items():
        f_name = str(f.get("name", "")).strip()
        f_qname = str(f.get("qualified_name", "")).strip()
        f_path = str(f.get("file_path", "")).replace("\\", "/").strip()

        is_covered = False
        if fid in covered_targets or f_name in covered_targets or f_qname in covered_targets:
            is_covered = True
        else:
            for ct in covered_targets:
                if (
                    ct == fid
                    or fid.endswith(":" + ct)
                    or ct.endswith(":" + f_qname)
                    or ct.endswith(":" + f_name)
                    or (f_path and ct.startswith(f_path) and (ct.endswith(f":{f_qname}") or ct.endswith(f":{f_name}")))
                ):
                    is_covered = True
                    break

        if not is_covered:
            uncovered_changed_funcs.append(f)

    # Each changed function without mapped tests: +10, maximum 20
    pts_uncovered = min(20, len(uncovered_changed_funcs) * 10)

    # Code changed but zero tests selected: +15
    has_code_changes = (
        len(unique_changed_funcs) > 0
        or unassigned_lines_count > 0
        or len(impact_report.get("changed_files") or []) > 0
    )
    total_selected_tests = len(selected_tests)
    pts_zero_tests = 15 if (has_code_changes and total_selected_tests == 0) else 0

    pts_section_b = min(25, pts_uncovered + pts_zero_tests)

    # -------------------------------------------------------------------------
    # 4. Section C: Test Execution (Max 40 points)
    # -------------------------------------------------------------------------
    exec_summary = execution_result.get("summary") or {}
    failed_count = exec_summary.get("failed", 0)
    passed_count = exec_summary.get("passed", 0)
    skipped_count = exec_summary.get("skipped", 0)
    total_executed = exec_summary.get("total", 0)
    exec_status = str(execution_result.get("status", "")).strip().lower()

    if exec_status in ("timeout", "error") or execution_result.get("exit_code") == -1:
        pts_section_c = 40
        exec_explanation = f"Test execution encountered {exec_status.upper()} (+40 pts)"
        verification_status = exec_status.upper()
    elif exec_status == "failed" or failed_count > 0:
        pts_section_c = 35
        exec_explanation = f"Test execution failed: {failed_count} test(s) failed (+35 pts)"
        verification_status = "FAILED"
    elif exec_status == "skipped" or (total_executed == 0 and total_selected_tests == 0) or (passed_count == 0 and skipped_count > 0):
        # Do not treat skipped or zero-execution as passing
        pts_section_c = 10
        exec_explanation = f"Test execution skipped: 0 tests verified (+10 pts)"
        verification_status = "SKIPPED"
    elif exec_status == "passed":
        # Rule: If execution status is passed, verify execution summary has zero failures
        if failed_count > 0:
            pts_section_c = 35
            exec_explanation = f"Execution reported passed but had {failed_count} failure(s) (+35 pts)"
            verification_status = "FAILED"
        elif passed_count > 0:
            pts_section_c = 0
            exec_explanation = f"All {passed_count} selected test(s) passed successfully (+0 pts)"
            verification_status = "VERIFIED"
        else:
            # Passed with 0 executed tests: do not treat as passed
            pts_section_c = 10
            exec_explanation = "Zero tests were executed (+10 pts)"
            verification_status = "UNVERIFIED"
    else:
        # Missing or unknown execution status
        pts_section_c = 10
        exec_explanation = f"Unverified execution status '{exec_status}' (+10 pts)"
        verification_status = "UNVERIFIED"

    # -------------------------------------------------------------------------
    # 5. Base Score & Safety Overrides
    # -------------------------------------------------------------------------
    base_score = pts_section_a + pts_section_b + pts_section_c
    score = base_score
    safety_overrides: List[str] = []

    # Override 1: Test failure -> min 75 (HIGH)
    if exec_status == "failed" or failed_count > 0:
        if score < 75:
            score = 75
            safety_overrides.append(
                f"Hard safety override applied: Score raised to 75 due to test failure ({failed_count} failing test(s))."
            )

    # Override 2: Timeout or Error -> min 80 (HIGH)
    if exec_status in ("timeout", "error"):
        if score < 80:
            score = 80
            safety_overrides.append(
                f"Hard safety override applied: Score raised to 80 due to test execution {exec_status.upper()}."
            )

    # Override 3: Changed functions without mapped tests -> min 35 (MEDIUM)
    if len(unique_changed_funcs) > 0 and len(uncovered_changed_funcs) > 0:
        if score < 35:
            score = 35
            safety_overrides.append(
                f"Hard safety override applied: Score raised to 35 due to {len(uncovered_changed_funcs)} uncovered changed function(s)."
            )

    # Clamping: Score never exceeds 100 or drops below 0
    score = min(100, max(0, score))

    # -------------------------------------------------------------------------
    # 6. Risk Level Classification
    # -------------------------------------------------------------------------
    if score <= 30:
        level = "LOW"
    elif score <= 69:
        level = "MEDIUM"
    else:
        level = "HIGH"

    # -------------------------------------------------------------------------
    # 7. Actionable Recommendations
    # -------------------------------------------------------------------------
    if level == "HIGH":
        if failed_count > 0 or exec_status in ("failed", "timeout", "error"):
            recommendation = "DO NOT DEPLOY: Regressions or test execution failures detected. Fix all failing tests before proceeding."
        else:
            recommendation = "DO NOT DEPLOY: High risk blast radius or unverified critical changes. Manual review and additional test coverage required."
    elif level == "MEDIUM":
        recommendation = "PROCEED WITH CAUTION: Moderate blast radius or partial test coverage. Recommend adding regression tests for uncovered code paths."
    else:
        recommendation = "SAFE TO DEPLOY: Changes are localized with low blast radius, and all relevant regression tests passed."

    # -------------------------------------------------------------------------
    # 8. Detailed Scoring Factors with Evidence
    # -------------------------------------------------------------------------
    factors = [
        {
            "name": "Changed Functions",
            "points": pts_changed,
            "max_points": 15,
            "explanation": f"{len(unique_changed_funcs)} directly changed function(s) (+5 pts each, max 15)."
        },
        {
            "name": "Direct Callers",
            "points": pts_direct,
            "max_points": 10,
            "explanation": f"{len(direct_callers)} direct caller(s) at dependency distance 1 (+3 pts each, max 10)."
        },
        {
            "name": "Transitive Callers",
            "points": pts_transitive,
            "max_points": 5,
            "explanation": f"{len(transitive_callers)} transitive caller(s) at dependency distance > 1 (+2 pts each, max 5)."
        },
        {
            "name": "Unassigned Changed Lines",
            "points": pts_unassigned,
            "max_points": 5,
            "explanation": f"{unassigned_lines_count} unassigned lines modified outside functions (+1 pt per 5 lines, max 5)."
        },
        {
            "name": "Untested Changed Functions",
            "points": pts_uncovered,
            "max_points": 20,
            "explanation": f"{len(uncovered_changed_funcs)} of {len(unique_changed_funcs)} changed function(s) lack mapped tests (+10 pts each, max 20)."
        },
        {
            "name": "Zero Tests Selected",
            "points": pts_zero_tests,
            "max_points": 15,
            "explanation": "Code changed but zero tests were selected (+15 pts)." if pts_zero_tests else "Tests were selected for code changes (+0 pts)."
        },
        {
            "name": "Test Execution",
            "points": pts_section_c,
            "max_points": 40,
            "explanation": exec_explanation
        }
    ]

    # -------------------------------------------------------------------------
    # 9. Structured Metrics
    # -------------------------------------------------------------------------
    metrics = {
        "changed_function_count": len(unique_changed_funcs),
        "impacted_function_count": len(unique_impacted_funcs),
        "direct_caller_count": len(direct_callers),
        "transitive_caller_count": len(transitive_callers),
        "unassigned_line_count": unassigned_lines_count,
        "discovered_test_count": int(selection_result.get("total_tests_discovered", 0)),
        "selected_test_count": total_selected_tests,
        "uncovered_changed_function_count": len(uncovered_changed_funcs),
        "failed_test_count": failed_count,
        "skipped_test_count": skipped_count
    }

    return {
        "score": score,
        "level": level,
        "factors": factors,
        "metrics": metrics,
        "safety_overrides": safety_overrides,
        "recommendation": recommendation,
        "verification_status": verification_status
    }
