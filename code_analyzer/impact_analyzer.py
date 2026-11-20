"""
Impact Analyzer for ChangeGuard AI.

Combines the Git Diff Parser, Python AST Analyzer, and NetworkX Dependency Graph
to compute end-to-end code change impact: identifying changed functions,
unassigned lines, and transitively impacted callers.
"""

import os
from typing import Any, Dict, List, Optional, Set
from code_analyzer.diff_parser import parse_git_diff
from code_analyzer.ast_analyzer import analyze_changed_functions
from code_analyzer.dependency_graph import build_dependency_graph, get_impacted_functions


def _find_matching_source_file(diff_path: str, source_files: List[str]) -> Optional[str]:
    """
    Match a file path reported in a Git diff to one of the provided source files.

    Handles exact matches, normalized paths, relative path suffixes, and basenames.
    """
    if not diff_path or not source_files:
        return None

    clean_diff = os.path.normpath(diff_path).replace("\\", "/")

    # 1. Exact or normalized match
    for sf in source_files:
        norm_sf = os.path.normpath(sf).replace("\\", "/")
        if norm_sf == clean_diff:
            return sf

    # 2. Suffix match (e.g. diff_path 'services/billing.py' matching 'c:/repo/services/billing.py')
    for sf in source_files:
        norm_sf = os.path.normpath(sf).replace("\\", "/")
        if norm_sf.endswith("/" + clean_diff) or clean_diff.endswith("/" + norm_sf):
            return sf

    # 3. Basename match as fallback
    diff_base = os.path.basename(clean_diff)
    for sf in source_files:
        if os.path.basename(sf) == diff_base:
            return sf

    # 4. Check if diff_path directly exists on disk
    if os.path.isfile(diff_path):
        return diff_path

    return None


def analyze_code_impact(diff_text: str, source_files: List[str]) -> Dict[str, Any]:
    """
    Analyze the blast radius and transitive impact of code changes in a Git diff.

    Workflow:
        1. Parse the supplied Git diff using parse_git_diff().
        2. For each changed file, obtain its changed line numbers.
        3. Use analyze_changed_functions() to identify functions containing those lines.
        4. Build a dependency graph from the supplied source files using build_dependency_graph().
        5. Pass identified changed functions to get_impacted_functions().
        6. Combine the results into a unified JSON-serializable impact report.

    Args:
        diff_text: Unified Git diff output as a string.
        source_files: List of Python source file paths representing the codebase.

    Returns:
        dict: A structured report containing:
            - success (bool)
            - changed_files (list)
            - changed_functions (list)
            - impacted_functions (list)
            - unassigned_changed_lines (list)
            - errors (list)
            - summary (dict)
    """
    errors: List[Dict[str, Any]] = []
    changed_files: List[Dict[str, Any]] = []
    changed_functions: List[Dict[str, Any]] = []
    unassigned_changed_lines: List[Dict[str, Any]] = []

    # 1. Parse Git diff
    diff_result = parse_git_diff(diff_text)
    parsed_files = diff_result.get("files", [])

    # 2. Build dependency graph from supplied source files
    if source_files is None or not isinstance(source_files, list):
        errors.append({
            "file_path": "",
            "error": "Invalid source_files: expected list of file paths"
        })
        graph_data: Dict[str, Any] = {"nodes": [], "edges": [], "errors": [], "success": False}
    else:
        graph_data = build_dependency_graph(source_files)
        for g_err in graph_data.get("errors", []):
            errors.append(g_err)

    seen_function_ids: Set[str] = set()
    changed_function_identifiers: List[str] = []

    # 3. Process each changed file in the diff
    for file_info in parsed_files:
        diff_file_path = file_info.get("file_path", "")
        change_type = file_info.get("change_type", "modified")
        added_lines = file_info.get("added_lines", [])
        deleted_lines = file_info.get("deleted_lines", [])

        file_record = {
            "file_path": diff_file_path,
            "change_type": change_type,
            "added_lines_count": len(added_lines),
            "deleted_lines_count": len(deleted_lines)
        }
        changed_files.append(file_record)

        # Deleted files do not have code in the new version to parse with AST
        if change_type == "deleted":
            continue

        # Determine line numbers to analyze in current file version
        # Prefer new line numbers of added/modified lines; if pure deletion, check deleted line position
        if added_lines:
            target_lines = [l["line_number"] for l in added_lines]
        elif deleted_lines:
            target_lines = [l["line_number"] for l in deleted_lines]
        else:
            target_lines = []

        # Resolve the source file location on disk
        actual_path = _find_matching_source_file(diff_file_path, source_files or [])
        if not actual_path or not os.path.isfile(actual_path):
            errors.append({
                "file_path": diff_file_path,
                "error": f"Source file not found for diff path: '{diff_file_path}'"
            })
            continue

        # If there are no line numbers to analyze, skip AST inspection
        if not target_lines:
            continue

        # 4. Analyze changed functions using AST
        ast_result = analyze_changed_functions(actual_path, target_lines)
        if not ast_result.get("success"):
            errors.append({
                "file_path": diff_file_path,
                "error": ast_result.get("error", "Unknown AST analysis error")
            })
            continue

        norm_actual_path = os.path.normpath(actual_path).replace("\\", "/")

        for func in ast_result.get("functions", []):
            qname = func["qualified_name"]
            func_id = f"{norm_actual_path}:{qname}"

            if func_id not in seen_function_ids:
                seen_function_ids.add(func_id)
                changed_function_identifiers.append(func_id)

                # Determine function type
                if func.get("is_method"):
                    function_type = "method"
                elif "." in qname and not func.get("parent_class"):
                    function_type = "nested function"
                else:
                    function_type = "function"

                changed_functions.append({
                    "id": func_id,
                    "name": func["name"],
                    "qualified_name": qname,
                    "file_path": norm_actual_path,
                    "start_line": func["start_line"],
                    "end_line": func["end_line"],
                    "function_type": function_type,
                    "changed_lines": func.get("changed_lines", [])
                })

        unassigned = ast_result.get("unassigned_lines", [])
        if unassigned:
            unassigned_changed_lines.append({
                "file_path": diff_file_path,
                "lines": sorted(unassigned)
            })

    # Sort changed functions for determinism
    changed_functions.sort(key=lambda f: (f["file_path"], f["start_line"], f["id"]))

    # 5. Compute impacted functions using dependency graph
    impact_result = get_impacted_functions(graph_data, changed_function_identifiers)
    impacted_functions = impact_result.get("impacted_functions", [])

    # Sort impacted functions for determinism
    impacted_functions.sort(key=lambda f: (f.get("distance", 1), f["file_path"], f["start_line"]))

    # Success is True if execution finished safely without fatal unhandled error
    # (files with errors are reported in the errors list)
    success = True if not errors else (len(changed_files) > 0 or len(source_files or []) > 0)

    total_unassigned = sum(len(item["lines"]) for item in unassigned_changed_lines)

    summary = {
        "changed_files_count": len(changed_files),
        "changed_functions_count": len(changed_functions),
        "impacted_functions_count": len(impacted_functions),
        "unassigned_lines_count": total_unassigned,
        "errors_count": len(errors)
    }

    return {
        "success": success,
        "changed_files": changed_files,
        "changed_functions": changed_functions,
        "impacted_functions": impacted_functions,
        "unassigned_changed_lines": unassigned_changed_lines,
        "errors": errors,
        "summary": summary
    }
