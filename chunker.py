"""
chunker.py — Split a Python source file into semantic chunks.

Strategy:
  - Valid Python files  → parse with ast, walk module.body top-level nodes,
                          group consecutive nodes of compatible types, extract
                          raw source text via line slicing.
  - Invalid/unparseable → entire file = one chunk of type 'raw_text'.

Chunk types: import | global_var | class | function | other | raw_text

Grouping rules (applied to consecutive top-level nodes):
  • Import / ImportFrom                         → 'import'   (consecutive ones merge)
  • Assign / AnnAssign / AugAssign (top-level)  → 'global_var' (consecutive ones merge)
  • ClassDef                                    → 'class'    (one chunk per class, no merging)
  • FunctionDef / AsyncFunctionDef              → 'function' (one chunk per function)
  • Everything else                             → 'other'    (consecutive ones merge)
"""

import ast
import hashlib
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _node_category(node: ast.AST) -> str:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return "global_var"
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "function"
    return "other"


def _node_name(node: ast.AST, category: str) -> str | None:
    """Return a human-friendly node name when one exists."""
    if category in ("class", "function"):
        return getattr(node, "name", None)
    return None


def _is_mergeable(category: str) -> bool:
    """Only import, global_var, and other chunks merge across consecutive nodes."""
    return category in ("import", "global_var", "other")


def _extract_lines(lines: list[str], start_line: int, end_line: int) -> str:
    """Extract source lines (1-based, inclusive). Strips trailing blank lines."""
    segment = "".join(lines[start_line - 1 : end_line])
    return segment.rstrip("\n")


def _make_chunk(
    abs_path: str,
    rel_path: str,
    chunk_type: str,
    name: str | None,
    start_line: int,
    end_line: int,
    source: str,
) -> dict:
    
    hash_source = _hash_source(source)
    chunk_id = f"{abs_path}::{start_line}::{end_line}::{hash_source}"
    return {
        "chunk_id": chunk_id,
        "type": chunk_type,
        "abs_path": abs_path,
        "rel_path": rel_path,
        "start_line": start_line,
        "end_line": end_line,
        "source": source,
        "hash": _hash_source(source),
        "processed": False,
        "result": None,
    }


# ---------------------------------------------------------------------------
# AST-based chunking
# ---------------------------------------------------------------------------

def _chunk_via_ast(path: Path, source_text: str) -> list[dict]:
    """Parse the file with ast and produce semantic chunks."""
    try:
        tree = ast.parse(source_text, filename=str(path))
    except SyntaxError:
        return None  # caller falls back to raw_text

    lines = source_text.splitlines(keepends=True)
    file_abs = str(path.resolve())
    file_rel = str(path)
    chunks: list[dict] = []

    # Each group: (category, name, start_line, end_line, [nodes])
    # We flush the current group when the category changes or a non-mergeable
    # chunk (class / function) is encountered.
    current_category: str | None = None
    group_start: int | None = None
    group_end: int | None = None
    group_name: str | None = None

    def flush_group():
        nonlocal current_category, group_start, group_end, group_name
        if current_category is None:
            return
        src = _extract_lines(lines, group_start, group_end)
        chunks.append(
            _make_chunk(file_abs, file_rel, current_category, group_name, group_start, group_end, src)
        )
        current_category = None
        group_start = None
        group_end = None
        group_name = None

    for node in tree.body:
        # ast end_lineno is available from Python 3.8+
        node_start = node.lineno
        node_end = getattr(node, "end_lineno", node.lineno)
        category = _node_category(node)
        name = _node_name(node, category)

        if not _is_mergeable(category):
            # Flush previous group, emit this node as its own chunk.
            flush_group()
            src = _extract_lines(lines, node_start, node_end)
            chunks.append(_make_chunk(file_abs, file_rel, category, name, node_start, node_end, src))
        else:
            if current_category == category:
                # Extend current group.
                group_end = node_end
            else:
                flush_group()
                current_category = category
                group_start = node_start
                group_end = node_end
                group_name = None  # merged groups have no single name

    flush_group()
    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_file(path: Path) -> list[dict]:
    """
    Return a list of chunk dicts for a .py file.

    Falls back to a single 'raw_text' chunk if the file cannot be parsed.
    """
    try:
        source_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc

    file_abs = str(path.resolve())

    # Try AST path first.
    ast_chunks = _chunk_via_ast(path, source_text)
    if ast_chunks is not None:
        return ast_chunks

    # Fallback: entire file as raw_text.
    source = source_text.rstrip("\n")
    lines = source_text.splitlines()
    return [
        _make_chunk(
            file_abs,
            str(path),
            "raw_text",
            None,
            1,
            len(lines) or 1,
            source,
        )
    ]
