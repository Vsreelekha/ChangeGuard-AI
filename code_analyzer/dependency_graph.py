"""
NetworkX Dependency Graph for ChangeGuard AI.

Constructs directed function dependency graphs (caller -> callee) from Python
source files using Python AST and NetworkX, and computes transitive change impact.
"""

import ast
import os
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import networkx as nx


class _SourceVisitor(ast.NodeVisitor):
    """
    AST Visitor that collects function definitions, import mappings,
    and function calls within a single Python source file.
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path.replace("\\", "/")
        self.functions: List[Dict[str, Any]] = []
        self.scope_stack: List[Tuple[str, str]] = []  # ('class' | 'function', name)
        self.function_stack: List[str] = []           # Stack of function node IDs
        self.calls: List[Tuple[str, ast.AST]] = []     # (caller_node_id, call_node)
        self.imports_from: Dict[str, Tuple[str, str]] = {}  # alias -> (module, original_name)
        self.imported_modules: Dict[str, str] = {}          # alias -> module_name

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            asname = alias.asname or alias.name
            self.imported_modules[asname] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        # Handle relative import level
        if node.level > 0:
            current_dir = os.path.dirname(self.file_path).replace("\\", "/")
            parts = current_dir.split("/") if current_dir else []
            # Level 1 is current dir, level 2 is parent dir, etc.
            back_steps = node.level - 1
            if back_steps > 0 and len(parts) >= back_steps:
                parts = parts[:-back_steps]
            rel_prefix = ".".join(parts)
            if rel_prefix and module:
                module = f"{rel_prefix}.{module}"
            elif rel_prefix:
                module = rel_prefix

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
        node_id = f"{self.file_path}:{qualified_name}"

        is_method = bool(self.scope_stack and self.scope_stack[-1][0] == "class")
        is_nested = bool(self.scope_stack and self.scope_stack[-1][0] == "function")

        if is_method:
            function_type = "method"
        elif is_nested:
            function_type = "nested function"
        else:
            function_type = "function"

        parent_class = self.scope_stack[-1][1] if is_method else None

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", None)
        if end_line is None:
            end_line = start_line
            for child in ast.walk(node):
                child_end = getattr(child, "end_lineno", None)
                if child_end is not None:
                    end_line = max(end_line, child_end)
                elif hasattr(child, "lineno"):
                    end_line = max(end_line, child.lineno)

        func_info: Dict[str, Any] = {
            "id": node_id,
            "name": node.name,
            "qualified_name": qualified_name,
            "file_path": self.file_path,
            "start_line": start_line,
            "end_line": end_line,
            "function_type": function_type,
            "parent_class": parent_class,
        }
        self.functions.append(func_info)

        # Track caller scope for calls made within this function
        self.scope_stack.append(("function", node.name))
        self.function_stack.append(node_id)

        # Visit function body to discover nested constructs and calls
        for item in node.body:
            self.visit(item)

        self.function_stack.pop()
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if self.function_stack:
            caller_id = self.function_stack[-1]
            self.calls.append((caller_id, node))
        self.generic_visit(node)


def build_networkx_digraph(source_files: List[str]) -> Tuple[nx.DiGraph, List[Dict[str, Any]]]:
    """
    Construct a NetworkX DiGraph from a list of Python source files.

    Directed edges point from the CALLER to the CALLEE (caller -> callee).

    Args:
        source_files: List of paths to Python source files.

    Returns:
        tuple: (nx.DiGraph, errors_list)
    """
    graph = nx.DiGraph()
    errors: List[Dict[str, Any]] = []

    visitors: List[_SourceVisitor] = []
    # Map normalized path -> visitor
    visitor_by_path: Dict[str, _SourceVisitor] = {}

    for file_path in source_files:
        norm_path = os.path.normpath(file_path).replace("\\", "/")

        if not os.path.isfile(norm_path):
            errors.append({
                "file_path": file_path,
                "error": f"File not found: '{file_path}'"
            })
            continue

        try:
            with open(norm_path, "r", encoding="utf-8") as f:
                source_code = f.read()
        except UnicodeDecodeError:
            try:
                with open(norm_path, "r", encoding="latin-1") as f:
                    source_code = f.read()
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
            tree = ast.parse(source_code, filename=norm_path)
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

        visitor = _SourceVisitor(norm_path)
        visitor.visit(tree)
        visitors.append(visitor)
        visitor_by_path[norm_path] = visitor

    # Index all function nodes across all files
    nodes_by_id: Dict[str, Dict[str, Any]] = {}
    nodes_by_file_and_qname: Dict[Tuple[str, str], str] = {}
    nodes_by_file_and_name: Dict[Tuple[str, str], List[str]] = {}
    nodes_by_name: Dict[str, List[str]] = {}

    for visitor in visitors:
        for func in visitor.functions:
            node_id = func["id"]
            nodes_by_id[node_id] = func
            graph.add_node(
                node_id,
                name=func["name"],
                qualified_name=func["qualified_name"],
                file_path=func["file_path"],
                start_line=func["start_line"],
                end_line=func["end_line"],
                function_type=func["function_type"],
                parent_class=func.get("parent_class")
            )

            fpath = func["file_path"]
            qname = func["qualified_name"]
            fname = func["name"]

            nodes_by_file_and_qname[(fpath, qname)] = node_id

            if (fpath, fname) not in nodes_by_file_and_name:
                nodes_by_file_and_name[(fpath, fname)] = []
            nodes_by_file_and_name[(fpath, fname)].append(node_id)

            if fname not in nodes_by_name:
                nodes_by_name[fname] = []
            nodes_by_name[fname].append(node_id)

    # Build module resolution index
    file_by_module: Dict[str, str] = {}
    for norm_path in visitor_by_path.keys():
        basename = os.path.basename(norm_path)
        mod_name = os.path.splitext(basename)[0]
        file_by_module[mod_name] = norm_path

        # Also map dotted paths (e.g. services.billing)
        path_without_ext = os.path.splitext(norm_path)[0]
        dotted = path_without_ext.replace("/", ".").replace("\\", ".")
        file_by_module[dotted] = norm_path

    # Resolve call edges
    for visitor in visitors:
        source_file = visitor.file_path

        for caller_id, call_node in visitor.calls:
            caller_info = nodes_by_id.get(caller_id, {})
            caller_parent_class = caller_info.get("parent_class")
            target_node_id: Optional[str] = None

            func_expr = call_node.func

            # Case 1: Simple Name call (e.g. calculate(), helper())
            if isinstance(func_expr, ast.Name):
                callee_name = func_expr.id

                # A. Check if imported via "from module import callee_name"
                if callee_name in visitor.imports_from:
                    target_mod, original_symbol = visitor.imports_from[callee_name]
                    target_file = file_by_module.get(target_mod)
                    if not target_file:
                        # Try relative resolution
                        mod_base = target_mod.split(".")[-1]
                        target_file = file_by_module.get(mod_base)

                    if target_file:
                        # Look for target symbol in target file
                        q_match = nodes_by_file_and_qname.get((target_file, original_symbol))
                        if q_match:
                            target_node_id = q_match
                        else:
                            name_matches = nodes_by_file_and_name.get((target_file, original_symbol), [])
                            if name_matches:
                                target_node_id = name_matches[0]

                # B. Check local functions / sibling functions in the same file
                if not target_node_id:
                    # If caller is inside a class, check class method call
                    if caller_parent_class:
                        class_method_id = nodes_by_file_and_qname.get(
                            (source_file, f"{caller_parent_class}.{callee_name}")
                        )
                        if class_method_id:
                            target_node_id = class_method_id

                    # Check nested or top-level function in same file
                    if not target_node_id:
                        # Match exact qualified name if nested or top-level
                        local_matches = nodes_by_file_and_name.get((source_file, callee_name), [])
                        if local_matches:
                            # Prefer local match closest in hierarchy
                            target_node_id = local_matches[0]

            # Case 2: Attribute call (e.g. self.helper(), module.func(), Class.method())
            elif isinstance(func_expr, ast.Attribute):
                attr_name = func_expr.attr
                value_expr = func_expr.value

                # A. self.method() or cls.method()
                if isinstance(value_expr, ast.Name) and value_expr.id in ("self", "cls"):
                    if caller_parent_class:
                        target_node_id = nodes_by_file_and_qname.get(
                            (source_file, f"{caller_parent_class}.{attr_name}")
                        )

                # B. module.func() or ClassName.method()
                elif isinstance(value_expr, ast.Name):
                    base_id = value_expr.id

                    # Check if base_id is an imported module (e.g. import billing; billing.calc())
                    if base_id in visitor.imported_modules:
                        target_mod = visitor.imported_modules[base_id]
                        target_file = file_by_module.get(target_mod) or file_by_module.get(target_mod.split(".")[-1])
                        if target_file:
                            q_match = nodes_by_file_and_qname.get((target_file, attr_name))
                            if q_match:
                                target_node_id = q_match
                            else:
                                name_matches = nodes_by_file_and_name.get((target_file, attr_name), [])
                                if name_matches:
                                    target_node_id = name_matches[0]

                    # Check if base_id is a class in the same file
                    if not target_node_id:
                        target_node_id = nodes_by_file_and_qname.get(
                            (source_file, f"{base_id}.{attr_name}")
                        )

                    # Check if base_id is an imported class
                    if not target_node_id and base_id in visitor.imports_from:
                        target_mod, original_class = visitor.imports_from[base_id]
                        target_file = file_by_module.get(target_mod) or file_by_module.get(target_mod.split(".")[-1])
                        if target_file:
                            target_node_id = nodes_by_file_and_qname.get(
                                (target_file, f"{original_class}.{attr_name}")
                            )

            # Add edge if callee was successfully resolved to a known node
            if target_node_id and target_node_id in graph:
                # Directed edge: caller -> callee
                graph.add_edge(caller_id, target_node_id)

    return graph, errors


def build_dependency_graph(source_files: List[str]) -> Dict[str, Any]:
    """
    Build a directed function dependency graph from Python source files.

    Args:
        source_files: List of Python source file paths.

    Returns:
        dict: A JSON-compatible dictionary representing the dependency graph:
            {
                "nodes": [
                    {
                        "id": str,
                        "name": str,
                        "qualified_name": str,
                        "file_path": str,
                        "start_line": int,
                        "end_line": int,
                        "function_type": "function" | "method" | "nested function"
                    },
                    ...
                ],
                "edges": [
                    {
                        "caller": str,
                        "callee": str
                    },
                    ...
                ],
                "errors": [
                    {"file_path": str, "error": str},
                    ...
                ],
                "success": bool
            }
    """
    if source_files is None or not isinstance(source_files, list):
        return {
            "nodes": [],
            "edges": [],
            "errors": [{"file_path": "", "error": "Invalid input: source_files must be a list of file paths"}],
            "success": False
        }

    graph, errors = build_networkx_digraph(source_files)

    nodes_list: List[Dict[str, Any]] = []
    for node_id, data in graph.nodes(data=True):
        nodes_list.append({
            "id": node_id,
            "name": data.get("name", ""),
            "qualified_name": data.get("qualified_name", ""),
            "file_path": data.get("file_path", ""),
            "start_line": data.get("start_line", 0),
            "end_line": data.get("end_line", 0),
            "function_type": data.get("function_type", "function")
        })

    # Sort nodes by file_path and start_line for deterministic output
    nodes_list.sort(key=lambda n: (n["file_path"], n["start_line"], n["id"]))

    edges_list: List[Dict[str, str]] = []
    for u, v in graph.edges():
        edges_list.append({
            "caller": u,
            "callee": v
        })
    edges_list.sort(key=lambda e: (e["caller"], e["callee"]))

    # success is True if at least one file was processed without fatal block or errors is empty
    success = len(errors) == 0

    return {
        "nodes": nodes_list,
        "edges": edges_list,
        "errors": errors,
        "success": success
    }


def _ensure_networkx_graph(graph: Union[nx.DiGraph, Dict[str, Any]]) -> nx.DiGraph:
    """
    Convert a dictionary representation of a dependency graph back to an nx.DiGraph
    if needed, or return the DiGraph directly.
    """
    if isinstance(graph, nx.DiGraph):
        return graph

    if isinstance(graph, dict):
        g = nx.DiGraph()
        for node in graph.get("nodes", []):
            node_id = node["id"]
            g.add_node(
                node_id,
                name=node.get("name", ""),
                qualified_name=node.get("qualified_name", ""),
                file_path=node.get("file_path", ""),
                start_line=node.get("start_line", 0),
                end_line=node.get("end_line", 0),
                function_type=node.get("function_type", "function")
            )
        for edge in graph.get("edges", []):
            g.add_edge(edge["caller"], edge["callee"])
        return g

    raise TypeError(f"Expected NetworkX DiGraph or graph dictionary, got {type(graph).__name__}")


def get_impacted_functions(
    graph: Union[nx.DiGraph, Dict[str, Any]],
    changed_functions: List[str]
) -> Dict[str, Any]:
    """
    Compute all transitively impacted functions that directly or indirectly
    depend on (call) the specified changed functions.

    Args:
        graph: NetworkX DiGraph or dictionary returned by build_dependency_graph.
        changed_functions: List of function identifiers or qualified names that changed.

    Returns:
        dict: A JSON-compatible dictionary:
            {
                "impacted_functions": [
                    {
                        "id": str,
                        "name": str,
                        "qualified_name": str,
                        "file_path": str,
                        "function_type": str,
                        "start_line": int,
                        "end_line": int,
                        "reason": str,
                        "distance": int
                    },
                    ...
                ],
                "changed_functions": list[str],
                "unknown_functions": list[str],
                "success": bool
            }
    """
    if changed_functions is None or not isinstance(changed_functions, list):
        return {
            "impacted_functions": [],
            "changed_functions": [],
            "unknown_functions": [],
            "success": False
        }

    try:
        g = _ensure_networkx_graph(graph)
    except Exception as e:
        return {
            "impacted_functions": [],
            "changed_functions": changed_functions,
            "unknown_functions": [],
            "error": str(e),
            "success": False
        }

    # Resolve changed function identifiers to known graph node IDs
    resolved_changed_nodes: Set[str] = set()
    unknown_functions: List[str] = []

    for item in changed_functions:
        if not isinstance(item, str):
            unknown_functions.append(str(item))
            continue

        if item in g:
            resolved_changed_nodes.add(item)
        else:
            # Try fuzzy matching by qualified name or name suffix
            matches = [
                n for n, d in g.nodes(data=True)
                if d.get("qualified_name") == item
                or d.get("name") == item
                or n.endswith(f":{item}")
                or n.endswith(f".{item}")
            ]
            if matches:
                for m in matches:
                    resolved_changed_nodes.add(m)
            else:
                unknown_functions.append(item)

    # Find all callers (ancestors in caller -> callee graph)
    impacted_nodes_set: Set[str] = set()
    for changed_id in resolved_changed_nodes:
        if changed_id in g:
            # nx.ancestors returns all nodes that have a directed path TO changed_id
            callers = nx.ancestors(g, changed_id)
            impacted_nodes_set.update(callers)

    # Exclude changed functions themselves
    impacted_nodes_set.difference_update(resolved_changed_nodes)

    # Determine explanation / reason and shortest distance for each impacted function
    impacted_functions: List[Dict[str, Any]] = []

    for node_id in impacted_nodes_set:
        data = g.nodes[node_id]

        best_path: Optional[List[str]] = None
        target_changed: Optional[str] = None

        for changed_id in resolved_changed_nodes:
            if nx.has_path(g, source=node_id, target=changed_id):
                path = nx.shortest_path(g, source=node_id, target=changed_id)
                if best_path is None or len(path) < len(best_path):
                    best_path = path
                    target_changed = changed_id

        if best_path and target_changed:
            distance = len(best_path) - 1
            changed_display = g.nodes[target_changed].get("name", target_changed)

            if distance == 1:
                reason = f"Directly calls '{changed_display}'"
            else:
                via_chain = " -> ".join(
                    g.nodes[step].get("name", step) for step in best_path[1:-1]
                )
                reason = f"Transitively calls '{changed_display}' via {via_chain}"
        else:
            distance = 1
            reason = "Calls changed function"

        impacted_functions.append({
            "id": node_id,
            "name": data.get("name", ""),
            "qualified_name": data.get("qualified_name", ""),
            "file_path": data.get("file_path", ""),
            "function_type": data.get("function_type", "function"),
            "start_line": data.get("start_line", 0),
            "end_line": data.get("end_line", 0),
            "reason": reason,
            "distance": distance
        })

    # Sort impacted functions by distance, then file_path, then start_line
    impacted_functions.sort(key=lambda f: (f["distance"], f["file_path"], f["start_line"]))

    return {
        "impacted_functions": impacted_functions,
        "changed_functions": list(resolved_changed_nodes),
        "unknown_functions": unknown_functions,
        "success": True
    }
