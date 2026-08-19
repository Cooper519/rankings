"""Read-only engineering-focused application evidence audit.

The audit combines the four existing raw corpora and the existing application
evidence audit.  Engineering candidates are selected only when a traceable
engineering keyword occurs in the recorded programme URL, discovery text, or
captured programme raw body.  This is a prioritisation signal, not a final
discipline classification.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from scraper.programs.audit_raw_application_evidence import (
    detect_signals,
    read_raw_text,
    url_key,
)
from scraper.programs.build_engineering_priority_queue_v4 import (
    RANKING_SOURCE_ORDER,
    build_row_scope,
    entity_maps,
    ranking_rows,
)
from scraper.programs.scope_policy import is_mainland_china_country


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPORA = (
    ("existing", ROOT / "scraper" / "playwright" / "_programs_full_raw"),
    ("top500", ROOT / "scraper" / "playwright" / "_top500_programs_raw"),
    ("catalogDiscovery", ROOT / "scraper" / "playwright" / "_top500_catalog_discovery_raw_v4"),
    ("browserRecovery", ROOT / "scraper" / "playwright" / "_top500_browser_recovered_raw_v4"),
    ("engineeringRecovery", ROOT / "scraper" / "playwright" / "_top350_engineering_url_recovery_batch_01_raw"),
    ("engineeringBrowserRecovery", ROOT / "scraper" / "playwright" / "_top350_engineering_browser_recovered_raw_v1"),
)
DEFAULT_TARGET_AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit_v3.json"
DEFAULT_APPLICATION_AUDIT = ROOT / "scraper" / "playwright" / "_raw_application_evidence_audit.json"
DEFAULT_ALIASES = ROOT / "frontend" / "public" / "data" / "university_aliases.json"
DEFAULT_PRIORITY_FILES = (
    ROOT / "scraper" / "playwright" / "catalog_overrides_priority_a.json",
    ROOT / "scraper" / "playwright" / "catalog_overrides_priority_b.json",
    ROOT / "scraper" / "playwright" / "catalog_overrides_priority_c.json",
    ROOT / "scraper" / "playwright" / "top500_catalog_discovery_application_gap_queue_v4.json",
    ROOT / "scraper" / "playwright" / "application_gap_queue.json",
)
DEFAULT_OUTPUT = ROOT / "scraper" / "playwright" / "top500_engineering_application_evidence_audit_v4.json"

CATEGORIES = ("requirements", "deadline", "applicationWindow", "documents", "language")
STATUS_ORDER = {"captured": 5, "blocked": 4, "error": 3, "pending": 2, "missing": 1, "unknown": 0}

# High-priority terms are explicit engineering disciplines or the engineering
# root itself.  Adjacent terms are reported for context but never qualify a
# candidate on their own.
HIGH_KEYWORDS = (
    "engineering", "engineer", "aerospace", "aeronautical", "architectural",
    "automotive", "biomedical", "chemical", "civil", "electrical", "electronic",
    "environmental", "geotechnical", "industrial", "manufacturing", "materials",
    "mechanical", "mechatronic", "nuclear", "petroleum", "robotics", "structural",
    "telecommunications", "telecommunication", "transportation", "energy systems",
    "engineering physics", "engineering science", "software engineering",
    "computer engineering", "systems engineering", "data engineering",
)
ADJACENT_KEYWORDS = (
    "technology", "technical", "computing", "informatics", "information systems",
    "computer science", "data science", "physics", "architecture", "biotechnology",
)
KEYWORD_PATTERNS = {
    "high": [(term, re.compile(r"\b" + re.escape(term) + r"\b", re.I)) for term in HIGH_KEYWORDS],
    "adjacent": [(term, re.compile(r"\b" + re.escape(term) + r"\b", re.I)) for term in ADJACENT_KEYWORDS],
}


def load_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return fallback


def rate(count: int, total: int) -> float:
    return round(float(count) / total, 4) if total else 0.0


def canonical_id(value: Any, aliases: Dict[str, str]) -> str:
    current = str(value or "")
    seen = set()
    while current and current not in seen and aliases.get(current, current) != current:
        seen.add(current)
        current = aliases[current]
    return current


def alias_map(aliases_path: Path, target_audit: Dict[str, Any]) -> Dict[str, str]:
    payload = load_json(aliases_path, {}) or {}
    result = payload.get("canonicalById", payload) if isinstance(payload, dict) else {}
    result = {str(key): str(value) for key, value in result.items() if value}
    for entity in target_audit.get("entities") or []:
        cid = str(entity.get("canonicalId") or "")
        for identifier in [cid] + list(entity.get("sourceUniversityIds") or []) + list(entity.get("existingRawTargetIds") or []):
            if identifier:
                result.setdefault(str(identifier), cid)
    return result


def valid_url(value: Any) -> bool:
    return bool(re.match(r"^https?://[^\s]+$", str(value or ""), re.I))


def status_of(record: Any, fallback: str = "pending") -> str:
    if not isinstance(record, dict):
        return fallback
    value = str(record.get("status") or fallback).lower()
    return value if value in STATUS_ORDER else "unknown"


def best_status(statuses: Iterable[str]) -> str:
    values = list(statuses)
    return max(values or ["missing"], key=lambda item: STATUS_ORDER.get(item, 0))


def keyword_hits(url: str, discovery_text: str, raw_text: str) -> List[Dict[str, str]]:
    fields = (("programUrl", url), ("discoveryText", discovery_text), ("programRaw", raw_text))
    hits = []
    seen = set()
    for priority in ("high", "adjacent"):
        for term, pattern in KEYWORD_PATTERNS[priority]:
            for location, value in fields:
                if value and pattern.search(value):
                    marker = (priority, term, location)
                    if marker not in seen:
                        seen.add(marker)
                        hits.append({"keyword": term, "priority": priority, "location": location})
    return hits


def is_candidate(hits: List[Dict[str, str]]) -> bool:
    return any(item["priority"] == "high" for item in hits)


def read_manifest(path: Path) -> Optional[Dict[str, Any]]:
    payload = load_json(path)
    return payload if isinstance(payload, dict) else None


def page_for(pages: Dict[str, Any], normalized: str) -> Dict[str, Any]:
    for raw_url, record in pages.items():
        if url_key(raw_url) == normalized and isinstance(record, dict):
            return record
    return {}


def candidate_for(candidates: Dict[str, Any], normalized: str) -> Dict[str, Any]:
    for raw_url, record in candidates.items():
        if url_key(raw_url) == normalized and isinstance(record, dict):
            return record
    return {}


def raw_file_for(manifest_path: Path, page: Dict[str, Any]) -> Optional[Path]:
    value = page.get("file") or page.get("rawFile")
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else manifest_path.parent / path


def candidate_records(
    label: str,
    root: Path,
    aliases: Dict[str, str],
    excluded_ids: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    records = []
    inventory = Counter({"manifestFiles": 0, "unreadableManifests": 0})
    if not root.exists():
        return records, dict(inventory)
    for manifest_path in sorted(root.glob("*/manifest.json"), key=lambda item: item.as_posix()):
        inventory["manifestFiles"] += 1
        manifest = read_manifest(manifest_path)
        if not manifest:
            inventory["unreadableManifests"] += 1
            continue
        uid = str(manifest.get("universityId") or manifest_path.parent.name)
        cid = canonical_id(uid, aliases) or uid
        if cid in (excluded_ids or set()):
            inventory["excludedMainlandChinaManifests"] += 1
            continue
        pages = manifest.get("pages") or {}
        discovered = (manifest.get("discovery") or {}).get("programCandidates") or {}
        urls = set()
        for value in discovered.keys() if isinstance(discovered, dict) else []:
            normalized = url_key(value)
            if normalized:
                urls.add(normalized)
        for value, page in pages.items():
            if isinstance(page, dict) and page.get("kind") == "program":
                normalized = url_key(value)
                if normalized:
                    urls.add(normalized)
        page_records = {
            url_key(raw_url): page
            for raw_url, page in pages.items()
            if url_key(raw_url) and isinstance(page, dict)
        }
        raw_text_by_url: Dict[str, str] = {}
        application_sources: Dict[str, Dict[str, Set[str]]] = {
            normalized: {category: set() for category in CATEGORIES}
            for normalized in urls
        }
        for normalized in urls:
            page = page_for(pages, normalized)
            raw_text = read_raw_text(manifest_path.parent, page)
            raw_text_by_url[normalized] = raw_text
            for category in detect_signals(raw_text):
                if category in application_sources[normalized]:
                    application_sources[normalized][category].add(normalized)

        for raw_url, page in pages.items():
            if (
                not isinstance(page, dict)
                or page.get("kind") != "evidence"
                or page.get("status") != "captured"
            ):
                continue
            evidence_url = url_key(raw_url)
            signals = detect_signals(read_raw_text(manifest_path.parent, page))
            source = url_key(page.get("sourceUrl"))
            seen = set()
            while source and source not in urls and source not in seen:
                seen.add(source)
                parent = page_records.get(source) or {}
                source = url_key(parent.get("sourceUrl"))
            if source in urls:
                for category in signals:
                    if category in application_sources[source]:
                        application_sources[source][category].add(evidence_url or source)
        for normalized in sorted(urls):
            candidate = candidate_for(discovered, normalized) if isinstance(discovered, dict) else {}
            page = page_for(pages, normalized)
            page_status = status_of(page, status_of(candidate, "pending"))
            discovery_text = " ".join(str(candidate.get(key) or "") for key in ("text", "title", "label"))
            # Projected text is cheap classification evidence; captured raw is
            # still read so application evidence is not silently undercounted.
            projected_text = " ".join(
                str(page.get(key) or "") for key in ("text", "documentTitle", "headings", "title", "mainText", "bodyText")
            ) if page else ""
            raw_text = raw_text_by_url.get(normalized, "")
            hits = keyword_hits(normalized, discovery_text, projected_text + " " + raw_text)
            if not is_candidate(hits):
                continue
            source_url = candidate.get("sourceUrl") or page.get("sourceUrl")
            raw_file = raw_file_for(manifest_path, page)
            records.append({
                "canonicalId": cid,
                "universityId": uid,
                "universityName": manifest.get("universityName") or uid,
                "country": manifest.get("country") or "",
                "programUrl": normalized,
                "sourceUrl": source_url if valid_url(source_url) else None,
                "sourceUrlComplete": valid_url(source_url),
                "status": page_status,
                "corpus": label,
                "manifestFile": str(manifest_path.resolve()),
                "rawFile": str(raw_file.resolve()) if raw_file else None,
                "keywordHits": hits,
                "applicationSourceUrls": {
                    category: sorted(application_sources[normalized][category])
                    for category in CATEGORIES
                },
            })
    return records, dict(inventory)


def direct_audit_sources(application_audit: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    result = defaultdict(lambda: defaultdict(set))
    for university in application_audit.get("universities") or []:
        for program in university.get("programs") or []:
            normalized = url_key(program.get("url"))
            if not normalized:
                continue
            for category in CATEGORIES:
                evidence = program.get("deadline") if category == "deadline" else (program.get("coverage") or {}).get(category)
                for source in (evidence or {}).get("sources") or []:
                    if isinstance(source, dict) and source.get("inferredShared") is not True and valid_url(source.get("url")):
                        result[normalized][category].add(source["url"])
    return {url: {category: sorted(values) for category, values in categories.items()} for url, categories in result.items()}


def application_source_url_integrity(application_audit: Dict[str, Any]) -> Dict[str, int]:
    counts = Counter({"sourceRecords": 0, "valid": 0, "missing": 0, "invalid": 0})
    for university in application_audit.get("universities") or []:
        for program in university.get("programs") or []:
            evidences = []
            for category in CATEGORIES:
                evidence = program.get("deadline") if category == "deadline" else (program.get("coverage") or {}).get(category)
                evidences.extend((evidence or {}).get("sources") or [])
            for source in evidences:
                counts["sourceRecords"] += 1
                if not isinstance(source, dict) or not source.get("url"):
                    counts["missing"] += 1
                elif valid_url(source.get("url")):
                    counts["valid"] += 1
                else:
                    counts["invalid"] += 1
    return dict(counts)


def ranking_info(
    target_audit: Dict[str, Any],
    rows_by_source: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    row_limit: int = 350,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    if rows_by_source is None:
        rows_by_source = ranking_rows(target_audit, row_limit)
    _, id_map = entity_maps({"entities": []}, target_audit)
    selected, deferred, row_summary = build_row_scope(
        rows_by_source, id_map, row_limit
    )
    result = {}
    for entity in target_audit.get("entities") or []:
        cid = str(entity.get("canonicalId") or "")
        if is_mainland_china_country(entity.get("country")):
            continue
        sources = []
        ranks = {}
        for appearance in entity.get("rankingAppearances") or []:
            source = str(appearance.get("source") or "")
            if source:
                sources.append(source)
                ranks[source] = appearance.get("rank")
        selections = selected.get(cid) or []
        if selections:
            scope = "top350"
        elif cid in deferred:
            scope = "top351to500Deferred"
        else:
            scope = "top350Unknown"
        result[cid] = {
            "rankingSources": sorted(set(sources)),
            "ranks": ranks,
            "top500": bool(sources),
            "rankScope": scope,
            "top350Selections": selections,
        }
    return result, row_summary


def scope_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    coverage = {}
    for category in CATEGORIES:
        covered = sum(1 for row in rows if row["evidence"][category]["covered"])
        coverage[category] = {"coveredCount": covered, "coverageRate": rate(covered, len(rows))}
    statuses = Counter(row["status"] for row in rows)
    source_complete = sum(1 for row in rows if row["sourceUrlComplete"])
    return {
        "universityCount": len(set(row["canonicalId"] for row in rows)), "programCount": len(rows),
        "statusCounts": dict(sorted(statuses.items())), "coverage": coverage,
        "sourceUrl": {"completeCount": source_complete, "missingCount": len(rows) - source_complete, "completenessRate": rate(source_complete, len(rows))},
    }


def priority_index(paths: Iterable[Path]) -> Dict[str, Any]:
    by_url = defaultdict(list)
    by_entity = defaultdict(list)
    existing = []
    for path in paths:
        payload = load_json(path)
        if payload is None:
            continue
        existing.append(str(path.resolve()))
        values = []
        if isinstance(payload, dict):
            values.extend(payload.get("tasks") or [])
            values.extend(payload.get("items") or [])
            values.extend(payload.get("universities") or [])
            values.extend(payload.get("programs") or [])
            if not values and isinstance(payload.get("overrides"), list):
                values.extend(payload["overrides"])
        elif isinstance(payload, list):
            values = payload
        for position, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            uid = item.get("canonicalId") or item.get("universityId")
            url = item.get("programUrl") or item.get("url")
            row = {"source": str(path.resolve()), "position": item.get("queuePosition", position), "priority": item.get("priority")}
            if uid:
                by_entity[str(uid)].append(row)
            normalized = url_key(url)
            if normalized:
                by_url[normalized].append(row)
    return {"files": existing, "byUrl": dict(by_url), "byEntity": dict(by_entity)}


def build_audit(
    corpora: Iterable[Tuple[str, Path]],
    target_audit: Dict[str, Any],
    application_audit: Dict[str, Any],
    aliases_path: Path,
    priority_files: Iterable[Path],
    rows_by_source: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    row_limit: int = 350,
) -> Dict[str, Any]:
    aliases = alias_map(aliases_path, target_audit)
    excluded_ids = {
        str(entity.get("canonicalId"))
        for entity in target_audit.get("entities") or []
        if entity.get("canonicalId")
        and is_mainland_china_country(entity.get("country"))
    }
    country_by_id = {
        str(entity.get("canonicalId")): entity.get("country")
        for entity in target_audit.get("entities") or []
        if entity.get("canonicalId")
    }
    all_records = []
    corpus_inventory = {}
    for label, root in corpora:
        records, inventory = candidate_records(label, root, aliases, excluded_ids)
        all_records.extend(records)
        corpus_inventory[label] = inventory

    evidence = direct_audit_sources(application_audit)
    evidence_source_integrity = application_source_url_integrity(application_audit)
    rankings, ranking_row_summary = ranking_info(
        target_audit, rows_by_source=rows_by_source, row_limit=row_limit
    )
    priorities = priority_index(priority_files)
    grouped = {}
    for record in all_records:
        key = (record["canonicalId"], record["programUrl"])
        row = grouped.setdefault(key, {
            "canonicalId": record["canonicalId"], "universityName": record["universityName"],
            "country": record["country"], "programUrl": record["programUrl"], "corpusRecords": [],
            "statuses": set(), "keywordHits": [], "sourceUrls": set(), "rawFiles": set(),
            "applicationSourceUrls": {category: set() for category in CATEGORIES},
        })
        row["country"] = country_by_id.get(record["canonicalId"]) or row["country"]
        row["corpusRecords"].append(record)
        row["statuses"].add(record["status"])
        row["keywordHits"].extend(record["keywordHits"])
        if record["sourceUrl"]:
            row["sourceUrls"].add(record["sourceUrl"])
        if record["rawFile"]:
            row["rawFiles"].add(record["rawFile"])
        for category in CATEGORIES:
            row["applicationSourceUrls"][category].update(
                record.get("applicationSourceUrls", {}).get(category) or []
            )

    programs = []
    for row in sorted(grouped.values(), key=lambda item: (item["canonicalId"], item["programUrl"])):
        url = row["programUrl"]
        sources = {
            category: set(evidence.get(url, {}).get(category) or [])
            | set(row["applicationSourceUrls"][category])
            for category in CATEGORIES
        }
        status = best_status(row["statuses"])
        unique_hits = {(hit["priority"], hit["keyword"], hit["location"]) for hit in row["keywordHits"]}
        priority_rows = priorities["byUrl"].get(url, [])
        programs.append({
            "canonicalId": row["canonicalId"], "universityName": row["universityName"], "country": row["country"],
            "programUrl": url, "status": status, "statusByCorpus": {label: best_status(record["status"] for record in row["corpusRecords"] if record["corpus"] == label) for label, _ in corpora if any(record["corpus"] == label for record in row["corpusRecords"])},
            "rankScope": rankings.get(row["canonicalId"], {}).get("rankScope", "top350Unknown"),
            "rankEvidence": rankings.get(row["canonicalId"], {}).get("ranks", {}),
            "feature2Eligible": rankings.get(row["canonicalId"], {}).get("rankScope") == "top350",
            "corpora": sorted(set(record["corpus"] for record in row["corpusRecords"])),
            "keywordHits": [dict(zip(("priority", "keyword", "location"), item)) for item in sorted(unique_hits)],
            "sourceUrls": sorted(row["sourceUrls"]), "sourceUrlComplete": bool(row["sourceUrls"]),
            "rawFiles": sorted(row["rawFiles"]),
            "evidence": {category: {"covered": bool(sources[category]), "sourceUrls": sorted(sources[category])} for category in CATEGORIES},
            "priorityMatches": priority_rows,
        })

    by_entity = defaultdict(list)
    for program in programs:
        by_entity[program["canonicalId"]].append(program)
    universities = []
    for cid in sorted(by_entity):
        rows = by_entity[cid]
        first = rows[0]
        info = rankings.get(cid, {})
        coverage = {}
        for category in CATEGORIES:
            covered = sum(1 for program in rows if program["evidence"][category]["covered"])
            coverage[category] = {"coveredCount": covered, "coverageRate": rate(covered, len(rows))}
        statuses = Counter(program["status"] for program in rows)
        universities.append({
            "canonicalId": cid, "universityName": first["universityName"], "country": first["country"],
            "rankingSources": info.get("rankingSources", []), "ranks": info.get("ranks", {}), "rankScope": info.get("rankScope", "top350Unknown"), "top500": info.get("top500", False),
            "programCount": len(rows), "coverage": coverage, "sourceUrlCompleteCount": sum(1 for program in rows if program["sourceUrlComplete"]),
            "statusCounts": dict(sorted(statuses.items())), "programs": rows,
        })

    total = len(programs)
    summary_coverage = {}
    for category in CATEGORIES:
        covered = sum(1 for program in programs if program["evidence"][category]["covered"])
        summary_coverage[category] = {"coveredCount": covered, "coverageRate": rate(covered, total)}
    status_counts = Counter(program["status"] for program in programs)
    source_complete = sum(1 for program in programs if program["sourceUrlComplete"])
    rank_groups = defaultdict(list)
    for program in programs:
        rank_groups[program["rankScope"]].append(program)
    rank_scope = {
        "top350": scope_summary(rank_groups["top350"]),
        "top350Unknown": scope_summary(rank_groups["top350Unknown"]),
        "top351to500Deferred": scope_summary(rank_groups["top351to500Deferred"]),
    }
    return {
        "schemaVersion": 4, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "readOnly": True, "networkAccessUsed": False, "cleaningPerformed": False,
            "dateNormalizationPerformed": False, "manualCorrectionPerformed": False, "frontendModified": False,
            "engineeringClassification": "high-priority keyword in recorded programme URL, discovery text, or captured programme raw body",
            "classificationWarning": "Keyword priority is a crawl prioritisation signal, not a final subject or discipline judgement.",
            "strictRankScope": "Feature 2 eligibility uses canonical entities mapped from the first rows of each original ranking JSON array, never displayed rank values.",
            "rankUnknownPolicy": "Entities absent from both selected and deferred ranking rows remain top350Unknown.",
            "deferredPolicy": "Canonical entities found only after the selected row limit are retained in top351to500Deferred.",
            "evidencePolicy": "Direct source URLs come from captured programme raw, sourceUrl-linked evidence pages, and the existing application audit; unresolved shared evidence is excluded.",
            "mainlandChinaInstitutionsExcluded": True,
            "hongKongAndMacauExcludedByThisRule": False,
            "top350SelectionBasis": "first-%d-rows-per-ranking-source" % row_limit,
        },
        "inputs": {
            "targetAudit": str(DEFAULT_TARGET_AUDIT.resolve()), "applicationEvidenceAudit": str(DEFAULT_APPLICATION_AUDIT.resolve()),
            "aliases": str(aliases_path.resolve()), "corpora": [{"label": label, "root": str(root.resolve())} for label, root in corpora],
            "priorityFiles": [str(path.resolve()) for path in priority_files if path.exists()],
        },
        "engineeringKeywordPolicy": {"high": list(HIGH_KEYWORDS), "adjacentReportedOnly": list(ADJACENT_KEYWORDS), "requiresHighKeyword": True},
        "rankingScope": {
            "selectionBasis": "first-%d-rows-per-ranking-source" % row_limit,
            "rowIndexBase": 0,
            "rankingSources": list(RANKING_SOURCE_ORDER),
            "rankingRowSummary": ranking_row_summary,
        },
        "summary": {
            "engineeringUniversityCount": len(universities), "engineeringProgramCount": total,
            "top500EngineeringUniversityCount": sum(1 for item in universities if item["top500"]),
            "top500EngineeringProgramCount": sum(item["programCount"] for item in universities if item["top500"]),
            "statusCounts": dict(sorted(status_counts.items())), "coverage": summary_coverage,
            "sourceUrl": {"completeCount": source_complete, "missingCount": total - source_complete, "completenessRate": rate(source_complete, total)},
            "applicationEvidenceSourceUrl": evidence_source_integrity,
            "rankScope": {name: {"universityCount": value["universityCount"], "programCount": value["programCount"]} for name, value in rank_scope.items()},
            "priorityMatchedProgramCount": sum(1 for program in programs if program["priorityMatches"]),
            "priorityInputFilesFound": len(priorities["files"]),
            "excludedMainlandChinaEntityCount": len(excluded_ids),
        },
        "corpusInventory": corpus_inventory,
        "priority": {"files": priorities["files"], "matchedEngineeringPrograms": sum(1 for program in programs if program["priorityMatches"])},
        "rankScope": rank_scope,
        "universities": universities,
    }


def parse_corpora(values: Optional[List[str]]) -> List[Tuple[str, Path]]:
    if not values:
        return list(DEFAULT_CORPORA)
    result = []
    for value in values:
        if "=" not in value:
            raise ValueError("corpus must use label=path")
        label, path = value.split("=", 1)
        result.append((label, Path(path)))
    return result


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="append", help="label=path; may be repeated")
    parser.add_argument("--target-audit", type=Path, default=DEFAULT_TARGET_AUDIT)
    parser.add_argument("--application-audit", type=Path, default=DEFAULT_APPLICATION_AUDIT)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--priority", type=Path, action="append")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--row-limit", type=int, default=350)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    corpora = parse_corpora(args.corpus)
    priority_files = args.priority if args.priority is not None else list(DEFAULT_PRIORITY_FILES)
    target_audit = load_json(args.target_audit, {}) or {}
    audit = build_audit(
        corpora,
        target_audit,
        load_json(args.application_audit, {}) or {},
        args.aliases,
        priority_files,
        rows_by_source=ranking_rows(target_audit, args.row_limit),
        row_limit=args.row_limit,
    )
    audit["inputs"]["targetAudit"] = str(args.target_audit.resolve())
    audit["inputs"]["applicationEvidenceAudit"] = str(args.application_audit.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": audit["summary"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
