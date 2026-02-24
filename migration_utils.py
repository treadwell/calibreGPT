#!/usr/bin/env python3

import json
import os
import sqlite3
import subprocess
from typing import Dict, List


def library_db_paths(library_path: str) -> Dict[str, str]:
    return {
        "fulltext": os.path.join(library_path, "full-text-search.db"),
        "metadata": os.path.join(library_path, "metadata.db"),
        "calibregpt": os.path.join(library_path, "calibregpt.db"),
        "faiss": os.path.join(library_path, "faiss.idx"),
    }


def validate_library_path(library_path: str) -> None:
    paths = library_db_paths(library_path)
    for required in ("fulltext", "metadata"):
        if not os.path.exists(paths[required]):
            raise ValueError(f"Missing required database: {paths[required]}")


def _run_engine(
    engine_path: str,
    library_path: str,
    embedding_model: str,
    active_model: str,
    batch_size: int,
    command: str,
    global_args: List[str] = None,
    command_args: List[str] = None,
) -> Dict:
    paths = library_db_paths(library_path)
    args = [
        "python3",
        engine_path,
        "--fulltext-db",
        paths["fulltext"],
        "--metadata-db",
        paths["metadata"],
        "--calibregpt-db",
        paths["calibregpt"],
        "--faiss-index",
        paths["faiss"],
        "--active-embedding-model",
        active_model,
        "--embedding-model",
        embedding_model,
        "--batch-size",
        str(batch_size),
    ]
    if global_args:
        args.extend(global_args)
    args.append(command)
    if command_args:
        args.extend(command_args)
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"engine exited {proc.returncode}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from engine: {proc.stdout[:300]}") from exc
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("results")


def migration_status(
    engine_path: str,
    library_path: str,
    embedding_model: str,
    active_model: str,
    batch_size: int,
) -> Dict:
    return _run_engine(engine_path, library_path, embedding_model, active_model, batch_size, "migration-status")


def migrate_once(
    engine_path: str,
    library_path: str,
    embedding_model: str,
    active_model: str,
    batch_size: int,
) -> Dict:
    token = os.environ.get("OPENAI_TOKEN", "")
    if not token:
        raise RuntimeError("OPENAI_TOKEN is required for migration runs.")
    return _run_engine(engine_path, library_path, embedding_model, active_model, batch_size, "migrate-embeddings")


def search_similar_chunks(
    engine_path: str,
    library_path: str,
    embedding_model: str,
    active_model: str,
    batch_size: int,
    query: str,
    match_count: int,
    skip_sync: bool = True,
) -> List[Dict]:
    global_args = ["--match-count", str(match_count)]
    if skip_sync:
        global_args.append("--skip-sync")
    command_args = ["--prompt", query]
    return _run_engine(
        engine_path,
        library_path,
        embedding_model,
        active_model,
        batch_size,
        "find-similar-chunks",
        global_args=global_args,
        command_args=command_args,
    )


def load_libraries(libraries_file: str, explicit: List[str]) -> List[str]:
    paths: List[str] = []
    if libraries_file:
        with open(libraries_file, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content.startswith("["):
                paths.extend(json.loads(content))
            else:
                for line in content.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        paths.append(line)
    paths.extend(explicit)
    deduped = []
    seen = set()
    for path in paths:
        norm = os.path.abspath(path)
        if norm not in seen:
            seen.add(norm)
            deduped.append(norm)
    if not deduped:
        raise ValueError("No libraries provided. Use --library-path or --libraries-file.")
    for path in deduped:
        validate_library_path(path)
    return deduped


def resolve_book_open_paths(
    library_path: str,
    book_ids: List[int],
    preferred_formats: List[str] = None,
) -> Dict[int, Dict[str, str]]:
    if not book_ids:
        return {}
    if preferred_formats is None:
        preferred_formats = ["PDF", "EPUB", "AZW3", "MOBI", "DOCX", "TXT", "RTF", "MD"]
    rank = {fmt.upper(): i for i, fmt in enumerate(preferred_formats)}
    metadata_db = os.path.join(library_path, "metadata.db")
    conn = sqlite3.connect(metadata_db)
    cursor = conn.cursor()
    placeholders = ",".join(["?" for _ in book_ids])
    cursor.execute(
        f"""
            select d.book, d.format, d.name, b.path
            from data d
            join books b on b.id = d.book
            where d.book in ({placeholders})
        """,
        book_ids,
    )
    rows = cursor.fetchall()
    conn.close()

    best: Dict[int, Dict[str, str]] = {}
    for book_id, fmt, name, rel_path in rows:
        fmt_upper = str(fmt).upper()
        candidate_path = os.path.join(library_path, rel_path, f"{name}.{str(fmt).lower()}")
        if not os.path.exists(candidate_path):
            alt = os.path.join(library_path, rel_path, f"{name}.{fmt}")
            if os.path.exists(alt):
                candidate_path = alt
        score = rank.get(fmt_upper, len(rank) + 1)
        current = best.get(book_id)
        if current is None or score < current["score"]:
            best[book_id] = {
                "path": candidate_path,
                "format": fmt_upper,
                "score": score,
            }
    return {k: {"path": v["path"], "format": v["format"]} for k, v in best.items()}
