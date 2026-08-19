"""Build covered and missing Top-350 school lists from local URL evidence.

Coverage means that an institution has at least one specific official
programme or programme-catalog URL that passed the deterministic URL filter.
It does not mean that programme requirements or deadlines are complete.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCOPE = ROOT / "scraper" / "playwright" / "top350_cs_engineering_feature2_scope_v1.json"
DEFAULT_REVIEW = ROOT / "scraper" / "playwright" / "top350_cs_engineering_url_quality_review_v1.json"
DEFAULT_COVERED = ROOT / "scraper" / "playwright" / "top350_cs_engineering_covered_schools_v1.json"
DEFAULT_MISSING = ROOT / "scraper" / "playwright" / "top350_cs_engineering_missing_schools_v1.json"
DEFAULT_FRONTEND = ROOT / "frontend" / "public" / "data" / "feature2_coverage.json"


def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def is_specific_url_review(row: Mapping[str, Any]) -> bool:
    return not any(
        isinstance(finding, dict)
        and finding.get("category") == "obvious-non-program-catalog"
        for finding in row.get("findings") or []
    )


def urls_by_canonical_id(review: Mapping[str, Any]) -> Dict[str, List[str]]:
    result: Dict[str, set[str]] = {}
    for row in review.get("urlReviews") or []:
        if not isinstance(row, dict) or not is_specific_url_review(row):
            continue
        url = str(row.get("url") or "").strip()
        if not url:
            continue
        for record in row.get("canonicalRecords") or []:
            if not isinstance(record, dict):
                continue
            canonical_id = str(record.get("canonicalId") or "").strip()
            if canonical_id:
                result.setdefault(canonical_id, set()).add(url)
    return {key: sorted(values) for key, values in result.items()}


def normalized_selections(entity: Mapping[str, Any]) -> List[Dict[str, Any]]:
    selections = []
    for row in (entity.get("rankingScope") or {}).get("selections") or []:
        if not isinstance(row, dict):
            continue
        selections.append({
            "source": row.get("source"),
            "rowIndex": row.get("rowIndex"),
            "displayedRank": row.get("displayedRank"),
            "year": row.get("year"),
        })
    return sorted(selections, key=lambda row: (row.get("rowIndex", 9999), row.get("source") or ""))


def ranking_ids_for_entity(
    entity: Mapping[str, Any],
    rankings_by_source: Optional[Mapping[str, Sequence[Mapping[str, Any]]]],
) -> List[str]:
    if not rankings_by_source:
        return []
    ids = []
    for selection in normalized_selections(entity):
        source = str(selection.get("source") or "")
        row_index = selection.get("rowIndex")
        if not isinstance(row_index, int):
            continue
        rows = rankings_by_source.get(source) or []
        if 0 <= row_index < len(rows):
            identifier = str(rows[row_index].get("universityId") or "").strip()
            if identifier and identifier not in ids:
                ids.append(identifier)
    return ids


def build_records(
    scope: Mapping[str, Any],
    review: Mapping[str, Any],
    rankings_by_source: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    evidence = urls_by_canonical_id(review)
    records = []
    for entity in scope.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        ranking_scope = entity.get("rankingScope") or {}
        if not ranking_scope.get("eligible"):
            continue
        canonical_id = str(entity.get("canonicalId") or "").strip()
        if not canonical_id:
            continue
        urls = evidence.get(canonical_id, [])
        record = {
            "canonicalId": canonical_id,
            "name": entity.get("name"),
            "country": entity.get("country"),
            "rankingSources": sorted(set(entity.get("rankingSources") or [])),
            "selections": normalized_selections(entity),
            "coverageStatus": "covered" if urls else "missing",
            "urlCount": len(urls),
            "urls": urls,
        }
        ranking_ids = ranking_ids_for_entity(entity, rankings_by_source)
        if ranking_ids:
            record["rankingUniversityIds"] = ranking_ids
        records.append(record)
    records.sort(key=lambda row: (
        min((selection.get("rowIndex", 9999) for selection in row["selections"]), default=9999),
        str(row.get("country") or ""),
        str(row.get("name") or ""),
        row["canonicalId"],
    ))
    return records


def make_payload(
    records: Sequence[Mapping[str, Any]],
    status: Optional[str] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    selected = [dict(row) for row in records if status is None or row.get("coverageStatus") == status]
    covered = sum(row.get("coverageStatus") == "covered" for row in records)
    missing = len(records) - covered
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at or datetime.now(timezone.utc).isoformat(),
        "scope": {
            "rankingSources": ["qs", "the", "arwu", "usnews"],
            "rankingRowLimit": 350,
            "selectionBasis": "first-350-rows-per-source",
            "mainlandChinaInstitutionsExcluded": True,
            "hongKongAndMacauIncluded": True,
            "coverageDefinition": "At least one specific official programme or programme-catalog URL passed the local URL quality filter.",
            "requirementsComplete": False,
        },
        "summary": {
            "schools": len(records),
            "coveredSchools": covered,
            "missingSchools": missing,
            "coveragePercent": round(100.0 * covered / len(records), 1) if records else 0.0,
            "recordsInFile": len(selected),
            "officialUrlAssignments": sum(int(row.get("urlCount") or 0) for row in records),
            "uniqueOfficialUrls": len({url for row in records for url in row.get("urls") or []}),
        },
        "schools": selected,
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--covered-output", type=Path, default=DEFAULT_COVERED)
    parser.add_argument("--missing-output", type=Path, default=DEFAULT_MISSING)
    parser.add_argument("--frontend-output", type=Path, default=DEFAULT_FRONTEND)
    args = parser.parse_args(argv)

    rankings_by_source = {}
    for source in ("qs", "the", "arwu", "usnews"):
        ranking_path = ROOT / "frontend" / "public" / "data" / "rankings" / f"{source}.json"
        rankings_by_source[source] = json.loads(ranking_path.read_text(encoding="utf-8"))
    records = build_records(load_json(args.scope), load_json(args.review), rankings_by_source)
    generated_at = datetime.now(timezone.utc).isoformat()
    covered_payload = make_payload(records, "covered", generated_at)
    missing_payload = make_payload(records, "missing", generated_at)
    frontend_payload = make_payload(records, None, generated_at)
    write_json(args.covered_output, covered_payload)
    write_json(args.missing_output, missing_payload)
    write_json(args.frontend_output, frontend_payload)
    print(json.dumps(frontend_payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
