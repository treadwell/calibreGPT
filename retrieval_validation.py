#!/usr/bin/env python3

import argparse
import json
import os
import statistics
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class QueryCase:
    query: str
    id: str
    expected_book_ids: List[int]


def load_queries(path: str) -> List[QueryCase]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        raise ValueError("Query file must contain a JSON list")
    cases = []
    for i, item in enumerate(payload):
        if not isinstance(item, dict) or "query" not in item:
            raise ValueError(f"Invalid query item at index {i}")
        qid = item.get("id", f"q{i+1}")
        expected = item.get("expected_book_ids", [])
        if not isinstance(expected, list):
            raise ValueError(f"expected_book_ids must be a list for {qid}")
        cases.append(QueryCase(query=item["query"], id=qid, expected_book_ids=[int(x) for x in expected]))
    return cases


def run_search(
    engine_path: str,
    library_path: str,
    embedding_model: str,
    active_model: str,
    query: str,
    top_k: int,
    skip_sync: bool,
) -> List[Dict]:
    fulltext = os.path.join(library_path, "full-text-search.db")
    metadata = os.path.join(library_path, "metadata.db")
    calibregpt = os.path.join(library_path, "calibregpt.db")
    faiss = os.path.join(library_path, "faiss.idx")

    args = [
        "python3",
        engine_path,
        "--fulltext-db",
        fulltext,
        "--metadata-db",
        metadata,
        "--calibregpt-db",
        calibregpt,
        "--faiss-index",
        faiss,
        "--active-embedding-model",
        active_model,
        "--embedding-model",
        embedding_model,
        "--match-count",
        str(top_k),
    ]
    if skip_sync:
        args.append("--skip-sync")
    args.extend(["find-similar-chunks", "--prompt", query])

    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"engine exited {proc.returncode}")
    payload = json.loads(proc.stdout)
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    return payload.get("results", [])


def reciprocal_rank(results: List[int], expected: List[int]) -> float:
    if not expected:
        return 0.0
    expected_set = set(expected)
    for i, book_id in enumerate(results, start=1):
        if book_id in expected_set:
            return 1.0 / i
    return 0.0


def hit_at_k(results: List[int], expected: List[int]) -> int:
    if not expected:
        return 0
    return int(any(book_id in set(expected) for book_id in results))


def overlap_ratio(a: List[int], b: List[int], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(a[:k]).intersection(set(b[:k]))) / float(k)


def summarize(per_query: List[Dict], model_a: str, model_b: str, k: int) -> Dict:
    overlap_values = [item["overlap_at_k"] for item in per_query]
    mrr_a = [item["metrics"][model_a]["rr"] for item in per_query if item["has_expectations"]]
    mrr_b = [item["metrics"][model_b]["rr"] for item in per_query if item["has_expectations"]]
    hit_a = [item["metrics"][model_a]["hit_at_k"] for item in per_query if item["has_expectations"]]
    hit_b = [item["metrics"][model_b]["hit_at_k"] for item in per_query if item["has_expectations"]]

    return {
        "k": k,
        "query_count": len(per_query),
        "query_with_expectations": len(mrr_a),
        "mean_overlap_at_k": round(statistics.mean(overlap_values), 4) if overlap_values else 0.0,
        f"{model_a}_mrr": round(statistics.mean(mrr_a), 4) if mrr_a else None,
        f"{model_b}_mrr": round(statistics.mean(mrr_b), 4) if mrr_b else None,
        f"{model_a}_hit_rate": round(statistics.mean(hit_a), 4) if hit_a else None,
        f"{model_b}_hit_rate": round(statistics.mean(hit_b), 4) if hit_b else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="retrieval_validation")
    parser.add_argument("--engine", default="./engine.py")
    parser.add_argument("--library-path", required=True)
    parser.add_argument("--queries-file", required=True)
    parser.add_argument("--baseline-model", default="text-embedding-ada-002")
    parser.add_argument("--candidate-model", default="text-embedding-3-small")
    parser.add_argument("--active-model", default="text-embedding-ada-002")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--skip-sync", action="store_true", default=True)
    parser.add_argument("--output", default="retrieval_validation_report.json")
    args = parser.parse_args()

    engine_path = os.path.abspath(args.engine)
    if not os.path.exists(engine_path):
        raise ValueError(f"Engine not found: {engine_path}")

    queries = load_queries(args.queries_file)
    per_query = []
    for case in queries:
        base_results = run_search(
            engine_path=engine_path,
            library_path=args.library_path,
            embedding_model=args.baseline_model,
            active_model=args.active_model,
            query=case.query,
            top_k=args.top_k,
            skip_sync=args.skip_sync,
        )
        cand_results = run_search(
            engine_path=engine_path,
            library_path=args.library_path,
            embedding_model=args.candidate_model,
            active_model=args.active_model,
            query=case.query,
            top_k=args.top_k,
            skip_sync=args.skip_sync,
        )

        base_ids = [int(r["book_id"]) for r in base_results]
        cand_ids = [int(r["book_id"]) for r in cand_results]
        has_expectations = len(case.expected_book_ids) > 0
        per_query.append(
            {
                "id": case.id,
                "query": case.query,
                "expected_book_ids": case.expected_book_ids,
                "has_expectations": has_expectations,
                "overlap_at_k": round(overlap_ratio(base_ids, cand_ids, args.top_k), 4),
                "metrics": {
                    args.baseline_model: {
                        "hit_at_k": hit_at_k(base_ids, case.expected_book_ids),
                        "rr": round(reciprocal_rank(base_ids, case.expected_book_ids), 4),
                        "top_book_ids": base_ids[: args.top_k],
                    },
                    args.candidate_model: {
                        "hit_at_k": hit_at_k(cand_ids, case.expected_book_ids),
                        "rr": round(reciprocal_rank(cand_ids, case.expected_book_ids), 4),
                        "top_book_ids": cand_ids[: args.top_k],
                    },
                },
            }
        )

    summary = summarize(per_query, args.baseline_model, args.candidate_model, args.top_k)
    report = {
        "library_path": os.path.abspath(args.library_path),
        "baseline_model": args.baseline_model,
        "candidate_model": args.candidate_model,
        "summary": summary,
        "per_query": per_query,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(summary, indent=2))
    print(f"report_path={os.path.abspath(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
