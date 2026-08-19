"""Build the raw-first Feature 2 scope for Top 350 CS/Engineering work."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from scraper.programs.build_engineering_priority_queue_v4 import (
    build_row_scope,
    entity_maps,
    ranking_rows,
)
from scraper.programs.scope_policy import is_mainland_china_country


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit_v3.json"
DEFAULT_COVERAGE = ROOT / "scraper" / "playwright" / "top500_goal_entity_coverage_v5.json"
DEFAULT_PRIORITY = ROOT / "scraper" / "playwright" / "top500_engineering_priority_queue_v4.json"
DEFAULT_OUTPUT = ROOT / "scraper" / "playwright" / "top350_cs_engineering_feature2_scope_v1.json"

CS_TERMS = re.compile(
    r"\b(?:computer science|computing|informatics|information technology|"
    r"software|data science|artificial intelligence|machine learning|"
    r"cyber[\s-]?security|robotics|computer engineering)\b",
    re.I,
)
ENGINEERING_TERMS = re.compile(
    r"\b(?:engineering|electrical|electronics|mechanical|civil|chemical|"
    r"biomedical|aerospace|environmental|energy|materials|industrial|"
    r"mechatronics|automation|manufacturing)\b",
    re.I,
)


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def payload_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "records", "entities", "universities", "targets"):
            if isinstance(payload.get(key), list):
                return [item for item in payload[key] if isinstance(item, dict)]
    return []


def text_values(item: Dict[str, Any]) -> Iterable[str]:
    for key in ("name", "title", "text", "anchorText", "discipline", "subject"):
        value = item.get(key)
        if isinstance(value, str):
            yield value
    for key in ("signals", "matchedSignals", "engineeringSignals", "csSignals"):
        values = item.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict):
                    for nested in ("signal", "match", "value", "term"):
                        if isinstance(value.get(nested), str):
                            yield value[nested]


def classify_signal(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    values = [value for item in items for value in text_values(item)]
    joined = " ".join(values)
    cs = sorted(set(match.group(0).casefold() for match in CS_TERMS.finditer(joined)))
    engineering = sorted(
        set(match.group(0).casefold() for match in ENGINEERING_TERMS.finditer(joined))
    )
    if cs and engineering:
        level = "strong"
    elif cs or engineering:
        level = "moderate"
    else:
        level = "unknown"
    return {
        "level": level,
        "csSignals": cs,
        "engineeringSignals": engineering,
        "sourceCount": len(values),
    }


def build_scope(
    audit: Dict[str, Any],
    coverage: Dict[str, Any],
    priority: Any = None,
    rows_by_source: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    row_limit: int = 350,
) -> Dict[str, Any]:
    if rows_by_source is None:
        rows_by_source = ranking_rows(audit, row_limit)
    _, id_map = entity_maps(coverage, audit)
    selected, _, row_summary = build_row_scope(rows_by_source, id_map, row_limit)
    priority_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for item in payload_items(priority):
        identifier = item.get("canonicalId") or item.get("universityId")
        if identifier:
            priority_by_id.setdefault(str(identifier), []).append(item)
    coverage_by_id = {
        str(item.get("canonicalId") or item.get("universityId")): item
        for item in payload_items(coverage)
        if item.get("canonicalId") or item.get("universityId")
    }
    records = []
    counts = Counter()
    excluded_country_counts = Counter()
    for entity in payload_items(audit):
        identifier = str(entity.get("canonicalId") or "")
        if not identifier:
            continue
        if is_mainland_china_country(entity.get("country")):
            excluded_country_counts[str(entity.get("country") or "China")] += 1
            continue
        selections = selected.get(identifier) or []
        ranks = {
            "eligible": bool(selections),
            "rowLimit": row_limit,
            "selectionBasis": "first-%d-rows" % row_limit,
            "selections": selections,
        }
        signal = classify_signal(priority_by_id.get(identifier, []))
        if priority_by_id.get(identifier) and signal["level"] == "unknown":
            signal["level"] = "moderate"
            signal["inheritedFromPriorityUrlExport"] = True
        if not ranks["eligible"]:
            status = "deferred-top351-500"
        elif signal["level"] == "unknown":
            status = "top350-unknown-discipline"
        else:
            status = "feature2-priority"
        counts[status] += 1
        records.append({
            "canonicalId": identifier,
            "name": entity.get("name"),
            "country": entity.get("country"),
            "rankingSources": entity.get("rankingSources") or [],
            "rankingScope": ranks,
            "disciplineSignal": signal,
            "coverageCategory": (coverage_by_id.get(identifier) or {}).get("category"),
            "priorityEvidence": priority_by_id.get(identifier, []),
            "status": status,
            "dataPolicy": {
                "rawFirst": True,
                "disciplineIsPrioritySignalOnly": True,
                "notFinalSubjectClassification": True,
                "deferredRanksRemainInCorpus": True,
            },
        })
    records.sort(key=lambda item: (
        0 if item["status"] == "feature2-priority" else
        1 if item["status"] == "top350-unknown-discipline" else 2,
        min((selection["rowIndex"] for selection in item["rankingScope"]["selections"]), default=501),
        item.get("country") or "",
        item["canonicalId"],
    ))
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "feature": "feature-2-cs-engineering-top350",
        "scope": {
            "rankingSources": ["qs", "the", "arwu", "usnews"],
            "rankingRowLimit": row_limit,
            "selectionBasis": "first-%d-rows-per-source" % row_limit,
            "rankingRowSummary": row_summary,
            "disciplines": ["Computer Science", "Engineering"],
            "signalOnlyUntilManualReview": True,
            "mainlandChinaInstitutionsExcluded": True,
            "hongKongAndMacauExcludedByThisRule": False,
        },
        "summary": {
            "entities": len(records),
            "statusCounts": dict(sorted(counts.items())),
            "priorityEntities": counts["feature2-priority"],
            "top350UnknownDiscipline": counts["top350-unknown-discipline"],
            "deferredTop351To500": counts["deferred-top351-500"],
            "excludedMainlandChinaEntities": sum(excluded_country_counts.values()),
            "excludedCountryCounts": dict(sorted(excluded_country_counts.items())),
        },
        "entities": records,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--priority", type=Path, default=DEFAULT_PRIORITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--row-limit", type=int, default=350)
    args = parser.parse_args(argv)
    audit = load(args.audit, {})
    result = build_scope(
        audit,
        load(args.coverage, {}),
        load(args.priority, []),
        rows_by_source=ranking_rows(audit, args.row_limit),
        row_limit=args.row_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
