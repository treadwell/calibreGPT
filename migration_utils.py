#!/usr/bin/env python3

import json
import os
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
        command,
    ]
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
