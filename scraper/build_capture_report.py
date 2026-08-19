"""Build an offline, school-level capture report from existing local evidence.

This command is intentionally read-only with respect to the network. It joins
the four top-500 ranking files, the goal coverage audit, and the raw
application audit so the frontend can distinguish captured raw pages from a
school that was only reviewed, blocked, or checked without finding a program.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "frontend" / "public" / "data"
PLAYWRIGHT = ROOT / "scraper" / "playwright"
GOAL = PLAYWRIGHT / "top500_goal_entity_coverage_v5.json"
APPLICATION_AUDIT = PLAYWRIGHT / "top500_engineering_application_evidence_audit_v4.json"
RANKING_FILES = {
    "qs": DATA / "rankings" / "qs.json",
    "the": DATA / "rankings" / "the.json",
    "arwu": DATA / "rankings" / "arwu.json",
    "usnews": DATA / "rankings" / "usnews.json",
}
EXPECTED_SCHOOLS = 811


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return default


def fold_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(
        r"\b(the|of|university|universite|universitat|universidad|institute|"
        r"technology|technische|technical|royal|school|college)\b",
        " ",
        text,
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def raw_stats(entity: Dict[str, Any]) -> Dict[str, Any]:
    records = [entity.get("existingRaw"), entity.get("newRaw")]
    records = [record for record in records if isinstance(record, dict)]
    return {
        "manifestCount": len(records),
        "sources": [
            {
                "status": record.get("manifestStatus"),
                "programCandidates": record.get("programCandidates", 0),
                "programCaptured": record.get("programCaptured", 0),
                "programBlocked": record.get("programBlocked", 0),
                "programError": record.get("programError", 0),
                "evidenceCaptured": record.get("evidenceCaptured", 0),
                "evidenceBlocked": record.get("evidenceBlocked", 0),
            }
            for record in records
        ],
    }


def classify(entity: Dict[str, Any], stats: Dict[str, Any]) -> str:
    category = entity.get("category")
    if category == "official-blocked":
        return "blocked"
    if category in {"official-review", "official-rejected", "official-discovery-missing",
                    "existing-target-manifest-missing", "verified-target-manifest-missing"}:
        return "needs-review"
    candidates = sum(item.get("programCandidates", 0) for item in stats["sources"])
    captured = sum(item.get("programCaptured", 0) for item in stats["sources"])
    if captured > 0:
        return "captured"
    if stats["manifestCount"] > 0 or candidates > 0:
        return "checked-no-program"
    return "pending"


def rank_lookup() -> Dict[str, Dict[str, Dict[str, Any]]]:
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for source, path in RANKING_FILES.items():
        by_id: Dict[str, Dict[str, Any]] = {}
        by_name: Dict[str, Dict[str, Any]] = {}
        for row in load_json(path, []):
            if not isinstance(row, dict):
                continue
            by_id[str(row.get("universityId") or "")] = row
            key = fold_name(row.get("name"))
            if key and (key not in by_name or row.get("rank", 9999) < by_name[key].get("rank", 9999)):
                by_name[key] = row
        result[source] = {"byId": by_id, "byName": by_name}
    return result


def rank_records(entity: Dict[str, Any], lookups: Dict[str, Dict[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for source in entity.get("rankingSources", []):
        lookup = lookups.get(source, {})
        row = None
        for source_id in entity.get("sourceUniversityIds", []):
            row = lookup.get("byId", {}).get(source_id)
            if row:
                break
        row = row or lookup.get("byName", {}).get(fold_name(entity.get("name")))
        if row:
            output[source] = {
                "rank": row.get("rank"),
                "score": row.get("score"),
                "year": row.get("year"),
            }
    return output


def build_report() -> Dict[str, Any]:
    goal = load_json(GOAL, {}) or {}
    goal_entities = [row for row in goal.get("entities", []) if isinstance(row, dict)]
    goal_ids = [str(row.get("canonicalId") or "") for row in goal_entities]
    if any(not identifier for identifier in goal_ids):
        raise ValueError("goal coverage contains an entity without canonicalId")
    duplicate_ids = sorted(identifier for identifier, count in Counter(goal_ids).items() if count > 1)
    if duplicate_ids:
        raise ValueError("goal coverage contains duplicate canonicalId values: " + ", ".join(duplicate_ids))
    if len(goal_ids) != EXPECTED_SCHOOLS:
        raise ValueError(f"goal coverage contains {len(goal_ids)} schools; expected {EXPECTED_SCHOOLS}")
    application = load_json(APPLICATION_AUDIT, {}) or {}
    application_by_id = {
        row.get("canonicalId"): row
        for row in application.get("universities", [])
        if isinstance(row, dict) and row.get("canonicalId")
    }
    lookups = rank_lookup()
    # Build a merged school dict keyed by canonicalId so that entities sharing
    # the same canonical ID (e.g. via manual alias groups) are collapsed.
    schools_by_id: Dict[str, Dict[str, Any]] = {}

    for entity in goal_entities:
        cid = entity.get("canonicalId")
        if not cid:
            continue
        stats = raw_stats(entity)
        status = classify(entity, stats)
        audit = application_by_id.get(cid)
        raw_candidates = sum(item.get("programCandidates", 0) for item in stats["sources"])
        raw_captured = sum(item.get("programCaptured", 0) for item in stats["sources"])
        country = entity.get("country") or ""
        existing = schools_by_id.get(cid)
        if existing is not None:
            # Merge: combine ranking sources, prefer the more descriptive name
            for src in entity.get("rankingSources", []):
                if src not in existing["rankingSources"]:
                    existing["rankingSources"].append(src)
            # Prefer name without abbreviation suffix if available
            if len(entity.get("name", "")) < len(existing["name"]):
                existing["name"] = entity.get("name")
            # Accumulate raw stats
            existing["raw"]["manifestCount"] += stats["manifestCount"]
            existing["raw"]["programCandidates"] += raw_candidates
            existing["raw"]["programCaptured"] += raw_captured
            existing["raw"]["programBlocked"] += sum(item.get("programBlocked", 0) for item in stats["sources"])
            existing["raw"]["programErrors"] += sum(item.get("programError", 0) for item in stats["sources"])
            existing["raw"]["sources"].extend(stats["sources"])
            # Upgrade status: captured > checked-no-program > needs-review > blocked > pending
            status_priority = {"captured": 5, "checked-no-program": 4, "needs-review": 3, "blocked": 2, "pending": 1}
            if status_priority.get(status, 0) > status_priority.get(existing["captureStatus"], 0):
                existing["captureStatus"] = status
            continue
        schools_by_id[cid] = {
            "canonicalId": cid,
            "name": entity.get("name"),
            "country": country,
            "mainlandChina": country == "China",
            "rankingSources": entity.get("rankingSources", []),
            "ranks": rank_records(entity, lookups),
            "captureStatus": status,
            "goalCategory": entity.get("category"),
            "officialVerificationStatus": entity.get("officialVerificationStatus"),
            "officialReasonCodes": entity.get("officialReasonCodes", []),
            "raw": {
                "manifestCount": stats["manifestCount"],
                "programCandidates": raw_candidates,
                "programCaptured": raw_captured,
                "programBlocked": sum(item.get("programBlocked", 0) for item in stats["sources"]),
                "programErrors": sum(item.get("programError", 0) for item in stats["sources"]),
                "sources": stats["sources"],
            },
            "engineeringAudit": {
                "top500": bool(audit and audit.get("top500")),
                "programCount": audit.get("programCount", 0) if audit else 0,
                "coverage": audit.get("coverage", {}) if audit else {},
                "sourceUrlCompleteCount": audit.get("sourceUrlCompleteCount", 0) if audit else 0,
            },
        }

    schools = list(schools_by_id.values())

    status_counts: Dict[str, int] = {}
    for school in schools:
        status = school["captureStatus"]
        status_counts[status] = status_counts.get(status, 0) + 1
    raw_candidates = sum(school["raw"]["programCandidates"] for school in schools)
    raw_captured = sum(school["raw"]["programCaptured"] for school in schools)
    mainland_count = sum(1 for school in schools if school["mainlandChina"])

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "rankingSources": list(RANKING_FILES),
            "rankingRowLimit": 500,
            "entityDefinition": "Deduplicated schools appearing in at least one of the four ranking top-500 files.",
            "mainlandChinaPolicy": "Existing local evidence is reported; no new mainland-China school website access is queued.",
            "sourceOfTruth": "Raw manifests and captured evidence, not official URL coverage alone.",
        },
        "summary": {
            "schools": len(schools),
            "statusCounts": status_counts,
            "rawProgramCandidates": raw_candidates,
            "rawProgramCaptured": raw_captured,
            "mainlandChinaSchools": mainland_count,
            "applicationAudit": application.get("summary", {}),
        },
        "sourceFiles": {
            "goalCoverage": str(GOAL.relative_to(ROOT)),
            "applicationAudit": str(APPLICATION_AUDIT.relative_to(ROOT)),
            "rankings": {key: str(path.relative_to(ROOT)) for key, path in RANKING_FILES.items()},
        },
        "schools": sorted(schools, key=lambda school: (school["captureStatus"], school["country"], school["name"] or "")),
    }


def main() -> None:
    report = build_report()
    destinations = [PLAYWRIGHT / "top500_capture_report.json", DATA / "top500_capture_report.json"]
    payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
    print("[capture-report] schools=%d status=%s" % (report["summary"]["schools"], report["summary"]["statusCounts"]))
    print("[capture-report] raw candidates=%d captured=%d" % (
        report["summary"]["rawProgramCandidates"], report["summary"]["rawProgramCaptured"]
    ))
    for destination in destinations:
        print("[capture-report] -> %s" % destination)


if __name__ == "__main__":
    main()
