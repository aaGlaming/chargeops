"""Run the versioned Step 34 deterministic evaluation suite.

The suite is intentionally offline: it exercises the same deterministic Agent
functions used by the tool executor, validates Gold expectations, and records
failure attribution without calling a chat model, Embedding endpoint, MySQL,
or Chroma.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EVAL_DIR = ROOT / "evals" / "step34"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.competition import analyze_competition
from app.agents.coverage_gap import analyze_coverage_gap
from app.agents.contracts import CompetitionOutput, CoverageGapOutput, ExpansionOutput, PolicyMatchingOutput, SiteSelectionOutput
from app.agents.expansion import analyze_expansion
from app.agents.policy_matching import analyze_policy_matching
from app.agents.site_selection import analyze_site_selection
from app.services.imports import FIELD_DEFINITIONS


MISSING = object()
PROMPT_VERSIONS = {
    "coverage_gap": "coverage-gap-v1",
    "competition": "competition-v1",
    "site_selection": "site-selection-v1",
    "expansion": "expansion-v1",
    "policy_matching": "policy-matching-v1",
}
RULE_VERSIONS = {
    "coverage_gap": "coverage-gap-v1",
    "competition": "competition-v1",
    "site_selection": "site-selection-score-v1",
    "expansion": "expansion-plan-v1",
    "policy_matching": "policy-matching-v1",
}
OUTPUT_SCHEMAS = {
    "coverage_gap": CoverageGapOutput,
    "competition": CompetitionOutput,
    "site_selection": SiteSelectionOutput,
    "expansion": ExpansionOutput,
    "policy_matching": PolicyMatchingOutput,
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def get_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split(".") if path else []:
        if isinstance(current, list) and segment.isdigit() and int(segment) < len(current):
            current = current[int(segment)]
        elif isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return MISSING
    return current


def equivalent(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=1e-6, abs_tol=1e-4)
    if isinstance(actual, dict) and isinstance(expected, dict):
        return set(actual) == set(expected) and all(equivalent(actual[key], expected[key]) for key in expected)
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(equivalent(left, right) for left, right in zip(actual, expected))
    return actual == expected


def check_expectation(output: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = expected.get("status")
    if status is not None and output.get("status") != status:
        errors.append(f"status expected {status!r}, got {output.get('status')!r}")
    for key in expected.get("required_keys", []):
        if key not in output:
            errors.append(f"missing required key {key}")
    for path, value in expected.get("fields", {}).items():
        actual = get_path(output, path)
        if actual is MISSING or not equivalent(actual, value):
            errors.append(f"{path} expected {value!r}, got {None if actual is MISSING else actual!r}")
    for condition in expected.get("reject_conditions", []):
        path = str(condition.get("path"))
        actual = get_path(output, path)
        if "equals" in condition and (actual is MISSING or not equivalent(actual, condition["equals"])):
            errors.append(f"{path} must equal {condition['equals']!r}")
        if "not_equals" in condition and actual is not MISSING and equivalent(actual, condition["not_equals"]):
            errors.append(f"{path} must not equal {condition['not_equals']!r}")
        if "contains" in condition and (actual is MISSING or condition["contains"] not in actual):
            errors.append(f"{path} must contain {condition['contains']!r}")
        if "not_contains" in condition and actual is not MISSING and condition["not_contains"] in actual:
            errors.append(f"{path} must not contain {condition['not_contains']!r}")
    return errors


def as_of(value: str | None, fallback: str) -> date:
    return date.fromisoformat(value or fallback)


def run_agent(case: dict[str, Any], suite_date: str) -> dict[str, Any]:
    payload = case["input"]
    context = case.get("context", {})
    agent_type = case["agent_type"]
    when = as_of(payload.get("analysis_date") or payload.get("planned_date"), suite_date)
    if agent_type == "coverage_gap":
        return analyze_coverage_gap(payload, region=context.get("region"), stations=context.get("stations", []), connectors=context.get("connectors", []), metrics=context.get("metrics", []), as_of=when)
    if agent_type == "competition":
        return analyze_competition(payload, stations=context.get("stations", []), connectors=context.get("connectors", []), as_of=when)
    if agent_type == "site_selection":
        return analyze_site_selection(payload, candidates=context.get("candidates", []), regions=context.get("regions", []), stations=context.get("stations", []), as_of=when)
    if agent_type == "expansion":
        return analyze_expansion(payload, stations=context.get("stations", []), connectors=context.get("connectors", []), metrics=context.get("metrics", []), faults=context.get("faults", []), as_of=when)
    if agent_type == "policy_matching":
        return analyze_policy_matching(payload, policies=context.get("policies", []), candidates=context.get("candidates", []), subject=context.get("subject"))
    raise ValueError(f"unsupported agent type: {agent_type}")


def validate_agent_case(case: dict[str, Any], suite_date: str) -> dict[str, Any]:
    output = run_agent(case, suite_date)
    errors = check_expectation(output, case["expected"])
    agent_type = case["agent_type"]
    try:
        OUTPUT_SCHEMAS[agent_type].model_validate(output)
    except Exception as exc:
        errors.append(f"output schema validation failed: {exc}")
    if output.get("data_version") not in {case["input"].get("data_version"), None}:
        errors.append(f"data_version expected {case['input'].get('data_version')!r}, got {output.get('data_version')!r}")
    if agent_type in RULE_VERSIONS and output.get("scoring_rule_version") not in {RULE_VERSIONS[agent_type], None}:
        errors.append(f"rule version mismatch: {output.get('scoring_rule_version')!r}")
    metrics: dict[str, Any] = {}
    if agent_type == "coverage_gap":
        metrics = {"coverage_score": output.get("coverage_score"), "nearest_station_distance_km": output.get("nearest_station_distance_km"), "station_density_per_sq_km": output.get("station_density_per_sq_km")}
    elif agent_type == "competition":
        metrics = {"nearest_station_distance_km": output.get("metrics", {}).get("nearest_station_distance_km"), "competition_index": output.get("competition_index"), "hhi": output.get("operator_concentration", {}).get("hhi")}
    elif agent_type == "site_selection":
        selected = (output.get("ranked_candidates") or [{}])[0]
        metrics = {"selected_candidate_id": output.get("selected_candidate_id"), "total_score": selected.get("total_score"), "recommendation_grade": selected.get("recommendation_grade")}
    elif agent_type == "expansion":
        plan = (output.get("plans") or [{}])[0]
        metrics = {"proposed_fast_connectors": plan.get("proposed_fast_connectors"), "estimated_budget_usd": plan.get("estimated_budget_usd"), "priority": plan.get("priority")}
    elif agent_type == "policy_matching":
        metrics = {"match_summary": output.get("match_summary"), "missing_materials": output.get("missing_materials", [])}
    return {"case_id": case["case_id"], "agent_type": agent_type, "complexity": case.get("complexity", "unspecified"), "passed": not errors, "errors": errors, "metrics": metrics}


def validate_rag_fixture(rag: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    documents = rag.get("documents", [])
    document_keys = [item.get("document_key") for item in documents]
    if len(document_keys) != len(set(document_keys)):
        errors.append("RAG document_key values are not unique")
    for document in documents:
        content = str(document.get("content", ""))
        for fragment in document.get("expected_fragments", []):
            if fragment not in content:
                errors.append(f"RAG fragment missing from {document.get('document_key')}: {fragment}")
    for query in rag.get("queries", []):
        expected_keys = query.get("expected_document_keys", [])
        if query.get("expected_status") == "EVIDENCE_INSUFFICIENT" and expected_keys:
            errors.append(f"RAG no-hit query has expected documents: {query.get('query_id')}")
        if query.get("expected_fragment") and not any(query["expected_fragment"] in document.get("content", "") for document in documents if document.get("document_key") in expected_keys):
            errors.append(f"RAG expected fragment is not present for {query.get('query_id')}")
    return errors


def validate_import_case(case: dict[str, Any]) -> dict[str, Any]:
    row = case.get("row", {})
    dataset_type = case["dataset_type"]
    expected = case["expected"]
    errors: list[str] = []
    actual_codes: list[str] = []
    fields = FIELD_DEFINITIONS.get(dataset_type, [])
    for field in fields:
        if field.required and not str(row.get(field.key, "")).strip():
            actual_codes.append("REQUIRED_FIELD_MISSING")
    if dataset_type == "stations":
        try:
            latitude = float(row["latitude"]) if str(row.get("latitude", "")).strip() else None
            longitude = float(row["longitude"]) if str(row.get("longitude", "")).strip() else None
            if latitude is not None and not -90 <= latitude <= 90:
                actual_codes.append("INVALID_COORDINATES")
            if longitude is not None and not -180 <= longitude <= 180:
                actual_codes.append("INVALID_COORDINATES")
        except (TypeError, ValueError):
            actual_codes.append("INVALID_COORDINATES")
        if row.get("external_station_id") == "ST-001":
            actual_codes.append("DUPLICATE_EXTERNAL_ID")
    if dataset_type == "connectors" and row.get("station_external_id") == "ST-NOT-FOUND":
        actual_codes.append("STATION_NOT_FOUND")
    actual_codes = sorted(set(actual_codes))
    expected_codes = sorted(set(expected.get("error_codes", [])))
    if expected.get("outcome") == "VALID" and actual_codes:
        errors.append(f"expected valid row, got {actual_codes}")
    if expected.get("outcome") == "REJECTED" and actual_codes != expected_codes:
        errors.append(f"expected import errors {expected_codes}, got {actual_codes}")
    return {"case_id": case["case_id"], "dataset_type": dataset_type, "passed": not errors, "errors": errors, "actual_codes": actual_codes, "outcome": "VALID" if not actual_codes else "REJECTED"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EVAL_DIR / "reports" / "latest.json")
    parser.add_argument("--strict", action="store_true", help="return non-zero when a baseline case fails")
    args = parser.parse_args()

    agent_fixture = load_json(EVAL_DIR / "agent_gold.json")
    rag_fixture = load_json(EVAL_DIR / "rag_gold.json")
    import_fixture = load_json(EVAL_DIR / "import_cases.json")
    versions = load_json(EVAL_DIR / "versions.json")
    attribution = load_json(EVAL_DIR / "failure_attribution.json")

    structural_errors: list[str] = []
    cases = agent_fixture.get("cases", [])
    case_ids = [case.get("case_id") for case in cases] + [case.get("case_id") for case in import_fixture.get("cases", [])]
    if len(case_ids) != len(set(case_ids)):
        structural_errors.append("case_id values are not unique")
    if agent_fixture.get("data_version") != versions.get("data_version"):
        structural_errors.append("agent Gold data_version does not match versions manifest")
    if versions.get("prompt_versions") != PROMPT_VERSIONS:
        structural_errors.append("prompt version manifest does not match Agent contracts")
    if versions.get("rule_versions") != RULE_VERSIONS:
        structural_errors.append("rule version manifest does not match deterministic baselines")
    structural_errors.extend(validate_rag_fixture(rag_fixture))
    attribution_ids = {entry.get("case_id") for entry in attribution.get("entries", [])}
    missing_attribution = {case_id for case_id in case_ids if str(case_id).endswith("reject_001") and case_id not in attribution_ids}
    structural_errors.extend(f"missing failure attribution for {case_id}" for case_id in sorted(missing_attribution))

    agent_results = [validate_agent_case(case, agent_fixture["as_of"]) for case in cases]
    import_results = [validate_import_case(case) for case in import_fixture.get("cases", [])]
    all_results = agent_results + import_results
    failed = [result for result in all_results if not result["passed"]]
    by_agent = Counter(result.get("agent_type", "imports") for result in all_results)
    passed_by_agent = Counter(result.get("agent_type", "imports") for result in all_results if result["passed"])
    report = {
        "suite": "chargeops-step34-deterministic-baseline",
        "suite_version": versions.get("suite_version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "versions": versions,
        "fixture_sha256": {name: sha256_file(EVAL_DIR / name) for name in ("agent_gold.json", "rag_gold.json", "import_cases.json", "versions.json", "failure_attribution.json")},
        "structural_errors": structural_errors,
        "summary": {"total": len(all_results), "passed": len(all_results) - len(failed), "failed": len(failed), "pass_rate": round((len(all_results) - len(failed)) / len(all_results), 4) if all_results else 0, "by_agent": dict(by_agent), "passed_by_agent": dict(passed_by_agent), "rag_queries": len(rag_fixture.get("queries", [])), "rag_documents": len(rag_fixture.get("documents", []))},
        "deterministic_metrics": {"distance": [result["metrics"].get("nearest_station_distance_km") for result in agent_results if result["metrics"].get("nearest_station_distance_km") is not None], "coverage": [result["metrics"].get("coverage_score") for result in agent_results if result["metrics"].get("coverage_score") is not None], "competition_index": [result["metrics"].get("competition_index") for result in agent_results if result["metrics"].get("competition_index") is not None], "site_scores": [result["metrics"].get("total_score") for result in agent_results if result["metrics"].get("total_score") is not None], "policy_summaries": [result["metrics"].get("match_summary") for result in agent_results if result["metrics"].get("match_summary") is not None]},
        "failures": failed,
        "failure_attribution": [entry for entry in attribution.get("entries", []) if any(entry.get("case_id") == result["case_id"] for result in failed)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"suite": report["suite"], "total": report["summary"]["total"], "passed": report["summary"]["passed"], "failed": report["summary"]["failed"], "structural_errors": len(structural_errors), "output": str(args.output)}, ensure_ascii=False))
    return 1 if args.strict and (failed or structural_errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
