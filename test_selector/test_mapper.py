"""
Test Mapper for ChangeGuard AI.

Discovers pytest test functions and methods, analyzes the application functions
they call (directly, via module imports, aliases, or local test helpers),
and maps tests to unique application function IDs.
"""

import ast
import os
from typing import Any, Dict, List, Optional, Set, Tuple


class _AppFunctionCollector(ast.NodeVisitor):
    """
    Collects all function, method, and class definitions in an application source file.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path.replace("\\", "/")
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[str] = []
        self.scope_stack: List[Tuple[str, str]] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
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
        node_id = f"{self.file_path}:{qualified_name}"
        is_method = bool(self.scope_stack and self.scope_stack[-1][0] == "class")

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno

        self.functions.append({
            "id": node_id,
            "name": node.name,
            "qualified_name": qualified_name,
            "file_path": self.file_path,
            "start_line": start_line,
            "end_line": end_line,
            "is_method": is_method,
            "parent_class": self.scope_stack[-1][1] if is_method else None,
        })

        self.scope_stack.append(("function", node.name))
        self.generic_visit(node)
        self.scope_stack.pop()


class _TestFileVisitor(ast.NodeVisitor):
    """
    Parses a test file to discover test functions, test methods, local helper
    functions, imports, and function calls.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path.replace("\\", "/")
        self.tests: List[Dict[str, Any]] = []
        self.helpers: Dict[str, Dict[str, Any]] = {}
        self.scope_stack: List[Tuple[str, str]] = []
        self.current_function_id: Optional[str] = None
        self.function_calls: Dict[str, List[ast.Call]] = {}

        # Import tracking
        self.imports_from: Dict[str, Tuple[str, str]] = {}  # alias -> (module, original_symbol)
        self.imported_modules: Dict[str, str] = {}          # alias -> original_module

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            asname = alias.asname or alias.name
            self.imported_modules[asname] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            asname = alias.asname or alias.name
            self.imports_from[asname] = (module, alias.name)
        self.generic_visit(node)

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
        func_id = f"{self.file_path}:{qualified_name}"

        is_in_test_class = bool(
            self.scope_stack and self.scope_stack[-1][0] == "class" and self.scope_stack[-1][1].startswith("Test")
        )
        is_top_level_test = bool(not self.scope_stack and node.name.startswith("test_"))
        is_method_test = bool(is_in_test_class and node.name.startswith("test_"))

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", node.lineno) or node.lineno

        self.function_calls[func_id] = []

        # If it's a test function or test method
        if is_top_level_test or is_method_test:
            self.tests.append({
                "id": func_id,
                "name": node.name,
                "qualified_name": qualified_name,
                "file_path": self.file_path,
                "start_line": start_line,
                "end_line": end_line,
                "parent_class": self.scope_stack[-1][1] if is_method_test else None,
                "is_method": is_method_test,
            })
        else:
            # Local helper function or setup method
            self.helpers[node.name] = {
                "id": func_id,
                "name": node.name,
                "qualified_name": qualified_name,
                "file_path": self.file_path,
            }

        prev_func = self.current_function_id
        self.current_function_id = func_id
        self.scope_stack.append(("function", node.name))

        # Visit body
        for item in node.body:
            self.visit(item)

        self.scope_stack.pop()
        self.current_function_id = prev_func

    def visit_Call(self, node: ast.Call) -> None:
        if self.current_function_id:
            self.function_calls[self.current_function_id].append(node)
        self.generic_visit(node)


def discover_test_functions(test_files: List[str]) -> Dict[str, Any]:
    """
    Parse Python test files to discover pytest test functions and methods.

    Discovers:
        - Top-level functions starting with 'test_'
        - Methods starting with 'test_' inside classes starting with 'Test'

    Args:
        test_files: List of paths to Python test files.

    Returns:
        dict:
            {
                "tests": [
                    {
                        "id": str,
                        "name": str,
                        "qualified_name": str,
                        "file_path": str,
                        "start_line": int,
                        "end_line": int,
                        "called_function_names": list[str],
                        "imported_application_symbols": list[str]
                    },
                    ...
                ],
                "errors": [{"file_path": str, "error": str}, ...],
                "success": bool
            }
    """
    if test_files is None or not isinstance(test_files, list):
        return {
            "tests": [],
            "errors": [{"file_path": "", "error": "Invalid input: test_files must be a list of file paths"}],
            "success": False
        }

    tests: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    for file_path in test_files:
        norm_path = os.path.normpath(file_path).replace("\\", "/")

        if not os.path.isfile(norm_path):
            errors.append({
                "file_path": file_path,
                "error": f"File not found: '{file_path}'"
            })
            continue

        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(norm_path, "r", encoding="latin-1") as f:
                    content = f.read()
            except Exception as e:
                errors.append({
                    "file_path": file_path,
                    "error": f"Failed to read file '{file_path}': {str(e)}"
                })
                continue
        except Exception as e:
            errors.append({
                "file_path": file_path,
                "error": f"Failed to read file '{file_path}': {str(e)}"
            })
            continue

        try:
            tree = ast.parse(content, filename=norm_path)
        except SyntaxError as e:
            line_info = f" (line {e.lineno})" if e.lineno is not None else ""
            errors.append({
                "file_path": file_path,
                "error": f"Syntax error in '{file_path}'{line_info}: {e.msg}"
            })
            continue
        except Exception as e:
            errors.append({
                "file_path": file_path,
                "error": f"Failed to parse '{file_path}': {str(e)}"
            })
            continue

        visitor = _TestFileVisitor(norm_path)
        visitor.visit(tree)

        # Collect imported symbols for reporting
        imported_symbols = sorted(list(visitor.imports_from.keys()))

        for t in visitor.tests:
            test_id = t["id"]
            if test_id in seen_ids:
                continue
            seen_ids.add(test_id)

            # Extract called function names from calls made in this test
            called_names: Set[str] = set()
            for call in visitor.function_calls.get(test_id, []):
                if isinstance(call.func, ast.Name):
                    called_names.add(call.func.id)
                elif isinstance(call.func, ast.Attribute):
                    called_names.add(call.func.attr)

            tests.append({
                "id": test_id,
                "name": t["name"],
                "qualified_name": t["qualified_name"],
                "file_path": t["file_path"],
                "start_line": t["start_line"],
                "end_line": t["end_line"],
                "called_function_names": sorted(list(called_names)),
                "imported_application_symbols": imported_symbols
            })

    # Sort discovered tests by file_path and start_line
    tests.sort(key=lambda t: (t["file_path"], t["start_line"], t["id"]))

    success = len(errors) == 0

    return {
        "tests": tests,
        "errors": errors,
        "success": success
    }


def map_tests_to_code(test_files: List[str], app_files: List[str]) -> Dict[str, Any]:
    """
    Map discovered pytest test functions and methods to the application functions
    they exercise.

    Args:
        test_files: List of Python test file paths.
        app_files: List of application Python source file paths.

    Returns:
        dict: A JSON-compatible dictionary containing:
            - test_to_code: dict mapping test_id -> list of app_function_ids
            - code_to_tests: dict mapping app_function_id -> list of test_ids
            - mappings: list of detailed mapping records
            - tests: list of discovered test records
            - errors: list of encountered file/syntax errors
            - success: bool flag indicating overall success
    """
    errors: List[Dict[str, Any]] = []

    if test_files is None or not isinstance(test_files, list):
        errors.append({"file_path": "", "error": "Invalid test_files: expected list of file paths"})
        test_files = []
    if app_files is None or not isinstance(app_files, list):
        errors.append({"file_path": "", "error": "Invalid app_files: expected list of file paths"})
        app_files = []

    # 1. Parse all application files and index their functions
    app_functions_by_id: Dict[str, Dict[str, Any]] = {}
    app_functions_by_file_and_qname: Dict[Tuple[str, str], str] = {}
    app_functions_by_file_and_name: Dict[Tuple[str, str], List[str]] = {}
    app_classes_by_file_and_name: Dict[Tuple[str, str], str] = {}
    file_by_module: Dict[str, str] = {}

    for app_path in app_files:
        norm_app_path = os.path.normpath(app_path).replace("\\", "/")

        if not os.path.isfile(norm_app_path):
            errors.append({"file_path": app_path, "error": f"Application file not found: '{app_path}'"})
            continue

        try:
            with open(norm_app_path, "r", encoding="utf-8") as f:
                code = f.read()
        except UnicodeDecodeError:
            try:
                with open(norm_app_path, "r", encoding="latin-1") as f:
                    code = f.read()
            except Exception as e:
                errors.append({"file_path": app_path, "error": f"Failed to read application file '{app_path}': {str(e)}"})
                continue
        except Exception as e:
            errors.append({"file_path": app_path, "error": f"Failed to read application file '{app_path}': {str(e)}"})
            continue

        try:
            tree = ast.parse(code, filename=norm_app_path)
        except SyntaxError as e:
            line_info = f" (line {e.lineno})" if e.lineno is not None else ""
            errors.append({"file_path": app_path, "error": f"Syntax error in application file '{app_path}'{line_info}: {e.msg}"})
            continue
        except Exception as e:
            errors.append({"file_path": app_path, "error": f"Failed to parse application file '{app_path}': {str(e)}"})
            continue

        collector = _AppFunctionCollector(norm_app_path)
        collector.visit(tree)

        # Build module name indices
        base_name = os.path.basename(norm_app_path)
        mod_name = os.path.splitext(base_name)[0]
        file_by_module[mod_name] = norm_app_path

        path_no_ext = os.path.splitext(norm_app_path)[0]
        dotted = path_no_ext.replace("/", ".").replace("\\", ".")
        file_by_module[dotted] = norm_app_path

        for cls_name in collector.classes:
            app_classes_by_file_and_name[(norm_app_path, cls_name)] = f"{norm_app_path}:{cls_name}"

        for func in collector.functions:
            func_id = func["id"]
            app_functions_by_id[func_id] = func

            fpath = func["file_path"]
            qname = func["qualified_name"]
            fname = func["name"]

            app_functions_by_file_and_qname[(fpath, qname)] = func_id

            if (fpath, fname) not in app_functions_by_file_and_name:
                app_functions_by_file_and_name[(fpath, fname)] = []
            app_functions_by_file_and_name[(fpath, fname)].append(func_id)

    # 2. Parse test files
    discovered_tests: List[Dict[str, Any]] = []
    test_visitors: List[_TestFileVisitor] = []

    for test_path in test_files:
        norm_test_path = os.path.normpath(test_path).replace("\\", "/")

        if not os.path.isfile(norm_test_path):
            errors.append({"file_path": test_path, "error": f"Test file not found: '{test_path}'"})
            continue

        try:
            with open(norm_test_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            try:
                with open(norm_test_path, "r", encoding="latin-1") as f:
                    content = f.read()
            except Exception as e:
                errors.append({"file_path": test_path, "error": f"Failed to read test file '{test_path}': {str(e)}"})
                continue
        except Exception as e:
            errors.append({"file_path": test_path, "error": f"Failed to read test file '{test_path}': {str(e)}" })
            continue

        try:
            tree = ast.parse(content, filename=norm_test_path)
        except SyntaxError as e:
            line_info = f" (line {e.lineno})" if e.lineno is not None else ""
            errors.append({"file_path": test_path, "error": f"Syntax error in test file '{test_path}'{line_info}: {e.msg}"})
            continue
        except Exception as e:
            errors.append({"file_path": test_path, "error": f"Failed to parse test file '{test_path}': {str(e)}"})
            continue

        visitor = _TestFileVisitor(norm_test_path)
        visitor.visit(tree)
        test_visitors.append(visitor)

        imported_symbols = sorted(list(visitor.imports_from.keys()))
        for t in visitor.tests:
            called_names: Set[str] = set()
            for call in visitor.function_calls.get(t["id"], []):
                if isinstance(call.func, ast.Name):
                    called_names.add(call.func.id)
                elif isinstance(call.func, ast.Attribute):
                    called_names.add(call.func.attr)

            discovered_tests.append({
                "id": t["id"],
                "name": t["name"],
                "qualified_name": t["qualified_name"],
                "file_path": t["file_path"],
                "start_line": t["start_line"],
                "end_line": t["end_line"],
                "called_function_names": sorted(list(called_names)),
                "imported_application_symbols": imported_symbols
            })

    # 3. Resolve calls from test functions to application functions
    test_to_code: Dict[str, List[str]] = {}
    code_to_tests: Dict[str, List[str]] = {}
    mappings_list: List[Dict[str, Any]] = []

    def resolve_call_to_app_function(
        call_node: ast.Call,
        visitor: _TestFileVisitor,
        visited_helpers: Optional[Set[str]] = None
    ) -> List[str]:
        """
        Resolve an AST Call node to one or more application function IDs.
        Recursively resolves calls through local helper functions in the test file.
        """
        if visited_helpers is None:
            visited_helpers = set()

        resolved_ids: List[str] = []
        func_expr = call_node.func

        # Helper resolution inside test file
        helper_call_name: Optional[str] = None

        if isinstance(func_expr, ast.Name):
            callee_name = func_expr.id

            # A. Direct / Aliased import: from module import symbol [as alias]
            if callee_name in visitor.imports_from:
                target_mod, original_symbol = visitor.imports_from[callee_name]
                target_file = file_by_module.get(target_mod) or file_by_module.get(target_mod.split(".")[-1])
                if target_file:
                    # Match function or method
                    exact_id = app_functions_by_file_and_qname.get((target_file, original_symbol))
                    if exact_id:
                        resolved_ids.append(exact_id)
                    else:
                        for fid in app_functions_by_file_and_name.get((target_file, original_symbol), []):
                            resolved_ids.append(fid)

                    # Also check if original_symbol was a class, in which case calls to it invoke __init__
                    init_id = app_functions_by_file_and_qname.get((target_file, f"{original_symbol}.__init__"))
                    if init_id and init_id not in resolved_ids:
                        resolved_ids.append(init_id)

            # B. Check local helper function in test file
            elif callee_name in visitor.helpers and callee_name not in visited_helpers:
                helper_call_name = callee_name

        elif isinstance(func_expr, ast.Attribute):
            attr_name = func_expr.attr
            value_expr = func_expr.value

            # A. Module call: import module [as alias]; alias.func()
            if isinstance(value_expr, ast.Name):
                base_id = value_expr.id
                if base_id in visitor.imported_modules:
                    target_mod = visitor.imported_modules[base_id]
                    target_file = file_by_module.get(target_mod) or file_by_module.get(target_mod.split(".")[-1])
                    if target_file:
                        exact_id = app_functions_by_file_and_qname.get((target_file, attr_name))
                        if exact_id:
                            resolved_ids.append(exact_id)
                        else:
                            for fid in app_functions_by_file_and_name.get((target_file, attr_name), []):
                                resolved_ids.append(fid)

                # B. Class method call on imported class: from module import Cls; Cls.method()
                elif base_id in visitor.imports_from:
                    target_mod, original_class = visitor.imports_from[base_id]
                    target_file = file_by_module.get(target_mod) or file_by_module.get(target_mod.split(".")[-1])
                    if target_file:
                        exact_id = app_functions_by_file_and_qname.get((target_file, f"{original_class}.{attr_name}"))
                        if exact_id:
                            resolved_ids.append(exact_id)

                # C. self.helper_method() in a Test* class
                elif base_id == "self" and attr_name in visitor.helpers and attr_name not in visited_helpers:
                    helper_call_name = attr_name

        # If a local helper function was called, trace what the helper calls
        if helper_call_name:
            visited_helpers.add(helper_call_name)
            helper_func_id = visitor.helpers[helper_call_name]["id"]
            for nested_call in visitor.function_calls.get(helper_func_id, []):
                sub_resolved = resolve_call_to_app_function(nested_call, visitor, visited_helpers)
                resolved_ids.extend(sub_resolved)

        return resolved_ids

    # Iterate through all visitors and test functions to compute mappings
    for visitor in test_visitors:
        for t in visitor.tests:
            test_id = t["id"]
            target_app_ids: Set[str] = set()

            for call_node in visitor.function_calls.get(test_id, []):
                resolved = resolve_call_to_app_function(call_node, visitor)
                target_app_ids.update(resolved)

            sorted_app_ids = sorted(list(target_app_ids))
            test_to_code[test_id] = sorted_app_ids

            for app_id in sorted_app_ids:
                if app_id not in code_to_tests:
                    code_to_tests[app_id] = []
                if test_id not in code_to_tests[app_id]:
                    code_to_tests[app_id].append(test_id)

                app_data = app_functions_by_id.get(app_id, {})
                mappings_list.append({
                    "test_id": test_id,
                    "test_name": t["name"],
                    "test_file": t["file_path"],
                    "app_function_id": app_id,
                    "app_function_name": app_data.get("name", ""),
                    "app_function_file": app_data.get("file_path", "")
                })

    # Sort tests and mappings for deterministic output
    discovered_tests.sort(key=lambda t: (t["file_path"], t["start_line"], t["id"]))
    mappings_list.sort(key=lambda m: (m["test_id"], m["app_function_id"]))

    for app_id in code_to_tests:
        code_to_tests[app_id].sort()

    success = len(errors) == 0

    return {
        "test_to_code": test_to_code,
        "code_to_tests": code_to_tests,
        "mappings": mappings_list,
        "tests": discovered_tests,
        "errors": errors,
        "success": success
    }
