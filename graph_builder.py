"""
graph_builder.py — Build chunk-level dependency graph payloads.
"""

import ast
import builtins
import keyword
from pathlib import Path


_BUILTIN_NAMES = set(dir(builtins))
_KEYWORDS = set(keyword.kwlist)


def _safe_parse(source: str) -> ast.AST | None:
    """Parse source text and return an AST tree, or None on syntax error."""
    try:
        return ast.parse(source)
    except SyntaxError:
        return None


def _module_label(abs_path: str) -> str:
    """Return module label derived from the file stem."""
    return Path(abs_path).stem


def _node_id(project_name: str, module_name: str, label: str) -> str:
    """Create a deterministic symbol-level node id."""
    return f"{project_name}::{module_name}::{label}"


def _add_node(nodes_by_id: dict[str, dict], node_id: str, label: str, kind: str, abs_path: str) -> None:
    if node_id in nodes_by_id:
        return
    nodes_by_id[node_id] = {
        "id": node_id,
        "label": label,
        "kind": kind,
        "file": abs_path,
    }


def _add_edge(edges_by_key: dict[str, dict], source: str, target: str, edge_type: str, abs_path: str) -> None:
    key = f"{source}::{target}::{edge_type}"
    if key in edges_by_key:
        return
    edges_by_key[key] = {
        "source": source,
        "target": target,
        "type": edge_type,
        "file": abs_path,
    }


def _extract_assigned_names(node: ast.AST) -> set[str]:
    names: set[str] = set()

    def collect(target: ast.AST) -> None:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                collect(item)

    if isinstance(node, ast.Assign):
        for target in node.targets:
            collect(target)
    elif isinstance(node, ast.AnnAssign):
        collect(node.target)
    elif isinstance(node, ast.AugAssign):
        collect(node.target)

    return names


def _call_label(func_node: ast.AST) -> str | None:
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        parts: list[str] = []
        current: ast.AST | None = func_node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
    return None


def _import_nodes_and_edges(
    tree: ast.AST,
    project_name: str,
    module_name: str,
    abs_path: str,
    nodes_by_id: dict[str, dict],
    edges_by_key: dict[str, dict],
) -> None:
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_label = alias.name.split(".")[0]
                module_id = _node_id(project_name, module_name, module_label)
                _add_node(nodes_by_id, module_id, module_label, "symbol", abs_path)

        if isinstance(node, ast.ImportFrom):
            module_label = (node.module or "").split(".")[0]
            if not module_label:
                continue

            module_id = _node_id(project_name, module_name, module_label)
            _add_node(nodes_by_id, module_id, module_label, "symbol", abs_path)

            for alias in node.names:
                if alias.name == "*":
                    continue
                symbol_label = alias.asname or alias.name
                symbol_id = _node_id(project_name, module_name, symbol_label)
                _add_node(nodes_by_id, symbol_id, symbol_label, "symbol", abs_path)
                _add_edge(edges_by_key, module_id, symbol_id, "import", abs_path)


def _defined_symbols(tree: ast.AST) -> set[str]:
    symbols: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
            continue

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            symbols.update(_extract_assigned_names(node))

    return symbols


def _usage_symbols(tree: ast.AST, defined_symbols: set[str]) -> set[str]:
    used: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        if not isinstance(node.ctx, ast.Load):
            continue

        symbol = node.id
        if symbol in defined_symbols:
            continue
        if symbol in _BUILTIN_NAMES or symbol in _KEYWORDS:
            continue

        used.add(symbol)

    return used


def _call_symbols(tree: ast.AST, defined_symbols: set[str]) -> set[str]:
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_label(node.func)
        if not call_name:
            continue
        if call_name in defined_symbols:
            continue
        calls.add(call_name)

    return calls


def extract_chunk_graph(chunk: dict, project_name: str) -> dict:
    """
    Build chunk-level graph with import, hierarchy, usage, and call edges.

    Returns:
        {
          "nodes": [ ... ],
          "edges": [ ... ],
          "project": project_name,
          "module": module_name,
        }
    """
    source = chunk.get("source", "")
    abs_path = chunk.get("abs_path", "")
    module_name = _module_label(abs_path)

    project_id = f"{project_name}::project"
    module_id = f"{project_name}::module::{module_name}"

    nodes_by_id: dict[str, dict] = {}
    edges_by_key: dict[str, dict] = {}

    tree = _safe_parse(source)
    if tree is None:
        return {
            "project": project_name,
            "module": module_name,
            "nodes": [],
            "edges": [],
        }

    _import_nodes_and_edges(
        tree,
        project_name,
        module_name,
        abs_path,
        nodes_by_id,
        edges_by_key,
    )

    defined_symbols = _defined_symbols(tree)

    if defined_symbols:
        _add_node(nodes_by_id, project_id, project_name, "project", abs_path)
        _add_node(nodes_by_id, module_id, module_name, "module", abs_path)
        _add_edge(edges_by_key, project_id, module_id, "hierarchy", abs_path)

    for symbol in defined_symbols:
        symbol_id = _node_id(project_name, module_name, symbol)
        _add_node(nodes_by_id, symbol_id, symbol, "symbol", abs_path)
        _add_edge(edges_by_key, module_id, symbol_id, "hierarchy", abs_path)

    usage_symbols = _usage_symbols(tree, defined_symbols)
    for used in usage_symbols:
        used_id = _node_id(project_name, module_name, used)
        _add_node(nodes_by_id, used_id, used, "symbol", abs_path)
        for defined in defined_symbols:
            defined_id = _node_id(project_name, module_name, defined)
            _add_edge(edges_by_key, used_id, defined_id, "usage", abs_path)

    call_symbols = _call_symbols(tree, defined_symbols)
    for call in call_symbols:
        call_id = _node_id(project_name, module_name, call)
        _add_node(nodes_by_id, call_id, call, "symbol", abs_path)
        for defined in defined_symbols:
            defined_id = _node_id(project_name, module_name, defined)
            _add_edge(edges_by_key, call_id, defined_id, "call", abs_path)

    return {
        "project": project_name,
        "module": module_name,
        "nodes": sorted(nodes_by_id.values(), key=lambda n: n["id"]),
        "edges": sorted(
            edges_by_key.values(),
            key=lambda e: (e["source"], e["target"], e["type"]),
        ),
    }


# ---------------------------------------------------------------------------
# Import-chunk graph
# ---------------------------------------------------------------------------

def _build_dotted_chain(
    parts: list[str],
    nodes_by_id: dict[str, dict],
    edges_by_key: dict[str, dict],
    abs_path: str,
) -> str:
    """
    Create a node for each dotted segment, linking them with 'submodule' edges.
    Returns the qualified id of the last node (e.g. 'a.b.c').
    """
    qualified = ""
    prev_id: str | None = None
    for part in parts:
        qualified = f"{qualified}.{part}" if qualified else part
        _add_node(nodes_by_id, qualified, part, "module", abs_path)
        if prev_id is not None:
            _add_edge(edges_by_key, prev_id, qualified, "submodule", abs_path)
        prev_id = qualified
    return qualified  # id of the last segment


def extract_import_chunk_graph(chunk: dict) -> dict:
    """
    Build a chain graph for an import-type chunk.

    Rules
    -----
    ``import a.b.c``          →  a → b → c          (submodule edges)
    ``import numpy as np``    →  numpy → numpy@np    (alias edge)
    ``from a.b import C``     →  a → b → a.b.C      (submodule + import edges)
    ``from a.b import C as D``→  a → b → a.b.C → a.b.C@D  (+ alias edge)
    Wildcard imports (``from x import *``) are skipped silently.

    Returns
    -------
    {
      "nodes": [ {"id", "label", "kind", "file"}, ... ],
      "edges": [ {"source", "target", "type", "file"}, ... ],
      "module": module_name,
    }
    """
    source = chunk.get("source", "")
    abs_path = chunk.get("abs_path", "")
    module_name = _module_label(abs_path)

    nodes_by_id: dict[str, dict] = {}
    edges_by_key: dict[str, dict] = {}

    tree = _safe_parse(source)
    if tree is None:
        return {"module": module_name, "nodes": [], "edges": []}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                last_id = _build_dotted_chain(parts, nodes_by_id, edges_by_key, abs_path)
                if alias.asname:
                    alias_id = f"{last_id}@{alias.asname}"
                    _add_node(nodes_by_id, alias_id, alias.asname, "alias", abs_path)
                    _add_edge(edges_by_key, last_id, alias_id, "alias", abs_path)

        elif isinstance(node, ast.ImportFrom):
            module_parts = (node.module or "").split(".")
            if not module_parts or not module_parts[0]:
                continue

            last_module_id = _build_dotted_chain(module_parts, nodes_by_id, edges_by_key, abs_path)
            qualified_module = last_module_id  # e.g. "pathlib" or "a.b"

            for alias in node.names:
                if alias.name == "*":
                    continue
                name_id = f"{qualified_module}.{alias.name}"
                _add_node(nodes_by_id, name_id, alias.name, "module", abs_path)
                _add_edge(edges_by_key, last_module_id, name_id, "import", abs_path)
                if alias.asname:
                    alias_id = f"{name_id}@{alias.asname}"
                    _add_node(nodes_by_id, alias_id, alias.asname, "alias", abs_path)
                    _add_edge(edges_by_key, name_id, alias_id, "alias", abs_path)

    return {
        "module": module_name,
        "nodes": sorted(nodes_by_id.values(), key=lambda n: n["id"]),
        "edges": sorted(
            edges_by_key.values(),
            key=lambda e: (e["source"], e["target"], e["type"]),
        ),
    }


# ---------------------------------------------------------------------------
# Global-var chunk graph
# ---------------------------------------------------------------------------

def _rel_path_parts(rel_path: str) -> list[str]:
    """
    Convert a relative file path to a list of dotted-chain parts.

    Example: 'code_flow/graph_builder.py' -> ['code_flow', 'graph_builder']
    """
    return list(Path(rel_path).with_suffix("").parts)


def extract_global_var_chunk_graph(chunk: dict) -> dict:
    """
    Build a chain graph for a global_var chunk.

    Each defined variable is linked to the file that defines it:
        pkg -> pkg.module -> pkg.module.VAR_NAME

    Edge types
    ----------
    ``"submodule"`` -- between path segments (pkg -> pkg.module)
    ``"defines"``   -- from module node to variable node

    Returns
    -------
    {
      "nodes": [ {"id", "label", "kind", "file"}, ... ],
      "edges": [ {"source", "target", "type", "file"}, ... ],
      "module": module_name,
    }
    """
    source = chunk.get("source", "")
    abs_path = chunk.get("abs_path", "")
    rel_path = chunk.get("rel_path", "") or abs_path
    module_name = _module_label(abs_path)

    nodes_by_id: dict[str, dict] = {}
    edges_by_key: dict[str, dict] = {}

    tree = _safe_parse(source)
    if tree is None:
        return {"module": module_name, "nodes": [], "edges": []}

    var_names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            var_names.update(_extract_assigned_names(node))

    if not var_names:
        return {"module": module_name, "nodes": [], "edges": []}

    path_parts = _rel_path_parts(rel_path)
    if not path_parts:
        path_parts = [module_name]

    last_module_id = _build_dotted_chain(path_parts, nodes_by_id, edges_by_key, abs_path)

    for var in sorted(var_names):
        var_id = f"{last_module_id}.{var}"
        _add_node(nodes_by_id, var_id, var, "variable", abs_path)
        _add_edge(edges_by_key, last_module_id, var_id, "defines", abs_path)

    return {
        "module": module_name,
        "nodes": sorted(nodes_by_id.values(), key=lambda n: n["id"]),
        "edges": sorted(
            edges_by_key.values(),
            key=lambda e: (e["source"], e["target"], e["type"]),
        ),
    }


# ---------------------------------------------------------------------------
# Function-chunk graph
# ---------------------------------------------------------------------------

def extract_function_chunk_graph(chunk: dict) -> dict:
    """
    Build a chain graph for a function chunk.

    The function name is linked to the file that defines it:
        pkg -> pkg.module -> pkg.module.func_name

    Edge types
    ----------
    ``"submodule"`` -- between path segments (pkg -> pkg.module)
    ``"defines"``   -- from module node to function node

    Returns
    -------
    {
      "nodes": [ {"id", "label", "kind", "file"}, ... ],
      "edges": [ {"source", "target", "type", "file"}, ... ],
      "module": module_name,
    }
    """
    abs_path = chunk.get("abs_path", "")
    rel_path = chunk.get("rel_path", "") or abs_path
    module_name = _module_label(abs_path)
    func_name = chunk.get("name")

    if not func_name:
        return {"module": module_name, "nodes": [], "edges": []}

    nodes_by_id: dict[str, dict] = {}
    edges_by_key: dict[str, dict] = {}

    path_parts = _rel_path_parts(rel_path)
    if not path_parts:
        path_parts = [module_name]

    last_module_id = _build_dotted_chain(path_parts, nodes_by_id, edges_by_key, abs_path)

    func_id = f"{last_module_id}.{func_name}"
    _add_node(nodes_by_id, func_id, func_name, "function", abs_path)
    _add_edge(edges_by_key, last_module_id, func_id, "defines", abs_path)

    return {
        "module": module_name,
        "nodes": sorted(nodes_by_id.values(), key=lambda n: n["id"]),
        "edges": sorted(
            edges_by_key.values(),
            key=lambda e: (e["source"], e["target"], e["type"]),
        ),
    }


# ---------------------------------------------------------------------------
# Class-chunk graph
# ---------------------------------------------------------------------------

def _build_import_map(tree: ast.AST) -> dict[str, str]:
    """
    Build a mapping from local name -> fully-qualified dotted path for every
    imported name visible in *tree*.

    Examples
    --------
    ``from code_flow.base import BaseBuilder``  ->  {"BaseBuilder": "code_flow.base.BaseBuilder"}
    ``import os``                               ->  {"os": "os"}
    ``import numpy as np``                      ->  {"np": "numpy"}
    """
    import_map: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module_str = node.module or ""
            if not module_str:
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                import_map[local_name] = f"{module_str}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[0]
                import_map[local_name] = alias.name
    return import_map


def _base_qualified_id(base: ast.expr, import_map: dict[str, str]) -> str | None:
    """
    Resolve a base-class AST expression to its fully-qualified dotted id,
    or None if it cannot be resolved via the import map.
    """
    if isinstance(base, ast.Name):
        return import_map.get(base.id)
    if isinstance(base, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = base
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            dotted = ".".join(reversed(parts))
            return import_map.get(dotted, dotted)
    return None


def extract_class_chunk_graph(chunk: dict) -> dict:
    """
    Build a graph for a class chunk.

    Covers
    ------
    - Module path chain:  pkg -> pkg.module -> pkg.module.ClassName
    - Base class chains:  resolved via imports -> inherits edge to subclass
    - Methods:            ClassName -> ClassName.method_name  (defines)
    - Instance variables: from self.x = ... in __init__     (defines)

    Returns
    -------
    {
      "nodes": [ {"id", "label", "kind", "file"}, ... ],
      "edges": [ {"source", "target", "type", "file"}, ... ],
      "module": module_name,
    }
    """
    source = chunk.get("source", "")
    abs_path = chunk.get("abs_path", "")
    rel_path = chunk.get("rel_path", "") or abs_path
    module_name = _module_label(abs_path)
    class_name = chunk.get("name")

    if not class_name:
        return {"module": module_name, "nodes": [], "edges": []}

    nodes_by_id: dict[str, dict] = {}
    edges_by_key: dict[str, dict] = {}

    tree = _safe_parse(source)
    if tree is None:
        return {"module": module_name, "nodes": [], "edges": []}

    import_map = _build_import_map(tree)

    # Module path chain -> class node
    path_parts = _rel_path_parts(rel_path)
    if not path_parts:
        path_parts = [module_name]
    last_module_id = _build_dotted_chain(path_parts, nodes_by_id, edges_by_key, abs_path)

    class_id = f"{last_module_id}.{class_name}"
    _add_node(nodes_by_id, class_id, class_name, "class", abs_path)
    _add_edge(edges_by_key, last_module_id, class_id, "defines", abs_path)

    # Locate the ClassDef node
    class_def: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_def = node
            break

    if class_def is None:
        return {
            "module": module_name,
            "nodes": sorted(nodes_by_id.values(), key=lambda n: n["id"]),
            "edges": sorted(edges_by_key.values(), key=lambda e: (e["source"], e["target"], e["type"])),
        }

    # Base class chains
    for base in class_def.bases:
        qualified = _base_qualified_id(base, import_map)
        if not qualified:
            continue
        base_parts = qualified.split(".")
        base_last_id = _build_dotted_chain(base_parts, nodes_by_id, edges_by_key, abs_path)
        _add_edge(edges_by_key, base_last_id, class_id, "inherits", abs_path)

    # Methods and instance variables
    for item in class_def.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            method_id = f"{class_id}.{item.name}"
            _add_node(nodes_by_id, method_id, item.name, "function", abs_path)
            _add_edge(edges_by_key, class_id, method_id, "defines", abs_path)

            if item.name == "__init__":
                for stmt in ast.walk(item):
                    if not isinstance(stmt, ast.Assign):
                        continue
                    for target in stmt.targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            var_id = f"{class_id}.{target.attr}"
                            _add_node(nodes_by_id, var_id, target.attr, "variable", abs_path)
                            _add_edge(edges_by_key, class_id, var_id, "defines", abs_path)

    return {
        "module": module_name,
        "nodes": sorted(nodes_by_id.values(), key=lambda n: n["id"]),
        "edges": sorted(
            edges_by_key.values(),
            key=lambda e: (e["source"], e["target"], e["type"]),
        ),
    }
