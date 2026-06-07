"""
scanner.py — File discovery and SHA-256 hashing.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path


def scan_files(target_path: Path) -> list[Path]:
    """Recursively collect all .py files under target_path."""
    return sorted(target_path.rglob("*.py"))


def hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_file_record(path: Path, target_path: Path, file_hash: str) -> dict:
    """Construct a file record dict ready to be stored in the database."""
    abs_path = str(path.resolve())
    try:
        rel_path = str(path.resolve().relative_to(target_path.resolve()))
    except ValueError:
        rel_path = abs_path

    return {
        "abs_path": abs_path,
        "rel_path": rel_path,
        "hash": file_hash,
        "last_scanned": datetime.now(timezone.utc).isoformat(),
    }


def find_changed_files(
    db: dict,
    project_key: str,
    all_files: list[Path],
    target_path: Path,
) -> list[tuple[Path, str, dict]]:
    """
    Compare each file's current hash against the stored hash.

    Returns a list of (path, current_hash, new_record) tuples for files
    that are new or whose content has changed since the last scan.
    """
    from db import get_stored_file_hash

    changed = []
    for path in all_files:
        current_hash = hash_file(path)
        stored_hash = get_stored_file_hash(db, project_key, str(path.resolve()))
        if current_hash != stored_hash:
            record = build_file_record(path, target_path, current_hash)
            changed.append((path, current_hash, record))
    return changed
