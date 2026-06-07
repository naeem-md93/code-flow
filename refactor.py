"""
refactor.py — CLI entry point for the Python project refactoring tool.

Usage:
    python refactor.py /path/to/target/project [--force]

Options:
    --force    Re-process all chunks even if already marked as processed.

Workflow:
    1. Load db.json (or start fresh).
    2. Recursively find all .py files in the target project.
    3. Breadth-first phase: hash/index all files and detect changed files.
    4. Processing phase: for each changed file:
        a. Split into semantic chunks (AST or raw-text fallback).
        b. For each chunk:
            - If chunk hash unchanged and already processed, skip.
            - Otherwise call process_chunk() and record the result.
    5. Update db.json.
    6. Print a summary.
"""

import argparse
import sys
from pathlib import Path

from db import (
    load_db,
    save_db,
    get_project,
    get_chunks,
    set_file_record,
    set_chunks,
    set_file_graph,
    rebuild_project_graph,
    get_stored_chunk_hashes,
)
from scanner import scan_files, hash_file, build_file_record, find_changed_files
from chunker import chunk_file
from processor import process_chunk


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(target_path: Path, force: bool = False) -> None:
    project_key = str(target_path.resolve())
    project_name = target_path.resolve().name
    print(f"Target project : {project_key}")

    db = load_db()
    get_project(db, project_key)  # ensure project entry exists

    all_files = scan_files(target_path)
    print(f"Python files found : {len(all_files)}")

    # Phase 1 (breadth-first): hash/index all files and compute changed files.
    if force:
        changed_files = []
        for path in all_files:
            current_hash = hash_file(path)
            record = build_file_record(path, target_path, current_hash)
            changed_files.append((path, current_hash, record))
    else:
        changed_files = find_changed_files(db, project_key, all_files, target_path)

    print(f"Files changed     : {len(changed_files)}")

    files_scanned = len(all_files)
    files_changed = len(changed_files)
    chunks_total = 0
    chunks_processed = 0
    chunks_skipped = 0

    # Phase 2: chunk/process only files that are new or changed.
    for path, _current_hash, record in changed_files:
        abs_path = str(path.resolve())

        # Build and store the updated file record.
        set_file_record(db, project_key, record)

        # Chunk the file.
        try:
            new_chunks = chunk_file(path)
        except RuntimeError as exc:
            print(f"  [WARN] Could not chunk {abs_path}: {exc}", file=sys.stderr)
            continue

        # Compare chunk hashes to avoid re-processing unchanged chunks.
        old_hashes = get_stored_chunk_hashes(db, project_key, abs_path)
        old_chunks = get_chunks(db, project_key, abs_path)

        for chunk in new_chunks:
            chunks_total += 1
            cid = chunk["chunk_id"]
            old_hash = old_hashes.get(cid)
            old_chunk = old_chunks.get(cid, {}) if isinstance(old_chunks, dict) else {}
            old_processed = bool(old_chunk.get("processed", False))

            if not force and old_hash == chunk["hash"] and old_processed:
                # Chunk unchanged and already processed — preserve old result.
                chunk["result"] = old_chunk.get("result")
                chunk["processed"] = old_processed
                chunks_skipped += 1
                continue

            result = process_chunk(chunk, project_name=project_name)
            chunk["result"] = result
            chunk["processed"] = True
            chunks_processed += 1

        file_nodes: dict[str, dict] = {}
        file_edges: dict[str, dict] = {}
        for chunk in new_chunks:
            graph = (chunk.get("result") or {}).get("graph", {})
            for node in graph.get("nodes", []):
                node_id = node.get("id")
                if node_id and node_id not in file_nodes:
                    file_nodes[node_id] = node
            for edge in graph.get("edges", []):
                src = edge.get("source")
                dst = edge.get("target")
                edge_type = edge.get("type")
                if not src or not dst or not edge_type:
                    continue
                edge_key = f"{src}::{dst}::{edge_type}"
                if edge_key not in file_edges:
                    file_edges[edge_key] = edge

        set_file_graph(
            db,
            project_key,
            abs_path,
            list(file_nodes.values()),
            list(file_edges.values()),
        )
        set_chunks(db, project_key, abs_path, new_chunks)

    rebuild_project_graph(db, project_key)

    save_db(db)

    # Summary
    print("-" * 50)
    print(f"Files scanned    : {files_scanned}")
    print(f"Files changed    : {files_changed}")
    print(f"Chunks total     : {chunks_total}")
    print(f"Chunks processed : {chunks_processed}")
    print(f"Chunks skipped   : {chunks_skipped}")
    print(f"Database saved   : db.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refactor a Python project: scan, chunk, and process all .py files."
    )
    parser.add_argument(
        "target_path",
        type=str,
        help="Absolute or relative path to the target Python project directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-process all chunks even if already marked as processed.",
    )
    args = parser.parse_args()

    target = Path(args.target_path).expanduser().resolve()
    if not target.is_dir():
        print(f"Error: '{target}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    run(target, force=args.force)


if __name__ == "__main__":
    main()
