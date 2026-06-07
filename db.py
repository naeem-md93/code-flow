"""
db.py — JSON database persistence helpers.

The database file (db.json) lives in the same directory as this script.
Schema (keyed by target project absolute path):

{
  "/target/project/path": {
    "files": {
      "/abs/path/file.py": {
        "hash": "sha256hex",
        "last_scanned": "ISO-datetime",
        "abs_path": "/abs/path/file.py",
        "rel_path": "relative/file/path/to/project/"
      }
    },
    "chunks": {
      "/abs/file/path": {
          "filepath::start_line::end_line::hash": {
            "chunk_id":   "filepath::type::name::start_line",
            "type":       "import|global_var|class|function|other|raw_text",
            "start_line": 1,
            "end_line":   10,
            "abs_path": "/absolute/path/to/file.py",
            "rel_path": "relative/path/to/file.py",
            "hash":       "sha256hex",
            "processed":  false,
            "result":     null
          }
        }
      }
            }
        },
        "graph": {
            "by_file": {
                "/abs/path/file.py": {
                    "nodes": [
                        {
                            "id": "symbol-id",
                            "label": "symbol-label",
                            "kind": "project|module|symbol",
                            "file": "/abs/path/file.py"
                        }
                    ],
                    "edges": [
                        {
                            "source": "source-id",
                            "target": "target-id",
                            "type": "import|hierarchy|usage|call",
                            "file": "/abs/path/file.py"
                        }
                    ]
                }
            },
            "nodes": [
                {
                    "id": "symbol-id",
                    "label": "symbol-label",
                    "kind": "project|module|symbol"
                }
            ],
            "edges": [
                {
                    "source": "source-id",
                    "target": "target-id",
                    "type": "import|hierarchy|usage|call"
                }
            ]
    }
  }
}
"""

import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "db.json"


def load_db() -> dict:
    """Load the database from disk. Returns an empty dict if not found."""
    if DB_PATH.exists():
        with DB_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_db(db: dict) -> None:
    """Persist the database to disk."""
    with DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Project-level helpers
# ---------------------------------------------------------------------------

def get_project(db: dict, project_path: str) -> dict:
    """Return the sub-dict for a project, creating it if absent."""
    if project_path not in db:
        db[project_path] = {"files": {}, "chunks": {}, "graph": {}}
    entry = db[project_path]
    entry.setdefault("files", {})
    entry.setdefault("chunks", {})
    graph = entry.setdefault("graph", {})
    graph.setdefault("by_file", {})
    graph.setdefault("nodes", [])
    graph.setdefault("edges", [])
    return entry


# ---------------------------------------------------------------------------
# File-record helpers
# ---------------------------------------------------------------------------

def get_file_record(db: dict, project_path: str, abs_path: str) -> dict | None:
    """Return the file record for a given file, or None if not stored."""
    project = get_project(db, project_path)
    return project["files"].get(abs_path)


def set_file_record(db: dict, project_path: str, record: dict) -> None:
    """Upsert a file record. `record` must contain 'abs_path'."""
    project = get_project(db, project_path)
    project["files"][record["abs_path"]] = record


def get_stored_file_hash(db: dict, project_path: str, abs_path: str) -> str | None:
    """Return the stored SHA-256 hash for a file, or None if not found."""
    record = get_file_record(db, project_path, abs_path)
    return record["hash"] if record else None


# ---------------------------------------------------------------------------
# Chunk helpers
# ---------------------------------------------------------------------------

def get_chunks(db: dict, project_path: str, abs_path: str) -> dict | list:
    """Return stored chunks for a file (dict keyed by chunk_id, or legacy list)."""
    project = get_project(db, project_path)
    return project["chunks"].get(abs_path, {})


def set_chunks(db: dict, project_path: str, abs_path: str, chunks: dict | list) -> None:
    """Replace chunks for a file, normalizing to a dict keyed by chunk_id."""
    project = get_project(db, project_path)
    if isinstance(chunks, list):
        project["chunks"][abs_path] = {chunk["chunk_id"]: chunk for chunk in chunks}
    else:
        project["chunks"][abs_path] = chunks


def get_chunk(db: dict, project_path: str, abs_path: str, chunk_id: str) -> dict:
    """Return the chunk dict for a file (may be empty)."""
    chunks = get_chunks(db, project_path, abs_path)
    if isinstance(chunks, list):
        for chunk in chunks:
            if chunk.get("chunk_id") == chunk_id:
                return chunk
        return {}
    return chunks.get(chunk_id, {})


def get_stored_chunk_hash(db: dict, project_path: str, abs_path: str, chunk_id: str) -> str | None:
    """Return a chunk hash."""
    chunk = get_chunk(db, project_path, abs_path, chunk_id)
    return chunk.get("hash")


def get_stored_chunk_hashes(db: dict, project_path: str, abs_path: str) -> dict[str, str]:
    """Return a mapping of chunk_id -> hash for all stored chunks of a file."""
    chunks = get_chunks(db, project_path, abs_path)
    if isinstance(chunks, list):
        return {
            chunk.get("chunk_id"): chunk.get("hash")
            for chunk in chunks
            if chunk.get("chunk_id")
        }
    return {
        chunk_id: chunk.get("hash")
        for chunk_id, chunk in chunks.items()
        if isinstance(chunk, dict)
    }


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def get_graph(db: dict, project_path: str) -> dict:
    """Return the project graph table, creating it if absent."""
    project = get_project(db, project_path)
    graph = project.setdefault("graph", {})
    graph.setdefault("by_file", {})
    graph.setdefault("nodes", [])
    graph.setdefault("edges", [])
    return graph


def set_file_graph(db: dict, project_path: str, abs_path: str, nodes: list[dict], edges: list[dict]) -> None:
    """Replace graph contribution for a single file, then rebuild aggregate graph."""
    graph = get_graph(db, project_path)
    graph["by_file"][abs_path] = {
        "nodes": nodes,
        "edges": edges,
    }


def rebuild_project_graph(db: dict, project_path: str) -> None:
    """Recompute deduplicated project-level graph from per-file graph entries."""
    graph = get_graph(db, project_path)
    by_file = graph.get("by_file", {})

    nodes_by_id: dict[str, dict] = {}
    edges_by_key: dict[str, dict] = {}

    for file_graph in by_file.values():
        for node in file_graph.get("nodes", []):
            node_id = node.get("id")
            if not node_id:
                continue
            if node_id not in nodes_by_id:
                nodes_by_id[node_id] = {
                    "id": node_id,
                    "label": node.get("label", node_id),
                    "kind": node.get("kind", "symbol"),
                }

        for edge in file_graph.get("edges", []):
            src = edge.get("source")
            dst = edge.get("target")
            edge_type = edge.get("type", "usage")
            if not src or not dst:
                continue
            key = f"{src}::{dst}::{edge_type}"
            if key not in edges_by_key:
                edges_by_key[key] = {
                    "source": src,
                    "target": dst,
                    "type": edge_type,
                }

    graph["nodes"] = sorted(nodes_by_id.values(), key=lambda n: n["id"])
    graph["edges"] = sorted(
        edges_by_key.values(),
        key=lambda e: (e["source"], e["target"], e["type"]),
    )
