"""Export Feature 2 official programme URLs from existing raw manifests.

This is a URL-only, offline export.  Top 350 selection is based strictly on
the first 350 array rows in each original ranking JSON, not displayed rank.
It does not read raw page bodies or export application-detail fields.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from scraper.programs.scope_policy import is_mainland_china_country


ROOT = Path(__file__).resolve().parent.parent.parent
COVERAGE = ROOT / "scraper" / "playwright" / "top500_goal_entity_coverage_v5.json"
RANKING_AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit_v3.json"
RAW_ROOTS = (
    ROOT / "scraper" / "playwright" / "_programs_full_raw",
    ROOT / "scraper" / "playwright" / "_top500_programs_raw",
    ROOT / "scraper" / "playwright" / "_top500_catalog_discovery_raw_v4",
    ROOT / "scraper" / "playwright" / "_top500_browser_recovered_raw_v4",
    ROOT / "scraper" / "playwright" / "_top350_engineering_url_recovery_batch_01_raw",
    ROOT / "scraper" / "playwright" / "_top350_engineering_browser_recovered_raw_v1",
)
OUTPUT = ROOT / "scraper" / "playwright" / "top500_engineering_priority_queue_v4.json"
URL_OUTPUT = ROOT / "scraper" / "playwright" / "top350_cs_engineering_official_urls_v1.txt"
RANKING_SOURCE_ORDER = ("qs", "the", "arwu", "usnews")

ENGINEERING_TERMS = (
    ("computer-science", "computer science", 12),
    ("computer-science", "computing", 8),
    ("computer-science", "informatics", 7),
    ("software", "software engineering", 12),
    ("software", "software", 8),
    ("data-ai", "data science", 12),
    ("data-ai", "data analytics", 9),
    ("data-ai", "artificial intelligence", 12),
    ("data-ai", "machine learning", 12),
    ("data-ai", "deep learning", 10),
    ("electrical-electronics", "electrical engineering", 12),
    ("electrical-electronics", "electronic engineering", 12),
    ("electrical-electronics", "electronics", 8),
    ("electrical-electronics", "embedded systems", 10),
    ("electrical-electronics", "telecommunications", 8),
    ("mechanical", "mechanical engineering", 12),
    ("mechanical", "mechatronics", 11),
    ("civil", "civil engineering", 12),
    ("civil", "structural engineering", 11),
    ("chemical", "chemical engineering", 12),
    ("chemical", "process engineering", 8),
    ("biomedical", "biomedical engineering", 12),
    ("biomedical", "bioengineering", 11),
    ("biomedical", "biotechnology", 7),
    ("aerospace", "aerospace engineering", 12),
    ("aerospace", "aeronautical engineering", 12),
    ("environmental-energy", "environmental engineering", 12),
    ("environmental-energy", "energy engineering", 11),
    ("environmental-energy", "energy systems", 9),
    ("environmental-energy", "renewable energy", 9),
    ("materials", "materials science", 11),
    ("materials", "materials engineering", 12),
    ("industrial-systems", "industrial engineering", 12),
    ("industrial-systems", "systems engineering", 10),
    ("industrial-systems", "engineering management", 6),
    ("industrial-systems", "construction management", 8),
    ("data-ai", "digital transformation", 7),
    ("robotics", "robotics", 12),
    ("robotics", "autonomous systems", 10),
    ("robotics", "robotic", 10),
    ("engineering-general", "master of technology", 10),
    ("engineering-general", "m tech", 8),
    ("engineering-general", "engineering", 5),
)
COMPILED_TERMS = tuple(
    (category, weight, re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"))
    for category, term, weight in ENGINEERING_TERMS
)
CS_CATEGORIES = {"computer-science", "software", "data-ai"}
WORD_RE = re.compile(r"[^a-z0-9]+")
SPECIFIC_PROGRAM_SURFACE_RE = re.compile(
    r"(?:\bmaster(?:'s)?\b|\bmsc\b|\bm\.sc\b|\bpostgraduate\b|"
    r"/(?:area-of-study|fields-study)/[^/?#]+)",
    re.I,
)
ENGINEERING_CATALOG_RE = re.compile(
    r"(?:/(?:areas-of-study|academic-study)/engineering(?:/|$)|"
    r"\b(?:study|degrees?|programmes?|programs?)\b.{0,80}\bengineering\b)",
    re.I,
)
CURATED_RECOVERY_SURFACE_RE = re.compile(
    r"(?:^/Admission/Graduate\.htm$|"
    r"^/Pages/Admission/Home/Postgraduate\.aspx$|"
    r"^/Pages/Admission/Postgraduate/Master-by-Coursework(?:/"
    r"(?:Master-of-Science|MSc|MSC)-[^/]+)?\.aspx$|"
    r"^/academics/optionreps/?$)",
    re.I,
)
MALFORMED_TRACKING_PATH_RE = re.compile(
    r"/?&(?=(?:utm_[a-z0-9_]+|gclid|fbclid|msclkid)=)",
    re.I,
)
TRACKING_QUERY_KEYS = {"gclid", "fbclid", "msclkid"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parts = urlsplit(text)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return ""
    host = (parts.hostname or "").casefold().rstrip(".")
    try:
        port = parts.port
    except ValueError:
        return ""
    netloc = host
    if port and not ((parts.scheme.casefold() == "http" and port == 80) or (parts.scheme.casefold() == "https" and port == 443)):
        netloc = "%s:%d" % (host, port)
    path = MALFORMED_TRACKING_PATH_RE.split(parts.path or "/", maxsplit=1)[0] or "/"
    query = urlencode([
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in TRACKING_QUERY_KEYS
    ], doseq=True)
    return urlunsplit((parts.scheme.casefold(), netloc, path, query, ""))


def entity_maps(coverage: Dict[str, Any], audit: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    entities: Dict[str, Dict[str, Any]] = {}
    id_map: Dict[str, str] = {}
    combined = list(coverage.get("entities") or []) + list(audit.get("entities") or [])
    for entity in combined:
        if not isinstance(entity, dict) or not entity.get("canonicalId"):
            continue
        canonical = str(entity["canonicalId"])
        current = entities.setdefault(canonical, {})
        for key in ("canonicalId", "name", "country", "rankingSources"):
            if entity.get(key) is not None:
                current[key] = entity.get(key)
        identifiers = [canonical]
        identifiers.extend(entity.get("sourceUniversityIds") or [])
        identifiers.extend(entity.get("existingRawTargetIds") or [])
        if entity.get("existingRawTargetId"):
            identifiers.append(entity["existingRawTargetId"])
        for raw in list(entity.get("existingRawSources") or []) + list(entity.get("newRawSources") or []):
            if isinstance(raw, dict) and raw.get("targetId"):
                identifiers.append(raw["targetId"])
        for identifier in identifiers:
            if identifier:
                id_map[str(identifier)] = canonical
    return entities, id_map


def ranking_rows(audit: Dict[str, Any], row_limit: int) -> Dict[str, List[Dict[str, Any]]]:
    if row_limit < 1:
        raise ValueError("row_limit must be at least 1")
    result: Dict[str, List[Dict[str, Any]]] = {}
    for source in RANKING_SOURCE_ORDER:
        metadata = (audit.get("sources") or {}).get(source) or {}
        input_file = metadata.get("inputFile")
        if not input_file:
            raise ValueError("ranking inputFile missing for %s" % source)
        rows = load_json(Path(str(input_file)))
        if not isinstance(rows, list) or len(rows) < row_limit:
            raise ValueError("ranking source %s has fewer than %d rows" % (source, row_limit))
        result[source] = rows
    return result


def build_row_scope(
    rows_by_source: Dict[str, List[Dict[str, Any]]],
    id_map: Dict[str, str],
    row_limit: int,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, set], Dict[str, Any]]:
    selected: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    deferred: Dict[str, set] = defaultdict(set)
    selected_counts = Counter()
    mapped_counts = Counter()
    unknown_counts = Counter()
    deferred_row_counts = Counter()
    for source in RANKING_SOURCE_ORDER:
        rows = rows_by_source[source]
        for row_index, row in enumerate(rows):
            university_id = str((row or {}).get("universityId") or "")
            canonical = id_map.get(university_id)
            if row_index < row_limit:
                selected_counts[source] += 1
                if not canonical:
                    unknown_counts[source] += 1
                    continue
                mapped_counts[source] += 1
                selected[canonical].append({
                    "source": source,
                    "rowIndex": row_index,
                    "displayedRank": row.get("rank"),
                    "year": row.get("year"),
                    "selectionBasis": "first-%d-rows" % row_limit,
                })
            elif canonical:
                deferred[canonical].add(source)
                deferred_row_counts[source] += 1
    for values in selected.values():
        values.sort(key=lambda item: (RANKING_SOURCE_ORDER.index(item["source"]), item["rowIndex"]))
    summary = {
        "selectedRowsBySource": {source: selected_counts[source] for source in RANKING_SOURCE_ORDER},
        "mappedSelectedRowsBySource": {source: mapped_counts[source] for source in RANKING_SOURCE_ORDER},
        "unknownSelectedRowsBySource": {source: unknown_counts[source] for source in RANKING_SOURCE_ORDER},
        "deferredRowsBySource": {source: deferred_row_counts[source] for source in RANKING_SOURCE_ORDER},
        "selectedCanonicalEntityCount": len(selected),
    }
    return dict(selected), dict(deferred), summary


def manifest_paths(raw_roots: Sequence[Path]) -> List[Tuple[str, Path]]:
    rows: List[Tuple[str, Path]] = []
    for root in raw_roots:
        if root.exists():
            rows.extend((root.name, path.resolve()) for path in root.glob("*/manifest.json"))
    return sorted(rows, key=lambda item: (item[0], str(item[1]).casefold()))


def surface_signal(values: Iterable[Any]) -> Tuple[int, str]:
    text = WORD_RE.sub(" ", " ".join(str(value or "") for value in values).casefold()).strip()
    categories = set()
    score = 0
    for category, weight, pattern in COMPILED_TERMS:
        if pattern.search(text):
            categories.add(category)
            score += weight
    has_cs = bool(categories & CS_CATEGORIES)
    has_engineering = bool(categories - CS_CATEGORIES)
    if has_cs and has_engineering:
        group = "cs+engineering"
    elif has_cs:
        group = "cs"
    elif has_engineering:
        group = "engineering"
    else:
        group = "none"
    return score, group


def recovery_page_is_program_evidence(url: str, page: Dict[str, Any]) -> bool:
    if page.get("status") != "captured" or page.get("blocked"):
        return False
    if page.get("eligibleAsProgramEvidence") is not True:
        return False
    kind = str(page.get("kind") or "").casefold()
    if kind not in {"category", "catalog", "program"}:
        return False
    path = urlsplit(url).path or "/"
    if CURATED_RECOVERY_SURFACE_RE.search(path):
        return True
    title = str(page.get("documentTitle") or "")
    score, group = surface_signal((url, title))
    if score <= 0 or group == "none":
        return False
    if kind == "program":
        return True
    surface = "%s %s" % (url, title)
    if kind == "category":
        return bool(SPECIFIC_PROGRAM_SURFACE_RE.search(surface))
    return path != "/" and bool(ENGINEERING_CATALOG_RE.search(surface))


def scan_manifests(
    manifests: Iterable[Tuple[str, Path, Dict[str, Any]]],
    id_map: Dict[str, str],
) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Dict[str, int]]:
    observations: Dict[Tuple[str, str], Dict[str, Any]] = {}
    counts = Counter()
    for corpus, manifest_file, manifest in manifests:
        counts["manifestCount"] += 1
        canonical = id_map.get(str(manifest.get("universityId") or ""))
        if not canonical:
            counts["unmappedManifestCount"] += 1
            continue
        counts["mappedManifestCount"] += 1
        candidates = ((manifest.get("discovery") or {}).get("programCandidates") or {})
        pages = manifest.get("pages") or {}
        visited = ((manifest.get("discovery") or {}).get("visited") or {})
        urls = set(str(url) for url in candidates)
        urls.update(str(url) for url, page in pages.items() if isinstance(page, dict) and page.get("kind") == "program")
        if corpus.startswith("_top350_engineering_url_recovery_batch_"):
            urls.update(
                str(url)
                for url, page in visited.items()
                if isinstance(page, dict)
                and recovery_page_is_program_evidence(str(url), page)
            )
        for url in urls:
            normalized = normalize_url(url)
            if not normalized:
                counts["invalidUrlCount"] += 1
                continue
            normalized_parts = urlsplit(normalized)
            if (normalized_parts.path or "/") == "/" and not normalized_parts.query:
                counts["genericRootUrlCount"] += 1
                continue
            candidate = candidates.get(url) if isinstance(candidates.get(url), dict) else {}
            page = pages.get(url) if isinstance(pages.get(url), dict) else {}
            if not page and isinstance(visited.get(url), dict):
                page = visited[url]
            score, group = surface_signal((
                url,
                candidate.get("text"),
                page.get("text"),
                page.get("documentTitle"),
            ))
            if (
                group == "none"
                and corpus.startswith("_top350_engineering_url_recovery_batch_")
                and recovery_page_is_program_evidence(url, page)
            ):
                group = "engineering"
                score = max(score, 1)
            key = (canonical, normalized)
            row = observations.setdefault(key, {
                "urls": set(),
                "sourceUrls": set(),
                "score": 0,
                "groups": set(),
            })
            row["urls"].add(url)
            source_url = candidate.get("sourceUrl") or page.get("sourceUrl")
            if source_url and normalize_url(source_url):
                row["sourceUrls"].add(str(source_url))
            row["score"] = max(int(row["score"]), score)
            if group != "none":
                row["groups"].add(group)
            counts["candidateObservations"] += 1
    counts["deduplicatedCandidateUrls"] = len(observations)
    return observations, dict(counts)


def load_manifests(raw_roots: Sequence[Path]) -> List[Tuple[str, Path, Dict[str, Any]]]:
    result = []
    for corpus, path in manifest_paths(raw_roots):
        try:
            manifest = load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(manifest, dict):
            result.append((corpus, path, manifest))
    return result


def build_export(
    coverage: Dict[str, Any],
    audit: Dict[str, Any],
    rows_by_source: Dict[str, List[Dict[str, Any]]],
    manifests: Iterable[Tuple[str, Path, Dict[str, Any]]],
    row_limit: int = 350,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    entities, id_map = entity_maps(coverage, audit)
    selected, deferred, row_summary = build_row_scope(rows_by_source, id_map, row_limit)
    observations, manifest_summary = scan_manifests(manifests, id_map)
    export_rows = []
    signal_groups = Counter()
    top_scope_no_signal = 0
    deferred_candidate_count = 0
    unknown_candidate_count = 0
    excluded_country_candidates = 0
    excluded_country_entities = set()
    for (canonical, normalized), observation in observations.items():
        entity = entities.get(canonical) or {}
        if is_mainland_china_country(entity.get("country")):
            excluded_country_candidates += 1
            excluded_country_entities.add(canonical)
            continue
        selections = selected.get(canonical) or []
        if not selections:
            if canonical in deferred:
                deferred_candidate_count += 1
            else:
                unknown_candidate_count += 1
            continue
        if not observation["groups"]:
            top_scope_no_signal += 1
            continue
        if "cs+engineering" in observation["groups"] or ({"cs", "engineering"} <= observation["groups"]):
            group = "cs+engineering"
        elif "cs" in observation["groups"]:
            group = "cs"
        else:
            group = "engineering"
        signal_groups[group] += 1
        export_rows.append({
            "url": normalized,
            "sourceUrl": sorted(observation["sourceUrls"])[0] if observation["sourceUrls"] else None,
            "canonicalId": canonical,
            "universityName": entity.get("name"),
            "top350Selections": selections,
            "_priorityGroup": group,
            "_score": observation["score"],
            "_normalizedUrl": normalized,
        })
    group_order = {"cs+engineering": 0, "cs": 1, "engineering": 2}
    export_rows.sort(key=lambda item: (
        group_order[item["_priorityGroup"]],
        -int(item["_score"]),
        str(item.get("universityName") or "").casefold(),
        item["canonicalId"],
        item["_normalizedUrl"],
    ))
    for item in export_rows:
        item.pop("_priorityGroup", None)
        item.pop("_score", None)
        item.pop("_normalizedUrl", None)
    selected_rows = row_summary["selectedRowsBySource"]
    if any(selected_rows[source] != row_limit for source in RANKING_SOURCE_ORDER):
        raise ValueError("each ranking source must contribute exactly %d rows" % row_limit)
    summary = dict(manifest_summary)
    summary.update({
        "urlOnlyExportCount": len(export_rows),
        "top350NoSignalCount": top_scope_no_signal,
        "deferredCandidateCount": deferred_candidate_count,
        "unknownCandidateCount": unknown_candidate_count,
        "excludedMainlandChinaCandidateCount": excluded_country_candidates,
        "excludedMainlandChinaEntityCount": len(excluded_country_entities),
        "signalGroupCounts": {name: signal_groups[name] for name in ("cs+engineering", "cs", "engineering")},
    })
    return {
        "schemaVersion": 2,
        "generatedAt": generated_at or utc_now(),
        "feature2": {
            "scope": "CS/Engineering URL-only export for canonical entities selected from the first %d rows of each original ranking JSON array" % row_limit,
            "selectionBasis": "first-%d-rows" % row_limit,
            "rowIndexBase": 0,
            "rankingSources": list(RANKING_SOURCE_ORDER),
            "rankingRowSummary": row_summary,
            "deferredAndUnknownAreStatisticsOnly": True,
        },
        "policy": {
            "networkAccessUsedByBuilder": False,
            "rawPageBodiesRead": False,
            "rawOrFrontendMutations": False,
            "urlsCopiedFromManifestOnly": True,
            "applicationDetailFieldsExported": False,
            "finalSubjectClassification": False,
            "mainlandChinaInstitutionsExcluded": True,
            "hongKongAndMacauExcludedByThisRule": False,
        },
        "summary": summary,
        "items": export_rows,
    }


def url_lines(result: Dict[str, Any]) -> List[str]:
    """Return a stable, deduplicated URL-only delivery list."""
    seen = set()
    urls = []
    for item in result.get("items") or []:
        url = str((item or {}).get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=COVERAGE)
    parser.add_argument("--ranking-audit", type=Path, default=RANKING_AUDIT)
    parser.add_argument("--raw-root", type=Path, action="append", dest="raw_roots")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--url-output", type=Path, default=URL_OUTPUT)
    parser.add_argument("--row-limit", type=int, default=350)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    roots = tuple(args.raw_roots or RAW_ROOTS)
    coverage = load_json(args.coverage, {})
    audit = load_json(args.ranking_audit, {})
    result = build_export(
        coverage,
        audit,
        ranking_rows(audit, args.row_limit),
        load_manifests(roots),
        row_limit=args.row_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    urls = url_lines(result)
    args.url_output.parent.mkdir(parents=True, exist_ok=True)
    args.url_output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print("[engineering-url-only-export] wrote %d URLs to %s" % (len(urls), args.url_output))


if __name__ == "__main__":
    main()
