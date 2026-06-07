"""
processor.py — Placeholder chunk processor.

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

Implement process_chunk() to perform whatever transformation or analysis
is needed. Return any JSON-serialisable value; it will be stored in
chunk["result"] and chunk["processed"] will be set to True.
"""


def process_chunk(chunk: dict):
    """
    Process a single chunk.

    TODO: replace this stub with real logic.

    Args:
        chunk: the chunk dict (read-only; do not mutate it here).

    Returns:
        A JSON-serialisable result that will be stored in chunk["result"].
        Return None to indicate no result yet.
    """
    # --- placeholder ---
    return None
