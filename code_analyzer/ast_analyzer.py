"""
Python AST Analyzer for ChangeGuard AI.

Parses Python source code using the standard `ast` module to identify which
functions, methods, and classes contain the changed lines identified by the
Git Diff Parser.
"""

import ast
import os
from typing import Any, Dict, List, Optional, Set, Tuple


class _FunctionCollector(ast.NodeVisitor):
    """
    AST Visitor that collects metadata for all functions, methods, and
    nested functions with their line ranges and qualified names.
    """

    def __init__(self) -> None:
        self.functions: List[Dict[str, Any]] = []
        self.scope_stack: List[Tuple[str, str]] = []  # ('class' | 'function', name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(("class", node.name))
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node)

    def _record_function(self, node: ast.AST) -> None:
        parent_scope = [s[1] for s in self.scope_stack]
        qualified_name = ".".join(parent_scope + [node.name]) if parent_scope else node.name

        is_method = bool(self.scope_stack and self.scope_stack[-1][0] == "class")
        parent_class = self.scope_stack[-1][1] if is_method else None

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", None)

        # Fallback to computing end_lineno if unavailable
        if end_line is None:
            end_line = start_line
            for child in ast.walk(node):
                child_end = getattr(child, "end_lineno", None)
                if child_end is not None:
                    end_line = max(end_line, child_end)
                elif hasattr(child, "lineno"):
                    end_line = max(end_line, child.lineno)

        # Effective start line accounts for decorator lines
        effective_start = start_line
        for decorator in getattr(node, "decorator_list", []):
            if hasattr(decorator, "lineno") and decorator.lineno < effective_start:
                effective_start = decorator.lineno

        func_info: Dict[str, Any] = {
            "name": node.name,
            "qualified_name": qualified_name,
            "start_line": start_line,
            "end_line": end_line,
            "effective_start": effective_start,
            "parent_class": parent_class,
            "is_method": is_method,
        }
        self.functions.append(func_info)

        self.scope_stack.append(("function", node.name))
        self.generic_visit(node)
        self.scope_stack.pop()


def analyze_changed_functions_from_source(
    source_code: str,
    changed_lines: List[int],
    file_path: str = ""
) -> Dict[str, Any]:
    """
    Analyze source code string to identify which functions contain the changed line numbers.

    Args:
        source_code: Python source code as a string.
        changed_lines: List of 1-based changed line numbers.
        file_path: Optional file path for reporting.

    Returns:
        Structured dictionary containing identified functions, unassigned lines, and error state.
    """
    if not isinstance(source_code, str):
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": "Invalid source_code: expected string",
            "success": False
        }

    if changed_lines is None:
        changed_lines = []
    elif not isinstance(changed_lines, list):
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": f"Invalid changed_lines: expected list[int], got {type(changed_lines).__name__}",
            "success": False
        }

    # Validate that all changed lines are integers
    validated_lines: List[int] = []
    for line in changed_lines:
        if isinstance(line, int):
            validated_lines.append(line)
        else:
            return {
                "file_path": file_path,
                "functions": [],
                "unassigned_lines": [],
                "error": f"Invalid line number '{line}': line numbers must be integers",
                "success": False
            }

    try:
        tree = ast.parse(source_code, filename=file_path or "<string>")
    except SyntaxError as e:
        line_info = f" (line {e.lineno})" if e.lineno is not None else ""
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": f"Syntax error in '{file_path or '<string>'}'{line_info}: {e.msg}",
            "success": False
        }
    except Exception as e:
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": f"Failed to parse '{file_path or '<string>'}': {str(e)}",
            "success": False
        }

    collector = _FunctionCollector()
    collector.visit(tree)
    all_functions = collector.functions

    # If no lines changed, return clean empty result
    if not validated_lines:
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": None,
            "success": True
        }

    unique_changed_lines = sorted(set(validated_lines))

    # Map each changed line to the innermost matching function
    matched_functions: Dict[str, Dict[str, Any]] = {}
    unassigned_lines: List[int] = []

    for line_num in unique_changed_lines:
        containing = [
            f for f in all_functions
            if f["effective_start"] <= line_num <= f["end_line"]
        ]

        if not containing:
            unassigned_lines.append(line_num)
        else:
            # Choose innermost function (smallest span)
            innermost = min(
                containing,
                key=lambda f: (f["end_line"] - f["effective_start"])
            )
            qname = innermost["qualified_name"]

            if qname not in matched_functions:
                matched_functions[qname] = {
                    "name": innermost["name"],
                    "qualified_name": innermost["qualified_name"],
                    "start_line": innermost["start_line"],
                    "end_line": innermost["end_line"],
                    "parent_class": innermost["parent_class"],
                    "is_method": innermost["is_method"],
                    "changed_lines": [line_num]
                }
            else:
                if line_num not in matched_functions[qname]["changed_lines"]:
                    matched_functions[qname]["changed_lines"].append(line_num)

    # Sort matched functions by start_line
    sorted_functions = sorted(matched_functions.values(), key=lambda f: f["start_line"])

    return {
        "file_path": file_path,
        "functions": sorted_functions,
        "unassigned_lines": sorted(unassigned_lines),
        "error": None,
        "success": True
    }


def analyze_changed_functions(file_path: str, changed_lines: List[int]) -> Dict[str, Any]:
    """
    Read and parse a Python source file to identify functions containing the changed lines.

    Args:
        file_path: Path to the Python source file.
        changed_lines: List of 1-based line numbers that changed.

    Returns:
        dict: A JSON-compatible dictionary:
            {
                "file_path": str,
                "functions": [
                    {
                        "name": str,
                        "qualified_name": str,
                        "start_line": int,
                        "end_line": int,
                        "parent_class": Optional[str],
                        "is_method": bool,
                        "changed_lines": [int, ...]
                    },
                    ...
                ],
                "unassigned_lines": [int, ...],
                "error": Optional[str],
                "success": bool
            }
    """
    if not file_path or not isinstance(file_path, str) or not file_path.strip():
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": "Invalid file path: path must be a non-empty string",
            "success": False
        }

    normalized_path = os.path.normpath(file_path)

    if not os.path.isfile(normalized_path):
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": f"File not found: '{file_path}'",
            "success": False
        }

    try:
        with open(normalized_path, "r", encoding="utf-8") as f:
            source_code = f.read()
    except UnicodeDecodeError:
        try:
            with open(normalized_path, "r", encoding="latin-1") as f:
                source_code = f.read()
        except Exception as e:
            return {
                "file_path": file_path,
                "functions": [],
                "unassigned_lines": [],
                "error": f"Failed to read file '{file_path}': {str(e)}",
                "success": False
            }
    except Exception as e:
        return {
            "file_path": file_path,
            "functions": [],
            "unassigned_lines": [],
            "error": f"Failed to read file '{file_path}': {str(e)}",
            "success": False
        }

    return analyze_changed_functions_from_source(
        source_code=source_code,
        changed_lines=changed_lines,
        file_path=file_path
    )
