"""
processor.py — Chunk processor.

Each chunk dict has the shape:
  {
    "chunk_id":   str,
    "type":       "import|global_var|class|function|other|raw_text",
    "name":       str | None,
    "start_line": int,
    "end_line":   int,
    "source":     str,
    "hash":       str,
    "processed":  bool,
    "result":     any,
  }

process_chunk() builds a dependency graph payload for each chunk.
"""

from graph_builder import (
    extract_chunk_graph,
    extract_import_chunk_graph,
    extract_global_var_chunk_graph,
    extract_function_chunk_graph,
    extract_class_chunk_graph,
)


def process_chunk(chunk: dict, project_name: str):
    """
    Process a single chunk.

    Args:
        chunk: the chunk dict (read-only; do not mutate it here).
        project_name: target project root node label.

    Returns:
        A JSON-serialisable result that will be stored in chunk["result"].
    """
    chunk_type = chunk.get("type")
    if chunk_type == "import":
        graph = extract_import_chunk_graph(chunk)
    elif chunk_type == "global_var":
        graph = extract_global_var_chunk_graph(chunk)
    elif chunk_type == "function":
        graph = extract_function_chunk_graph(chunk)
    elif chunk_type == "class":
        graph = extract_class_chunk_graph(chunk)
    else:
        graph = {}
    return {
        "graph": graph,
    }
