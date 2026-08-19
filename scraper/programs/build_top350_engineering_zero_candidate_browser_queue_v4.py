"""Restrict the engineering zero-candidate browser queue to Top 350 rows.

The scope is the union of canonical institutions mapped from the first 350
array rows of each original ranking source. Displayed rank values are never
used for selection. The source queue and ranking data are read-only.
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from scraper.programs.build_engineering_priority_queue_v4 import (
    RANKING_SOURCE_ORDER,
    build_row_scope,
    entity_maps,
    ranking_rows,
)
from scraper.programs.scope_policy import is_mainland_china_country


ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE_INPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top500_engineering_zero_candidate_browser_queue_v4.json"
)
COVERAGE_INPUT = (
    ROOT / "scraper" / "playwright" / "top500_goal_entity_coverage_v5.json"
)
RANKING_AUDIT_INPUT = (
    ROOT / "scraper" / "programs" / "top500_targets_audit_v3.json"
)
PRIORITY_URL_INPUT = (
    ROOT / "scraper" / "playwright" / "top500_engineering_priority_queue_v4.json"
)
OUTPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top350_engineering_zero_candidate_browser_queue_v4.json"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build_queue(
    queue_payload: Any,
    coverage_payload: Any,
    ranking_audit_payload: Any,
    rows_by_source: Dict[str, List[Dict[str, Any]]],
    priority_url_payload: Any = None,
    row_limit: int = 350,
    generated_at: Optional[str] = None,
    source_queue_file: str = str(QUEUE_INPUT),
    source_coverage_file: str = str(COVERAGE_INPUT),
    source_ranking_audit_file: str = str(RANKING_AUDIT_INPUT),
    source_priority_url_file: str = str(PRIORITY_URL_INPUT),
) -> Dict[str, Any]:
    if not isinstance(queue_payload, dict) or not isinstance(
        queue_payload.get("items"), list
    ):
        raise ValueError("engineering browser queue must contain an items array")
    if not isinstance(coverage_payload, dict):
        raise ValueError("coverage payload must be an object")
    if not isinstance(ranking_audit_payload, dict):
        raise ValueError("ranking audit payload must be an object")

    entities, id_map = entity_maps(coverage_payload, ranking_audit_payload)
    selected, _, ranking_summary = build_row_scope(
        rows_by_source, id_map, row_limit
    )
    recovered_ids = {
        str(item.get("canonicalId"))
        for item in ((priority_url_payload or {}).get("items") or [])
        if isinstance(item, dict) and item.get("canonicalId") and item.get("url")
    }

    items: List[Dict[str, Any]] = []
    exclusions = Counter()
    source_task_counts = Counter()
    for source_item in queue_payload["items"]:
        if not isinstance(source_item, dict):
            exclusions["invalid-queue-item"] += 1
            continue
        university_id = str(source_item.get("universityId") or "")
        canonical_id = id_map.get(university_id)
        if not canonical_id:
            exclusions["canonical-institution-unmapped"] += 1
            continue
        entity_country = (entities.get(canonical_id) or {}).get("country")
        if is_mainland_china_country(entity_country or source_item.get("country")):
            exclusions["excluded-country:china"] += 1
            continue
        selections = selected.get(canonical_id)
        if not selections:
            exclusions["outside-first-%d-rows" % row_limit] += 1
            continue
        if canonical_id in recovered_ids:
            exclusions["recovered-program-url"] += 1
            continue

        item = copy.deepcopy(source_item)
        item["canonicalId"] = canonical_id
        item["top350Selections"] = copy.deepcopy(selections)
        item["sourcePriorityPosition"] = source_item.get("priorityPosition")
        item["priorityPosition"] = len(items)
        items.append(item)
        for selection in selections:
            source_task_counts[selection["source"]] += 1

    signal_counts = Counter(
        str((item.get("engineeringVisibleTextSignals") or {}).get("level") or "unknown")
        for item in items
    )
    country_counts = Counter(str(item.get("country") or "") for item in items)
    status_counts = Counter(str(item.get("status") or "") for item in items)
    excluded_rows = sum(exclusions.values())

    return {
        "schemaVersion": 1,
        "generatedAt": generated_at or utc_now(),
        "sourceQueueFile": source_queue_file,
        "sourceCoverageFile": source_coverage_file,
        "sourceRankingAuditFile": source_ranking_audit_file,
        "sourcePriorityUrlFile": source_priority_url_file,
        "scope": {
            "selectionBasis": "first-%d-rows" % row_limit,
            "rowIndexBase": 0,
            "rankingSources": list(RANKING_SOURCE_ORDER),
            "rankingRowSummary": ranking_summary,
            "canonicalInstitutionUnionCount": len(selected),
        },
        "policy": {
            "networkAccessUsedByBuilder": False,
            "sourceQueueModified": False,
            "sourceRankingDataModified": False,
            "displayedRankUsedForSelection": False,
            "canonicalMappingImplementation": (
                "scraper.programs.build_engineering_priority_queue_v4"
            ),
            "recoveredInstitutionsExcluded": True,
            "mainlandChinaInstitutionsExcluded": True,
            "hongKongAndMacauExcludedByThisRule": False,
        },
        "summary": {
            "sourceQueueRows": len(queue_payload["items"]),
            "scopedTasks": len(items),
            "excludedRows": excluded_rows,
            "exclusionCounts": dict(sorted(exclusions.items())),
            "tasksByTop350RankingSource": {
                source: source_task_counts[source]
                for source in RANKING_SOURCE_ORDER
            },
            "engineeringSignalLevelCounts": dict(sorted(signal_counts.items())),
            "countryCounts": dict(sorted(country_counts.items())),
            "statusCounts": dict(sorted(status_counts.items())),
        },
        "items": items,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-input", type=Path, default=QUEUE_INPUT)
    parser.add_argument("--coverage-input", type=Path, default=COVERAGE_INPUT)
    parser.add_argument("--ranking-audit", type=Path, default=RANKING_AUDIT_INPUT)
    parser.add_argument("--priority-url-input", type=Path, default=PRIORITY_URL_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--row-limit", type=int, default=350)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    queue_payload = load_json(args.queue_input)
    coverage_payload = load_json(args.coverage_input)
    ranking_audit_payload = load_json(args.ranking_audit)
    priority_url_payload = load_json(args.priority_url_input)
    result = build_queue(
        queue_payload,
        coverage_payload,
        ranking_audit_payload,
        ranking_rows(ranking_audit_payload, args.row_limit),
        priority_url_payload=priority_url_payload,
        row_limit=args.row_limit,
        source_queue_file=str(args.queue_input.resolve()),
        source_coverage_file=str(args.coverage_input.resolve()),
        source_ranking_audit_file=str(args.ranking_audit.resolve()),
        source_priority_url_file=str(args.priority_url_input.resolve()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
