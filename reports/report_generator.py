"""
Report Generation module for ChangeGuard AI.

Assembles a single, self-contained impact report by combining outputs from
the Code Analyzer, Test Selector, Test Runner, and Risk Scorer.
Provides both JSON-serializable dict output and a readable Markdown format.
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reports.risk_scorer import calculate_risk_score


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_execution_result(execution_result: Any) -> Dict[str, Any]:
    """
    Normalize execution input regardless of whether it comes from:
      - run_tests()         → top-level keys: status, summary, failure_details …
      - run_selected_tests() → top-level status + nested "execution" key

    Always returns a dict with the flat run_tests() schema.
    """
    if not isinstance(execution_result, dict):
        return {}

    # run_selected_tests() wraps run_tests() output under "execution"
    if "execution" in execution_result and isinstance(execution_result["execution"], dict):
        return execution_result["execution"]

    return execution_result


def _generate_report_id(
    impact_report: Any,
    selection_result: Any,
    execution_result: Any
) -> str:
    """
    Produce a deterministic 12-character hex ID from the canonicalized inputs.
    Identical inputs always yield the same ID; the timestamp is excluded.
    """
    try:
        canonical = json.dumps(
            {
                "impact": impact_report,
                "selection": selection_result,
                "execution": execution_result
            },
            sort_keys=True,
            default=str
        )
    except Exception:
        canonical = repr((impact_report, selection_result, execution_result))

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _aggregate_errors(
    impact_report: Any,
    selection_result: Any,
    exec_result: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Collect and tag errors from every upstream module."""
    aggregated: List[Dict[str, Any]] = []

    if isinstance(impact_report, dict):
        for err in impact_report.get("errors") or []:
            if isinstance(err, dict):
                aggregated.append({
                    "source": "impact_analyzer",
                    "file_path": err.get("file_path", ""),
                    "error": err.get("error", str(err))
                })

    if isinstance(selection_result, dict):
        for err in selection_result.get("errors") or []:
            if isinstance(err, dict):
                aggregated.append({
                    "source": "test_selector",
                    "file_path": err.get("file_path", ""),
                    "error": err.get("message") or err.get("error", str(err))
                })

    exec_status = str(exec_result.get("status", "")).strip().lower()
    stderr = exec_result.get("stderr", "") or ""
    exec_msg = exec_result.get("message", "") or ""
    if exec_status in ("timeout", "error") or (stderr and exec_status == "error"):
        aggregated.append({
            "source": "test_runner",
            "file_path": "",
            "error": exec_msg or stderr or f"Execution ended with status: {exec_status}"
        })

    return aggregated


def _build_evidence(
    impact_report: Dict[str, Any],
    selection_result: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build the evidence section by cross-referencing changed functions with
    selected test target_functions, and direct callers from impacted functions.
    """
    changed_functions: List[Dict[str, Any]] = impact_report.get("changed_functions") or []
    impacted_functions: List[Dict[str, Any]] = impact_report.get("impacted_functions") or []
    selected_tests: List[Dict[str, Any]] = selection_result.get("selected_tests") or []

    # Build lookup: canonical keys → test IDs that cover them
    # Keys = function name, qualified_name, and full ID forms from target_functions
    coverage_map: Dict[str, List[str]] = {}
    for t in selected_tests:
        if not isinstance(t, dict):
            continue
        test_id = t.get("test_id", "")
        for tf in t.get("target_functions") or []:
            if isinstance(tf, str) and tf.strip():
                coverage_map.setdefault(tf.strip(), []).append(test_id)

    def _find_covering_tests(func: Dict[str, Any]) -> List[str]:
        """Return test IDs that cover this changed function, using ID/qname/name."""
        fid = str(func.get("id", "")).strip()
        fname = str(func.get("name", "")).strip()
        fqname = str(func.get("qualified_name", "")).strip()
        fpath = str(func.get("file_path", "")).replace("\\", "/").strip()

        matched: List[str] = []
        seen: set = set()

        for key, test_ids in coverage_map.items():
            hit = (
                key == fid
                or key == fname
                or key == fqname
                or (fid and fid.endswith(":" + key))
                or (key and fid.endswith(":" + key))
                or (fqname and key.endswith(":" + fqname))
                or (fname and key.endswith(":" + fname))
                or (fpath and key.startswith(fpath) and (
                    key.endswith(":" + fqname) or key.endswith(":" + fname)
                ))
            )
            if hit:
                for tid in test_ids:
                    if tid not in seen:
                        seen.add(tid)
                        matched.append(tid)

        return matched

    protected: List[Dict[str, Any]] = []
    exposed: List[Dict[str, Any]] = []

    for func in changed_functions:
        if not isinstance(func, dict):
            continue
        covering = _find_covering_tests(func)
        entry = {
            "id": func.get("id", ""),
            "name": func.get("name", ""),
            "qualified_name": func.get("qualified_name", ""),
            "file_path": func.get("file_path", "")
        }
        if covering:
            protected.append({**entry, "tests": covering})
        else:
            exposed.append(entry)

    # Direct call paths: impacted functions at distance == 1
    direct_call_paths: List[Dict[str, Any]] = []
    for func in impacted_functions:
        if not isinstance(func, dict):
            continue
        if func.get("distance", 1) == 1:
            direct_call_paths.append({
                "caller": func.get("qualified_name") or func.get("name", ""),
                "file_path": func.get("file_path", ""),
                "reason": func.get("reason", ""),
                "distance": 1
            })

    return {
        "protected_functions": protected,
        "exposed_functions": exposed,
        "direct_call_paths": direct_call_paths
    }


def _build_test_execution_section(
    exec_result: Dict[str, Any],
    include_raw_output: bool
) -> Dict[str, Any]:
    """Build the test_execution section from a normalised run_tests() result."""
    summary = exec_result.get("summary") or {}
    failure_details = exec_result.get("failure_details") or []

    section: Dict[str, Any] = {
        "status": exec_result.get("status", ""),
        "execution_time": exec_result.get("execution_time", 0.0),
        "exit_code": exec_result.get("exit_code", None),
        "summary": {
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0),
            "total": summary.get("total", 0)
        },
        "failures": [
            {"test": fd.get("test", ""), "message": fd.get("message", "")}
            for fd in failure_details
            if isinstance(fd, dict)
        ],
        "message": exec_result.get("message", "")
    }

    if include_raw_output:
        section["stdout"] = exec_result.get("stdout", "")
        section["stderr"] = exec_result.get("stderr", "")

    return section


def _build_test_selection_section(selection_result: Dict[str, Any]) -> Dict[str, Any]:
    """Build the test_selection section from select_tests() output."""
    if not isinstance(selection_result, dict):
        return {
            "total_tests_discovered": 0,
            "total_tests_selected": 0,
            "reduction_percentage": 0.0,
            "selection_summary": {},
            "selected_tests": []
        }

    return {
        "total_tests_discovered": selection_result.get("total_tests_discovered", 0),
        "total_tests_selected": selection_result.get("total_tests_selected", 0),
        "reduction_percentage": selection_result.get("reduction_percentage", 0.0),
        "selection_summary": selection_result.get("selection_summary") or {},
        "selected_tests": selection_result.get("selected_tests") or []
    }


def _build_impact_section(impact_report: Dict[str, Any]) -> Dict[str, Any]:
    """Build the impact section from analyze_code_impact() output."""
    if not isinstance(impact_report, dict):
        return {
            "summary": {},
            "changed_files": [],
            "changed_functions": [],
            "impacted_functions": [],
            "unassigned_changed_lines": []
        }

    return {
        "summary": impact_report.get("summary") or {},
        "changed_files": impact_report.get("changed_files") or [],
        "changed_functions": impact_report.get("changed_functions") or [],
        "impacted_functions": impact_report.get("impacted_functions") or [],
        "unassigned_changed_lines": impact_report.get("unassigned_changed_lines") or []
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_impact_report(
    impact_report: Dict[str, Any],
    selection_result: Dict[str, Any],
    execution_result: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    include_raw_output: bool = False
) -> Dict[str, Any]:
    """
    Assemble a complete, self-contained ChangeGuard AI impact report.

    Integrates outputs from:
      - analyze_code_impact()     → impact analysis
      - select_tests()            → intelligent test selection
      - run_tests() or
        run_selected_tests()      → test execution (both shapes supported)
      - calculate_risk_score()    → deterministic risk assessment

    Args:
        impact_report:    Output of analyze_code_impact().
        selection_result: Output of select_tests().
        execution_result: Output of run_tests() or run_selected_tests().
        metadata:         Optional caller context (PR, branch, author, commit).
        include_raw_output: When True, attaches stdout/stderr to test_execution.

    Returns:
        JSON-serializable dict. `success` reflects whether the report was
        generated without fatal errors — NOT whether the code is safe to deploy.
        Risk level and verification_status communicate deployment safety.
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    # Normalize execution: handle both run_tests() and run_selected_tests() shapes
    exec_result = _normalize_execution_result(execution_result)

    # Deterministic ID from inputs only (not the timestamp)
    report_id = _generate_report_id(impact_report, selection_result, execution_result)

    # Risk score (reuse existing scorer — no duplication)
    risk = calculate_risk_score(impact_report, selection_result, exec_result)

    # Build sections
    impact_section = _build_impact_section(impact_report)
    selection_section = _build_test_selection_section(selection_result)
    exec_section = _build_test_execution_section(exec_result, include_raw_output)
    evidence = _build_evidence(
        impact_report if isinstance(impact_report, dict) else {},
        selection_result if isinstance(selection_result, dict) else {}
    )
    errors = _aggregate_errors(impact_report, selection_result, exec_result)

    # Report `success` = report was assembled without fatal upstream errors.
    # It does NOT mean the code change is safe to deploy.
    impact_ok = isinstance(impact_report, dict) and impact_report.get("success", True)
    selection_ok = isinstance(selection_result, dict) and selection_result.get("success", True)
    exec_status = exec_result.get("status", "")
    exec_ok = exec_status not in ("error",) and exec_result.get("exit_code", 0) != -1
    report_success = bool(impact_ok and selection_ok and exec_ok)

    return {
        "report_id": report_id,
        "generated_at": generated_at,
        "success": report_success,
        "metadata": metadata if isinstance(metadata, dict) else None,
        "risk": risk,
        "impact": impact_section,
        "test_selection": selection_section,
        "test_execution": exec_section,
        "evidence": evidence,
        "errors": errors
    }


def format_markdown_report(report: Dict[str, Any]) -> str:
    """
    Render a ChangeGuard AI impact report as a readable Markdown string.

    Reads only from the supplied report dictionary.
    Does not re-run any analysis, tests, or scoring.

    Args:
        report: Dictionary produced by generate_impact_report().

    Returns:
        Markdown string suitable for display in a PR comment, terminal, or UI.
    """
    if not isinstance(report, dict):
        return "# ChangeGuard AI — Report Error\n\nReport data is missing or malformed.\n"

    lines: List[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    risk = report.get("risk") or {}
    score = risk.get("score", "N/A")
    level = risk.get("level", "UNKNOWN")
    verification = risk.get("verification_status", "UNKNOWN")

    level_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(level, "⚪")
    verify_emoji = {
        "VERIFIED": "✅", "FAILED": "❌", "SKIPPED": "⏭",
        "TIMEOUT": "⏱", "ERROR": "💥", "UNVERIFIED": "❓", "UNCERTAIN": "⚠️"
    }.get(verification, "❓")

    lines += [
        "# ChangeGuard AI — Impact Report",
        "",
        f"**Report ID:** `{report.get('report_id', 'N/A')}`  ",
        f"**Generated:** {report.get('generated_at', 'N/A')}",
        "",
        "---",
        "",
        "## Risk Assessment",
        "",
        f"| Field | Value |",
        f"|---|---|",
        f"| Risk Score | **{score} / 100** |",
        f"| Risk Level | {level_emoji} **{level}** |",
        f"| Verification | {verify_emoji} {verification} |",
        ""
    ]

    recommendation = risk.get("recommendation", "")
    if recommendation:
        lines += [f"> **{recommendation}**", ""]

    # ── Metadata ────────────────────────────────────────────────────────────
    meta = report.get("metadata")
    if isinstance(meta, dict) and meta:
        lines += ["## Metadata", ""]
        for k, v in meta.items():
            lines.append(f"- **{k}:** {v}")
        lines.append("")

    # ── Change Summary ───────────────────────────────────────────────────────
    impact = report.get("impact") or {}
    summary = impact.get("summary") or {}
    lines += [
        "## Change Summary",
        "",
        f"| Metric | Count |",
        f"|---|---|",
        f"| Changed files | {summary.get('changed_files_count', 0)} |",
        f"| Changed functions | {summary.get('changed_functions_count', 0)} |",
        f"| Impacted functions | {summary.get('impacted_functions_count', 0)} |",
        f"| Unassigned changed lines | {summary.get('unassigned_lines_count', 0)} |",
        f"| Analysis errors | {summary.get('errors_count', 0)} |",
        ""
    ]

    # ── Changed Functions ────────────────────────────────────────────────────
    changed_funcs = impact.get("changed_functions") or []
    if changed_funcs:
        lines += ["## Directly Changed Functions", ""]
        lines += ["| Function | Type | File | Lines |", "|---|---|---|---|"]
        for f in changed_funcs:
            lines.append(
                f"| `{f.get('qualified_name', f.get('name', '?'))}` "
                f"| {f.get('function_type', '?')} "
                f"| `{f.get('file_path', '?')}` "
                f"| {f.get('start_line', '?')}–{f.get('end_line', '?')} |"
            )
        lines.append("")

    # ── Impacted Functions ───────────────────────────────────────────────────
    impacted_funcs = impact.get("impacted_functions") or []
    if impacted_funcs:
        lines += ["## Transitively Impacted Functions", ""]
        lines += ["| Function | File | Distance | Reason |", "|---|---|---|---|"]
        for f in impacted_funcs:
            lines.append(
                f"| `{f.get('qualified_name', f.get('name', '?'))}` "
                f"| `{f.get('file_path', '?')}` "
                f"| {f.get('distance', '?')} "
                f"| {f.get('reason', '')} |"
            )
        lines.append("")

    # ── Test Selection ───────────────────────────────────────────────────────
    sel = report.get("test_selection") or {}
    sel_summary = sel.get("selection_summary") or {}
    lines += [
        "## Test Selection",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Tests discovered | {sel.get('total_tests_discovered', 0)} |",
        f"| Tests selected | {sel.get('total_tests_selected', 0)} |",
        f"| Test reduction | {sel.get('reduction_percentage', 0.0):.1f}% |",
        f"| High priority | {sel_summary.get('high_priority_count', 0)} |",
        f"| Medium priority | {sel_summary.get('medium_priority_count', 0)} |",
        f"| Module-level | {sel_summary.get('module_level_count', 0)} |",
        ""
    ]

    selected_tests = sel.get("selected_tests") or []
    if selected_tests:
        lines += ["### Selected Tests", ""]
        lines += ["| Test | Priority | Reason |", "|---|---|---|"]
        for t in selected_tests:
            lines.append(
                f"| `{t.get('test_id', t.get('test_name', '?'))}` "
                f"| {t.get('priority', '?')} "
                f"| {t.get('selection_reason', '')} |"
            )
        lines.append("")

    # ── Test Execution ───────────────────────────────────────────────────────
    exec_sec = report.get("test_execution") or {}
    exec_sum = exec_sec.get("summary") or {}
    exec_status_str = exec_sec.get("status", "")
    failures = exec_sec.get("failures") or []

    lines += [
        "## Test Execution",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Status | **{exec_status_str.upper() if exec_status_str else 'N/A'}** |",
        f"| Passed | {exec_sum.get('passed', 0)} |",
        f"| Failed | {exec_sum.get('failed', 0)} |",
        f"| Skipped | {exec_sum.get('skipped', 0)} |",
        f"| Total | {exec_sum.get('total', 0)} |",
        f"| Execution time | {exec_sec.get('execution_time', 0.0):.3f}s |",
        ""
    ]

    if exec_sec.get("message"):
        lines += [f"_{exec_sec['message']}_", ""]

    if failures:
        lines += ["### Test Failures", ""]
        for fl in failures:
            lines.append(f"- ❌ `{fl.get('test', '?')}`: {fl.get('message', '')}")
        lines.append("")

    if exec_sec.get("stdout") or exec_sec.get("stderr"):
        lines += ["<details><summary>Raw Output</summary>", ""]
        if exec_sec.get("stdout"):
            lines += ["**stdout:**", "```", exec_sec["stdout"].strip(), "```", ""]
        if exec_sec.get("stderr"):
            lines += ["**stderr:**", "```", exec_sec["stderr"].strip(), "```", ""]
        lines += ["</details>", ""]

    # ── Evidence ─────────────────────────────────────────────────────────────
    evidence = report.get("evidence") or {}
    protected = evidence.get("protected_functions") or []
    exposed = evidence.get("exposed_functions") or []
    direct_paths = evidence.get("direct_call_paths") or []

    lines += ["## Evidence Audit Trail", ""]

    if protected:
        lines += [f"### ✅ Protected Functions ({len(protected)} covered by tests)", ""]
        for f in protected:
            test_ids = ", ".join(f"``{t}``" for t in (f.get("tests") or []))
            lines.append(
                f"- `{f.get('qualified_name') or f.get('name', '?')}` "
                f"(`{f.get('file_path', '?')}`) — covered by: {test_ids or 'mapped test'}"
            )
        lines.append("")

    if exposed:
        lines += [f"### ⚠️ Exposed Functions ({len(exposed)} without mapped tests)", ""]
        for f in exposed:
            lines.append(
                f"- `{f.get('qualified_name') or f.get('name', '?')}` "
                f"(`{f.get('file_path', '?')}`) — **no regression test coverage**"
            )
        lines.append("")

    if direct_paths:
        lines += [f"### 🔗 Direct Call Paths ({len(direct_paths)} callers at distance 1)", ""]
        for cp in direct_paths:
            lines.append(
                f"- `{cp.get('caller', '?')}` (`{cp.get('file_path', '?')}`) "
                f"— {cp.get('reason', 'directly calls a changed function')}"
            )
        lines.append("")

    # ── Risk Score Factors ───────────────────────────────────────────────────
    factors = risk.get("factors") or []
    if factors:
        lines += ["## Risk Score Breakdown", ""]
        lines += ["| Factor | Points | Max | Explanation |", "|---|---|---|---|"]
        for f in factors:
            lines.append(
                f"| {f.get('name', '?')} "
                f"| {f.get('points', 0)} "
                f"| {f.get('max_points', '?')} "
                f"| {f.get('explanation', '')} |"
            )
        lines.append("")

    safety_overrides = risk.get("safety_overrides") or []
    if safety_overrides:
        lines += ["### Safety Overrides Applied", ""]
        for ov in safety_overrides:
            lines.append(f"- ⚠️ {ov}")
        lines.append("")

    # ── Errors ───────────────────────────────────────────────────────────────
    errors = report.get("errors") or []
    if errors:
        lines += ["## Errors and Warnings", ""]
        for err in errors:
            src = err.get("source", "unknown")
            fp = err.get("file_path", "")
            msg = err.get("error", str(err))
            loc = f" (`{fp}`)" if fp else ""
            lines.append(f"- **{src}**{loc}: {msg}")
        lines.append("")

    # ── Footer ───────────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        "_Generated by ChangeGuard AI · Risk scoring is deterministic and evidence-based._",
        ""
    ]

    return "\n".join(lines)
