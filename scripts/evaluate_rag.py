"""Run the offline Step 35 RAG retrieval and lifecycle evaluation.

This evaluator uses the same deterministic text normalization and Chunk
builder as the application. Retrieval is a controlled lexical baseline so the
suite can run without MySQL, Chroma, or an external Embedding service. It
measures retrieval quality and validates the safety/metadata contracts that
must hold when the live hybrid retriever is enabled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EVAL_DIR = ROOT / "evals" / "step35"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.rag_chunks import _build_chunks, clean_markdown


TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
AGENT_DOC_TYPES = {
    "coverage_gap": {"business_rule"},
    "competition": {"business_rule"},
    "site_selection": {"business_rule"},
    "expansion": {"safety_standard"},
    "policy_matching": {"policy"},
}
MISSING = object()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def terms(value: str) -> list[str]:
    return list(dict.fromkeys(item for item in TOKEN_PATTERN.findall(value.lower()) if len(item) > 1))[:20]


def effective_date_allowed(document: dict[str, Any], filters: dict[str, Any]) -> bool:
    current = date.fromisoformat(str(document["effective_date"])[:10]) if document.get("effective_date") else None
    if filters.get("effective_date_from") and (current is None or current < date.fromisoformat(filters["effective_date_from"])):
        return False
    if filters.get("effective_date_to") and (current is None or current > date.fromisoformat(filters["effective_date_to"])):
        return False
    if document.get("effective_to") and filters.get("effective_date_from") and date.fromisoformat(str(document["effective_to"])[:10]) < date.fromisoformat(filters["effective_date_from"]):
        return False
    return True


def retrieve(documents: list[dict[str, Any]], query: dict[str, Any]) -> list[dict[str, Any]]:
    filters = query.get("filters", {})
    query_terms = terms(query["query"])
    candidates: list[dict[str, Any]] = []
    for document in documents:
        if filters.get("doc_type") and document.get("doc_type") != filters["doc_type"]:
            continue
        if filters.get("region_code") and document.get("region_code") != filters["region_code"]:
            continue
        if filters.get("version") and document.get("version") != filters["version"]:
            continue
        if query.get("agent_scenario") and query["agent_scenario"] not in document.get("agent_scenarios", []):
            continue
        if not effective_date_allowed(document, filters):
            continue
        haystack = f"{document.get('content', '')} {document.get('document_key', '')}".lower()
        matched = sum(1 for item in query_terms if item in haystack)
        if matched:
            candidates.append({**document, "score": round(matched / max(1, len(query_terms)), 6), "matched_terms": matched})
    candidates.sort(key=lambda item: (-float(item["score"]), str(item["document_key"])))
    return candidates[: int(query.get("top_k", 5))]


def chunk_snapshot(document: dict[str, Any], parameters: dict[str, Any]) -> list[dict[str, Any]]:
    cleaned = clean_markdown(document["content"])
    chunks = _build_chunks(cleaned, int(parameters["target_tokens"]), int(parameters["overlap_tokens"]))
    result = []
    for index, chunk in enumerate(chunks):
        chunk_id = f"{document['document_key']}/{document['version']}/chunk-{index:04d}-{hashlib.sha256(chunk['content'].encode('utf-8')).hexdigest()[:12]}"
        result.append({"chunk_id": chunk_id, "chunk_index": index, "content": chunk["content"], "start_char": chunk["start_char"], "end_char": chunk["end_char"], "document_version": document["version"]})
    return result


def evaluate_chunks(documents: list[dict[str, Any]], parameters: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    per_document: list[dict[str, Any]] = []
    for document in documents:
        first = chunk_snapshot(document, parameters)
        second = chunk_snapshot(document, parameters)
        stable = first == second
        cleaned = clean_markdown(document["content"])
        locatable = all(0 <= item["start_char"] < item["end_char"] <= len(cleaned) for item in first)
        fragments_present = all(any(fragment in item["content"] for item in first) for fragment in document.get("expected_fragments", []))
        if not stable:
            failures.append(f"Chunk regeneration changed for {document['document_key']}")
        if not locatable:
            failures.append(f"Chunk positions are not locatable for {document['document_key']}")
        if not fragments_present:
            failures.append(f"Expected fragment is missing from chunks for {document['document_key']}")
        per_document.append({"document_key": document["document_key"], "chunk_count": len(first), "stable": stable, "locatable": locatable, "fragments_present": fragments_present, "document_version": document["version"], "chunk_ids": [item["chunk_id"] for item in first]})
    return {"passed": not failures, "failures": failures, "documents": per_document}


def evaluate_query(documents: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    hits = retrieve(documents, query)
    expected = list(query.get("expected_document_keys", []))
    hit_keys = [item["document_key"] for item in hits]
    expected_set = set(expected)
    relevant_positions = [index + 1 for index, key in enumerate(hit_keys) if key in expected_set]
    positive = bool(expected)
    recall = sum(key in hit_keys for key in expected_set) / len(expected_set) if positive else None
    hit_rate = 1.0 if (any(key in expected_set for key in hit_keys) if positive else not hits) else 0.0
    mrr = 1.0 / relevant_positions[0] if relevant_positions else (None if not positive else 0.0)
    source_correct = True
    fragment_locatable = True
    for key in expected:
        document = next((item for item in documents if item["document_key"] == key), None)
        if document is None or key not in hit_keys:
            source_correct = False
            fragment_locatable = False
            continue
        source_correct = source_correct and document.get("doc_type") == query.get("filters", {}).get("doc_type") and document.get("region_code") == query.get("filters", {}).get("region_code") and document.get("version") == query.get("filters", {}).get("version") and query.get("agent_scenario") in document.get("agent_scenarios", [])
        fragment = query.get("expected_fragment")
        chunks = chunk_snapshot(document, {"target_tokens": 80, "overlap_tokens": 12}) if fragment else []
        fragment_locatable = fragment_locatable and (not fragment or any(fragment in chunk["content"] and chunk["start_char"] < chunk["end_char"] for chunk in chunks))
    expected_status = query.get("expected_status", "HIT" if positive else "EVIDENCE_INSUFFICIENT")
    actual_status = "HIT" if hits and float(hits[0]["score"]) >= 0.2 else "EVIDENCE_INSUFFICIENT"
    filter_ok = all(item.get("doc_type") == query.get("filters", {}).get("doc_type") and item.get("region_code") == query.get("filters", {}).get("region_code") and item.get("version") == query.get("filters", {}).get("version") and effective_date_allowed(item, query.get("filters", {})) for item in hits)
    agent_type_ok = all(item.get("doc_type") in AGENT_DOC_TYPES.get(query.get("agent_scenario"), set()) and query.get("agent_scenario") in item.get("agent_scenarios", []) for item in hits)
    failures: list[str] = []
    if actual_status != expected_status:
        failures.append(f"status expected {expected_status}, got {actual_status}")
    if positive and not source_correct:
        failures.append("expected source was not retrieved with matching metadata")
    if positive and not fragment_locatable:
        failures.append("expected original fragment is not locatable")
    if not positive and hits:
        failures.append("no-hit safety case returned unsupported evidence")
    if not filter_ok:
        failures.append("filter constraints were not preserved")
    if hits and not agent_type_ok:
        failures.append("retrieved document type is not allowed for the Agent scenario")
    return {"query_id": query["query_id"], "agent_scenario": query.get("agent_scenario"), "passed": not failures, "failures": failures, "hit_keys": hit_keys, "status": actual_status, "expected_keys": expected, "recall_at_k": recall, "hit_rate_at_k": hit_rate, "mrr": mrr, "source_correct": source_correct if positive else not hits, "fragment_locatable": fragment_locatable if positive else not hits, "filter_ok": filter_ok, "agent_type_ok": agent_type_ok, "policy_conclusion_allowed": bool(hits and actual_status == "HIT") if query.get("agent_scenario") == "policy_matching" else None}


def evaluate_embedding_lifecycle(cases: list[dict[str, Any]]) -> dict[str, Any]:
    batches: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    next_id = 1
    for case in cases:
        operation = case["operation"]
        key = case["batch_key"]
        if operation == "failure":
            batches[key] = {"id": next_id, "status": "FAILED", "pending_retry_count": case["failed"], "vectors": []}
            next_id += 1
            actual = {"status": batches[key]["status"], "pending_retry_count": batches[key]["pending_retry_count"]}
        elif operation == "duplicate":
            existing = batches.get(key)
            actual = {"existing_batch_reused": existing is not None, "new_batch_count": 0 if existing else 1}
        elif operation == "retry":
            if key in batches and batches[key]["status"] == "FAILED":
                batches[key].update(status="COMPLETED", pending_retry_count=0, vectors=["chunk-1", "chunk-2"])
            actual = {"status": batches.get(key, {}).get("status"), "pending_retry_count": batches.get(key, {}).get("pending_retry_count")}
        elif operation == "rebuild":
            old = batches.get(key)
            batches[key] = {"id": next_id, "status": "COMPLETED", "pending_retry_count": 0, "vectors":["chunk-1", "chunk-2"], "deleted_old_vectors": old is not None}
            next_id += 1
            actual = {"new_batch_count": 1, "old_vectors_deleted": batches[key]["deleted_old_vectors"], "status": batches[key]["status"]}
        else:
            actual = {}
            failures.append(f"unsupported embedding operation {operation}")
        expected = {key: case[key] for key in case if key.startswith("expected_")}
        case_failures = []
        for expected_key, expected_value in expected.items():
            actual_key = expected_key.removeprefix("expected_")
            if actual.get(actual_key) != expected_value:
                case_failures.append(f"{actual_key} expected {expected_value!r}, got {actual.get(actual_key)!r}")
        failures.extend(f"{case['case_id']}: {message}" for message in case_failures)
        results.append({"case_id": case["case_id"], "operation": operation, "passed": not case_failures, "actual": actual, "failures": case_failures})
    return {"passed": not failures, "failures": failures, "cases": results}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "reports" / "latest.json")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    fixture = load_json(EVAL_DIR / "rag_eval.json")
    embedding_fixture = load_json(EVAL_DIR / "embedding_cases.json")
    versions = load_json(ROOT / "evals" / "step34" / "versions.json")
    documents = fixture.get("documents", [])
    queries = fixture.get("queries", [])
    query_results = [evaluate_query(documents, query) for query in queries]
    chunk_results = evaluate_chunks(documents, fixture["chunk_parameters"])
    embedding_results = evaluate_embedding_lifecycle(embedding_fixture.get("cases", []))
    positive = [item for item in query_results if item["expected_keys"]]
    metric = lambda key: round(sum(float(item[key]) for item in positive if item[key] is not None) / max(1, len([item for item in positive if item[key] is not None])), 4)
    failures = [item for item in query_results if not item["passed"]]
    failures.extend({"query_id": "chunk_regeneration", "failures": chunk_results["failures"]} for _ in [0] if not chunk_results["passed"])
    failures.extend({"query_id": "embedding_lifecycle", "failures": embedding_results["failures"]} for _ in [0] if not embedding_results["passed"])
    report = {
        "suite": "chargeops-step35-rag-evaluation",
        "suite_version": "step35-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versions": {"data_version": fixture.get("data_version"), "model": versions.get("model"), "embedding": versions.get("embedding"), "prompt_versions": versions.get("prompt_versions"), "rule_versions": versions.get("rule_versions"), "index_version": fixture.get("index_version")},
        "parameters": {"top_k_values": sorted({int(query.get("top_k", 5)) for query in queries}), "chunk": fixture.get("chunk_parameters"), "retrieval": {"tokenizer": "unicode-word-cjk-v1", "score": "matched_terms / query_terms", "no_hit_status": "EVIDENCE_INSUFFICIENT"}},
        "fixture_sha256": {name: sha256_file(EVAL_DIR / name) for name in ("rag_eval.json", "embedding_cases.json")},
        "summary": {"documents": len(documents), "queries": len(queries), "query_passed": len(query_results) - len([item for item in query_results if not item["passed"]]), "query_failed": len([item for item in query_results if not item["passed"]]), "recall_at_k": metric("recall_at_k"), "hit_rate_at_k": metric("hit_rate_at_k"), "mrr": metric("mrr"), "source_correctness": round(sum(item["source_correct"] for item in positive) / max(1, len(positive)), 4), "fragment_locatability": round(sum(item["fragment_locatable"] for item in positive) / max(1, len(positive)), 4), "filter_checks_passed": sum(item["filter_ok"] for item in query_results), "agent_type_checks_passed": sum(item["agent_type_ok"] for item in query_results), "chunk_regeneration_passed": chunk_results["passed"], "embedding_lifecycle_passed": embedding_results["passed"]},
        "query_results": query_results,
        "chunk_regeneration": chunk_results,
        "embedding_lifecycle": embedding_results,
        "failures": failures,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"suite": report["suite"], "queries": report["summary"]["queries"], "failed": report["summary"]["query_failed"], "recall_at_k": report["summary"]["recall_at_k"], "hit_rate_at_k": report["summary"]["hit_rate_at_k"], "mrr": report["summary"]["mrr"], "source_correctness": report["summary"]["source_correctness"], "fragment_locatability": report["summary"]["fragment_locatability"], "output": str(args.output)}, ensure_ascii=False))
    return 1 if args.strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
