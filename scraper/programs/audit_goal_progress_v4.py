"""Read-only progress audit for the RankingSelect four-list Top 500 goal.

This module deliberately treats manifests and raw bodies as immutable evidence.
It does not normalize deadlines, clean programme records, or write frontend data.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scraper.programs.audit_raw_application_evidence import (
    CATEGORIES,
    detect_signals,
    read_raw_text,
    url_key,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET_AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit_v3.json"
DEFAULT_COVERAGE = ROOT / "scraper" / "playwright" / "top500_goal_entity_coverage_v3.json"
DEFAULT_OLD_RAW = ROOT / "scraper" / "playwright" / "_programs_full_raw"
DEFAULT_NEW_RAW = ROOT / "scraper" / "playwright" / "_top500_programs_raw"
DEFAULT_QUEUES = (
    ROOT / "scraper" / "playwright" / "top500_browser_recovery_queue.json",
    ROOT / "scraper" / "playwright" / "top500_recovered_blocked_browser_queue_v3.json",
)
DEFAULT_JSON = ROOT / "scraper" / "playwright" / "top500_goal_progress_audit_v4.json"
DEFAULT_MD = ROOT / "scraper" / "playwright" / "top500_goal_progress_audit_v4.md"

EVIDENCE_CATEGORIES = ("requirements", "deadline", "applicationWindow", "documents", "language")
ESSENTIAL_CATEGORIES = ("requirements", "deadline", "applicationWindow")
STATUS_PRECEDENCE = {"captured": 5, "blocked": 4, "error": 3, "pending": 2, "missing": 1, "unknown": 0}


def load_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return fallback


def rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def as_path(base: Path, value: Any) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_absolute() else base / path


def read_payload(path: Path) -> bytes:
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix.lower() == ".gz" else data


def deterministic_sample(items: list[Any], limit: int) -> list[Any]:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return items
    if limit == 1:
        return [items[0]]
    indexes = sorted({round(index * (len(items) - 1) / (limit - 1)) for index in range(limit)})
    return [items[index] for index in indexes]


def best_status(statuses: set[str]) -> str:
    return max(statuses or {"missing"}, key=lambda value: STATUS_PRECEDENCE.get(value, 0))


def target_maps(target_audit: dict) -> tuple[dict[str, str], dict[str, dict]]:
    id_to_canonical: dict[str, str] = {}
    entities: dict[str, dict] = {}
    for entity in target_audit.get("entities") or []:
        canonical_id = str(entity["canonicalId"])
        entities[canonical_id] = entity
        id_to_canonical[canonical_id] = canonical_id
        for key in ("sourceUniversityIds", "existingRawTargetIds"):
            for identifier in entity.get(key) or []:
                id_to_canonical[str(identifier)] = canonical_id
    return id_to_canonical, entities


def iter_manifest_records(manifest: dict):
    for url, record in (manifest.get("pages") or {}).items():
        if isinstance(record, dict):
            yield "pages", str(url), record
    for url, record in ((manifest.get("discovery") or {}).get("visited") or {}).items():
        if isinstance(record, dict):
            yield "discovery.visited", str(url), record


def inventory_corpus(root: Path, label: str, id_to_canonical: dict[str, str], hash_sample_size: int) -> tuple[dict, list[dict]]:
    directories = sorted(path for path in root.iterdir() if path.is_dir() and path.name != "_quarantine")
    summary = Counter()
    issues: dict[str, list] = defaultdict(list)
    mapped_manifests: list[dict] = []
    hash_candidates: dict[str, dict] = {}

    summary["directories"] = len(directories)
    for directory in directories:
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            summary["missingManifests"] += 1
            issues["missingManifests"].append(str(manifest_path.resolve()))
            continue
        summary["manifestFiles"] += 1
        try:
            manifest = load_json(manifest_path)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            summary["unreadableManifests"] += 1
            issues["unreadableManifests"].append({"file": str(manifest_path.resolve()), "error": str(exc)})
            continue
        if not isinstance(manifest, dict):
            summary["invalidManifests"] += 1
            issues["invalidManifests"].append(str(manifest_path.resolve()))
            continue

        required_missing = [key for key in ("universityId", "discovery", "pages") if key not in manifest]
        if required_missing:
            summary["manifestsMissingRequiredFields"] += 1
            issues["manifestsMissingRequiredFields"].append({
                "file": str(manifest_path.resolve()), "fields": required_missing,
            })
        uid = str(manifest.get("universityId") or directory.name)
        canonical_id = id_to_canonical.get(uid)
        if canonical_id:
            summary["mappedManifests"] += 1
            mapped_manifests.append({
                "corpus": label,
                "canonicalId": canonical_id,
                "universityId": uid,
                "directory": directory,
                "manifestFile": manifest_path,
                "manifest": manifest,
            })
        else:
            summary["unmappedManifests"] += 1
            issues["unmappedManifestIds"].append(uid)

        for section, url, record in iter_manifest_records(manifest):
            summary["manifestRecords"] += 1
            relative = record.get("file")
            if not relative:
                summary["recordsWithoutFile"] += 1
                continue
            raw_path = as_path(directory, relative)
            summary["fileReferences"] += 1
            if raw_path is None or not raw_path.exists():
                summary["missingReferencedFiles"] += 1
                issues["missingReferencedFiles"].append({
                    "manifest": str(manifest_path.resolve()), "section": section, "url": url,
                    "file": str(raw_path) if raw_path else str(relative),
                })
                continue
            summary["existingReferencedFiles"] += 1
            expected_hash = record.get("sha256")
            if expected_hash:
                summary["referencesWithSha256"] += 1
                key = str(raw_path.resolve()).lower()
                hash_candidates.setdefault(key, {
                    "corpus": label, "manifest": str(manifest_path.resolve()), "section": section,
                    "url": url, "file": raw_path, "expectedSha256": str(expected_hash),
                    "expectedBytes": record.get("bytes"),
                })
            else:
                summary["referencesWithoutSha256"] += 1

    hash_rows = []
    ordered_candidates = [hash_candidates[key] for key in sorted(hash_candidates)]
    for candidate in deterministic_sample(ordered_candidates, hash_sample_size):
        row = {key: value for key, value in candidate.items() if key != "file"}
        row["file"] = str(candidate["file"].resolve())
        try:
            payload = read_payload(candidate["file"])
            actual = hashlib.sha256(payload).hexdigest()
            row["actualSha256"] = actual
            row["actualBytes"] = len(payload)
            row["hashMatches"] = actual == candidate["expectedSha256"]
            row["bytesMatch"] = candidate.get("expectedBytes") is None or len(payload) == candidate["expectedBytes"]
            summary["hashSamplesChecked"] += 1
            summary["hashSamplesMatched"] += bool(row["hashMatches"])
            summary["hashSamplesMismatched"] += not row["hashMatches"]
            summary["byteSamplesMismatched"] += not row["bytesMatch"]
        except (OSError, EOFError) as exc:
            row["error"] = str(exc)
            row["hashMatches"] = False
            row["bytesMatch"] = False
            summary["hashSamplesChecked"] += 1
            summary["hashSamplesMismatched"] += 1
        hash_rows.append(row)

    return {
        "root": str(root.resolve()),
        "summary": dict(sorted(summary.items())),
        "issues": dict(issues),
        "hashSample": {
            "method": "deterministic evenly-spaced sample over sorted unique referenced files with manifest sha256",
            "requestedSize": hash_sample_size,
            "eligibleFiles": len(ordered_candidates),
            "items": hash_rows,
        },
    }, mapped_manifests


def page_for_url(pages_by_url: dict[str, list[tuple[dict, Path]]], normalized_url: str) -> tuple[dict, Path] | None:
    records = pages_by_url.get(normalized_url) or []
    if not records:
        return None
    return max(records, key=lambda item: STATUS_PRECEDENCE.get(str(item[0].get("status") or "unknown"), 0))


def scan_entities(entity_defs: dict[str, dict], manifests: list[dict]) -> tuple[dict[str, dict], dict]:
    groups: dict[str, dict] = {}
    for canonical_id, entity in entity_defs.items():
        groups[canonical_id] = {
            "canonicalId": canonical_id,
            "name": entity.get("name"),
            "country": entity.get("country"),
            "rankingSources": sorted(entity.get("rankingSources") or []),
            "manifests": {"existing": [], "new": []},
            "programs": {},
            "pageRecords": defaultdict(list),
            "evidence": [],
            "rawPageCounts": Counter(),
        }

    for envelope in manifests:
        group = groups[envelope["canonicalId"]]
        corpus_key = "existing" if envelope["corpus"] == "existing" else "new"
        manifest = envelope["manifest"]
        directory = envelope["directory"]
        pages = manifest.get("pages") or {}
        group["manifests"][corpus_key].append({
            "universityId": envelope["universityId"],
            "manifestFile": str(envelope["manifestFile"].resolve()),
            "manifestStatus": manifest.get("status"),
        })
        pages_by_url: dict[str, list[tuple[dict, Path]]] = defaultdict(list)
        for raw_url, page in pages.items():
            if not isinstance(page, dict):
                continue
            normalized = url_key(raw_url)
            if normalized:
                pages_by_url[normalized].append((page, directory))
                group["pageRecords"][normalized].append((page, directory))
            kind = str(page.get("kind") or "other")
            status = str(page.get("status") or "unknown")
            group["rawPageCounts"][(corpus_key, kind, status)] += 1

        candidates = (manifest.get("discovery") or {}).get("programCandidates") or {}
        for raw_url in candidates:
            normalized = url_key(raw_url)
            if not normalized:
                continue
            program = group["programs"].setdefault(normalized, {
                "url": normalized,
                "candidateStatuses": {"existing": set(), "new": set()},
                "pageStatuses": {"existing": set(), "new": set()},
                "directSignals": set(),
                "sharedSignals": set(),
            })
            matched = page_for_url(pages_by_url, normalized)
            status = str(matched[0].get("status") or "unknown") if matched else "missing"
            program["candidateStatuses"][corpus_key].add(status)

        for raw_url, page in pages.items():
            if not isinstance(page, dict):
                continue
            normalized = url_key(raw_url)
            kind = page.get("kind")
            if kind == "program" and normalized:
                program = group["programs"].setdefault(normalized, {
                    "url": normalized,
                    "candidateStatuses": {"existing": set(), "new": set()},
                    "pageStatuses": {"existing": set(), "new": set()},
                    "directSignals": set(),
                    "sharedSignals": set(),
                })
                program["pageStatuses"][corpus_key].add(str(page.get("status") or "unknown"))
                if page.get("status") == "captured" and page.get("file"):
                    program["directSignals"].update(detect_signals(read_raw_text(directory, page)))
            elif kind == "evidence" and page.get("status") == "captured" and page.get("file"):
                signals = detect_signals(read_raw_text(directory, page))
                if signals:
                    group["evidence"].append({
                        "url": normalized or str(raw_url),
                        "sourceUrl": url_key(page.get("sourceUrl")),
                        "signals": signals,
                    })

    candidate_summary = {
        "existing": Counter(), "new": Counter(), "combined": Counter(),
    }
    for group in groups.values():
        program_urls = set(group["programs"])
        for evidence in group["evidence"]:
            source = evidence["sourceUrl"]
            seen: set[str] = set()
            while source and source not in program_urls and source not in seen:
                seen.add(source)
                records = group["pageRecords"].get(source) or []
                parent = max(records, key=lambda item: STATUS_PRECEDENCE.get(str(item[0].get("status") or "unknown"), 0))[0] if records else None
                source = url_key(parent.get("sourceUrl")) if isinstance(parent, dict) else ""
            if source in program_urls:
                group["programs"][source]["directSignals"].update(evidence["signals"])
            else:
                for program in group["programs"].values():
                    program["sharedSignals"].update(evidence["signals"])

        for program in group["programs"].values():
            combined_statuses: set[str] = set()
            for corpus_key in ("existing", "new"):
                statuses = program["candidateStatuses"][corpus_key]
                if statuses:
                    status = best_status(statuses)
                    candidate_summary[corpus_key][status] += 1
                    candidate_summary[corpus_key]["total"] += 1
                    combined_statuses.update(statuses)
            if combined_statuses:
                candidate_summary["combined"][best_status(combined_statuses)] += 1
                candidate_summary["combined"]["total"] += 1

    return groups, {key: dict(sorted(value.items())) for key, value in candidate_summary.items()}


def summarize_evidence(groups: dict[str, dict], entity_defs: dict[str, dict]) -> tuple[dict, list[dict], dict]:
    entity_rows = []
    program_totals = {mode: Counter() for mode in ("direct", "includingShared")}
    entity_totals = {mode: Counter() for mode in ("direct", "includingShared")}
    by_source: dict[str, dict[str, Counter]] = defaultdict(lambda: {
        "program": Counter(), "entityDirect": Counter(), "entityIncludingShared": Counter(),
    })
    gap_groups: dict[str, list] = defaultdict(list)

    for canonical_id in sorted(groups):
        group = groups[canonical_id]
        programs = list(group["programs"].values())
        program_count = len(programs)
        row = {
            "canonicalId": canonical_id,
            "name": group["name"],
            "country": group["country"],
            "rankingSources": group["rankingSources"],
            "raw": {
                "existingManifestCount": len(group["manifests"]["existing"]),
                "newManifestCount": len(group["manifests"]["new"]),
                "programCount": program_count,
                "candidateStatus": {},
                "pageCounts": {
                    "%s:%s:%s" % key: value for key, value in sorted(group["rawPageCounts"].items())
                },
            },
            "evidence": {},
        }
        for corpus_key in ("existing", "new", "combined"):
            counts = Counter()
            for program in programs:
                statuses = set()
                if corpus_key in ("existing", "new"):
                    statuses.update(program["candidateStatuses"][corpus_key])
                else:
                    statuses.update(program["candidateStatuses"]["existing"])
                    statuses.update(program["candidateStatuses"]["new"])
                if statuses:
                    counts[best_status(statuses)] += 1
                    counts["total"] += 1
            row["raw"]["candidateStatus"][corpus_key] = dict(sorted(counts.items()))

        for mode in ("direct", "includingShared"):
            category_counts = {}
            for category in EVIDENCE_CATEGORIES:
                covered_urls = []
                for program in programs:
                    signals = program["directSignals"] if mode == "direct" else program["directSignals"] | program["sharedSignals"]
                    if category in signals:
                        covered_urls.append(program["url"])
                covered = len(covered_urls)
                category_counts[category] = {
                    "coveredPrograms": covered,
                    "uncoveredPrograms": program_count - covered,
                    "programCoverageRate": rate(covered, program_count),
                    "entityHasAny": covered > 0,
                    "entityFullyCovered": program_count > 0 and covered == program_count,
                    "uncoveredProgramSamples": [
                        program["url"] for program in programs
                        if category not in (program["directSignals"] if mode == "direct" else program["directSignals"] | program["sharedSignals"])
                    ][:10],
                }
                program_totals[mode][category] += covered
                entity_totals[mode][category + ":any"] += covered > 0
                entity_totals[mode][category + ":full"] += program_count > 0 and covered == program_count
            bundle_covered = 0
            for program in programs:
                signals = program["directSignals"] if mode == "direct" else program["directSignals"] | program["sharedSignals"]
                bundle_covered += all(category in signals for category in ESSENTIAL_CATEGORIES)
            category_counts["essentialBundle"] = {
                "coveredPrograms": bundle_covered,
                "uncoveredPrograms": program_count - bundle_covered,
                "programCoverageRate": rate(bundle_covered, program_count),
                "entityHasAny": bundle_covered > 0,
                "entityFullyCovered": program_count > 0 and bundle_covered == program_count,
            }
            program_totals[mode]["essentialBundle"] += bundle_covered
            entity_totals[mode]["essentialBundle:any"] += bundle_covered > 0
            entity_totals[mode]["essentialBundle:full"] += program_count > 0 and bundle_covered == program_count
            row["evidence"][mode] = category_counts

        if program_count:
            for category in ESSENTIAL_CATEGORIES:
                direct = row["evidence"]["direct"][category]
                if direct["uncoveredPrograms"]:
                    gap_groups["missingDirect" + category[0].upper() + category[1:]].append({
                        "canonicalId": canonical_id,
                        "name": group["name"],
                        "country": group["country"],
                        "programCount": program_count,
                        "uncoveredPrograms": direct["uncoveredPrograms"],
                        "samplePrograms": direct["uncoveredProgramSamples"],
                    })

        for source in group["rankingSources"]:
            slice_group = by_source[source]
            slice_group["program"]["total"] += program_count
            slice_group["program"]["entitiesWithPrograms"] += program_count > 0
            for category in EVIDENCE_CATEGORIES + ("essentialBundle",):
                direct = row["evidence"]["direct"][category]
                shared = row["evidence"]["includingShared"][category]
                slice_group["program"][category] += direct["coveredPrograms"]
                slice_group["entityDirect"][category + ":any"] += direct["entityHasAny"]
                slice_group["entityDirect"][category + ":full"] += direct["entityFullyCovered"]
                slice_group["entityIncludingShared"][category + ":any"] += shared["entityHasAny"]
                slice_group["entityIncludingShared"][category + ":full"] += shared["entityFullyCovered"]
        entity_rows.append(row)

    total_programs = sum(len(group["programs"]) for group in groups.values())
    entities_with_programs = sum(bool(group["programs"]) for group in groups.values())
    summary = {
        "programUniverse": {
            "definition": "deduplicated normalized URL union of programCandidates and pages[kind=program] across mapped existing/new manifests",
            "programs": total_programs,
            "entitiesWithPrograms": entities_with_programs,
            "entitiesWithoutPrograms": len(groups) - entities_with_programs,
        },
        "modes": {},
        "byRankingSource": {},
    }
    for mode in ("direct", "includingShared"):
        summary["modes"][mode] = {}
        for category in EVIDENCE_CATEGORIES + ("essentialBundle",):
            covered = program_totals[mode][category]
            summary["modes"][mode][category] = {
                "programLevel": {
                    "covered": covered,
                    "uncovered": total_programs - covered,
                    "coverageRate": rate(covered, total_programs),
                },
                "entityLevel": {
                    "denominatorEntitiesWithPrograms": entities_with_programs,
                    "withAnyCoveredProgram": entity_totals[mode][category + ":any"],
                    "allProgramsCovered": entity_totals[mode][category + ":full"],
                    "anyCoverageRate": rate(entity_totals[mode][category + ":any"], entities_with_programs),
                    "fullCoverageRate": rate(entity_totals[mode][category + ":full"], entities_with_programs),
                },
            }

    for source, counters in sorted(by_source.items()):
        total = counters["program"]["total"]
        entities_with = counters["program"]["entitiesWithPrograms"]
        source_row = {"programs": total, "entitiesWithPrograms": entities_with, "direct": {}, "includingShared": {}}
        for category in EVIDENCE_CATEGORIES + ("essentialBundle",):
            covered = counters["program"][category]
            source_row["direct"][category] = {
                "coveredPrograms": covered, "programCoverageRate": rate(covered, total),
                "entitiesWithAny": counters["entityDirect"][category + ":any"],
                "entitiesFull": counters["entityDirect"][category + ":full"],
            }
            source_row["includingShared"][category] = {
                "entitiesWithAny": counters["entityIncludingShared"][category + ":any"],
                "entitiesFull": counters["entityIncludingShared"][category + ":full"],
            }
        summary["byRankingSource"][source] = source_row
    return summary, entity_rows, dict(gap_groups)


def summarize_raw_coverage(entity_rows: list[dict], coverage_matrix: dict) -> dict:
    observed = Counter()
    by_source: dict[str, Counter] = defaultdict(Counter)
    for row in entity_rows:
        has_existing = row["raw"]["existingManifestCount"] > 0
        has_new = row["raw"]["newManifestCount"] > 0
        has_programs = row["raw"]["programCount"] > 0
        observed["existingManifestEntities"] += has_existing
        observed["newManifestEntities"] += has_new
        observed["anyManifestEntities"] += has_existing or has_new
        observed["programRawEntities"] += has_programs
        for source in row["rankingSources"]:
            by_source[source]["entities"] += 1
            by_source[source]["existingManifestEntities"] += has_existing
            by_source[source]["newManifestEntities"] += has_new
            by_source[source]["anyManifestEntities"] += has_existing or has_new
            by_source[source]["programRawEntities"] += has_programs
    matrix_categories = Counter((coverage_matrix.get("summary") or {}).get("categories") or {})
    expected = {
        "existingManifestEntities": matrix_categories["existing-program-raw"] + matrix_categories["existing-zero-candidates"],
        "newManifestEntities": matrix_categories["new-program-raw"] + matrix_categories["verified-zero-candidates"],
        "programRawEntities": matrix_categories["existing-program-raw"] + matrix_categories["new-program-raw"],
    }
    return {
        "observed": dict(observed),
        "matrixCategories": dict(matrix_categories),
        "matrixDerivedExpected": expected,
        "matchesMatrix": {key: observed[key] == value for key, value in expected.items()},
        "byRankingSource": {source: dict(counts) for source, counts in sorted(by_source.items())},
    }


def group_matrix_entities(coverage_matrix: dict) -> dict[str, list[dict]]:
    output: dict[str, list[dict]] = defaultdict(list)
    for entity in coverage_matrix.get("entities") or []:
        output[str(entity.get("category") or "unknown")].append({
            "canonicalId": entity.get("canonicalId"),
            "name": entity.get("name"),
            "country": entity.get("country"),
            "rankingSources": entity.get("rankingSources") or [],
            "officialVerificationStatus": entity.get("officialVerificationStatus"),
            "officialReasonCodes": entity.get("officialReasonCodes") or [],
        })
    return dict(output)


def blocked_groups(entity_rows: list[dict]) -> dict:
    candidate_blocked = []
    evidence_blocked = []
    for row in entity_rows:
        combined = row["raw"]["candidateStatus"]["combined"]
        if combined.get("blocked"):
            candidate_blocked.append({
                "canonicalId": row["canonicalId"], "name": row["name"], "country": row["country"],
                "blockedCandidates": combined["blocked"],
            })
        blocked_evidence = sum(
            count for key, count in row["raw"]["pageCounts"].items()
            if ":evidence:blocked" in key
        )
        if blocked_evidence:
            evidence_blocked.append({
                "canonicalId": row["canonicalId"], "name": row["name"], "country": row["country"],
                "blockedEvidencePages": blocked_evidence,
            })
    return {"candidateBlocked": candidate_blocked, "evidenceBlocked": evidence_blocked}


def load_queue_items(paths: list[Path]) -> list[dict]:
    items = []
    for path in paths:
        payload = load_json(path, [])
        values = payload.get("items") or [] if isinstance(payload, dict) else payload or []
        for item in values:
            if isinstance(item, dict):
                normalized = {**item, "queueFile": str(path.resolve())}
                if not normalized.get("kind") and normalized.get("browserAction"):
                    normalized["kind"] = "official-homepage"
                if not normalized.get("url"):
                    normalized["url"] = normalized.get("indexUrl")
                homepage_raw = ((normalized.get("provenance") or {}).get("officialHomepageRaw") or {})
                if not normalized.get("sourceManifestFile"):
                    normalized["sourceManifestFile"] = homepage_raw.get("manifestFile")
                if not normalized.get("sourceRawFile"):
                    normalized["sourceRawFile"] = homepage_raw.get("rawFile")
                items.append(normalized)
    deduped = {}
    for item in items:
        key = (item.get("universityId"), item.get("kind"), url_key(item.get("url")) or item.get("url"))
        deduped[key] = item
    return list(deduped.values())


def audit_queues(paths: list[Path]) -> dict:
    items = load_queue_items(paths)
    counts = Counter()
    by_country: dict[str, Counter] = defaultdict(Counter)
    issues: dict[str, list] = defaultdict(list)
    hash_checked = 0
    hash_matched = 0
    for item in items:
        kind = str(item.get("kind") or "unknown")
        status = str(item.get("status") or "unknown")
        country = str(item.get("country") or "Unknown")
        counts["tasks"] += 1
        counts["kind:" + kind] += 1
        counts["status:" + status] += 1
        by_country[country][kind] += 1
        manifest_path = Path(str(item["sourceManifestFile"])) if item.get("sourceManifestFile") else None
        raw_path = Path(str(item["sourceRawFile"])) if item.get("sourceRawFile") else None
        if manifest_path and manifest_path.exists():
            counts["existingSourceManifests"] += 1
            try:
                source_manifest = load_json(manifest_path)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                issues["unreadableSourceManifests"].append({"file": str(manifest_path), "error": str(exc)})
                source_manifest = None
            if raw_path and raw_path.exists() and isinstance(source_manifest, dict) and source_manifest.get("sha256"):
                hash_checked += 1
                actual = hashlib.sha256(raw_path.read_bytes()).hexdigest()
                if actual == source_manifest.get("sha256"):
                    hash_matched += 1
                else:
                    issues["sourceHashMismatches"].append({"file": str(raw_path), "expected": source_manifest.get("sha256"), "actual": actual})
        elif manifest_path:
            issues["missingSourceManifests"].append(str(manifest_path))
        else:
            counts["tasksWithoutSourceManifest"] += 1
        if raw_path:
            if raw_path.exists():
                counts["existingSourceRawFiles"] += 1
            else:
                issues["missingSourceRawFiles"].append(str(raw_path))
        else:
            counts["tasksWithoutSourceRawFile"] += 1
    return {
        "queueFiles": [str(path.resolve()) for path in paths],
        "summary": dict(sorted(counts.items())),
        "byCountry": {country: dict(counts) for country, counts in sorted(by_country.items())},
        "sourceHashCheck": {"checked": hash_checked, "matched": hash_matched, "mismatched": hash_checked - hash_matched},
        "issues": dict(issues),
        "items": items,
    }


def validate_scope(target_audit: dict, coverage_matrix: dict) -> dict:
    source_counts = Counter()
    source_unique: dict[str, set[str]] = defaultdict(set)
    rank_rows = 0
    for entity in target_audit.get("entities") or []:
        for appearance in entity.get("rankingAppearances") or []:
            source = str(appearance.get("source"))
            source_counts[source] += 1
            source_unique[source].add(str(appearance.get("universityId")))
            rank_rows += 1
    expected_sources = ("qs", "the", "arwu", "usnews")
    source_rows = {
        source: {
            "rows": source_counts[source],
            "uniqueSourceUniversityIds": len(source_unique[source]),
            "expectedRows": 500,
            "rowsMatch": source_counts[source] == 500,
        }
        for source in expected_sources
    }
    target_entities = len(target_audit.get("entities") or [])
    coverage_entities = len(coverage_matrix.get("entities") or [])
    return {
        "rankingRows": rank_rows,
        "expectedRankingRows": 2000,
        "rankingRowsMatch": rank_rows == 2000,
        "canonicalEntitiesTargetAudit": target_entities,
        "canonicalEntitiesCoverageMatrix": coverage_entities,
        "expectedCanonicalEntities": 811,
        "canonicalEntitiesMatch": target_entities == coverage_entities == 811,
        "sources": source_rows,
        "allFourSourcesMatch500": all(row["rowsMatch"] for row in source_rows.values()),
    }


def build_audit(
    target_audit: dict,
    coverage_matrix: dict,
    old_raw: Path,
    new_raw: Path,
    queue_paths: list[Path],
    hash_sample_size: int = 64,
) -> dict:
    id_to_canonical, entity_defs = target_maps(target_audit)
    old_inventory, old_manifests = inventory_corpus(old_raw, "existing", id_to_canonical, hash_sample_size)
    new_inventory, new_manifests = inventory_corpus(new_raw, "new", id_to_canonical, hash_sample_size)
    groups, candidate_status = scan_entities(entity_defs, old_manifests + new_manifests)
    evidence_summary, entity_rows, evidence_gaps = summarize_evidence(groups, entity_defs)
    raw_coverage = summarize_raw_coverage(entity_rows, coverage_matrix)
    matrix_groups = group_matrix_entities(coverage_matrix)
    blocked = blocked_groups(entity_rows)
    queue_audit = audit_queues(queue_paths)
    missing_program_groups = {
        category: rows for category, rows in matrix_groups.items()
        if category not in {"existing-program-raw", "new-program-raw"}
    }
    return {
        "schemaVersion": 4,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "readOnly": True,
            "rawFirst": True,
            "cleaningPerformed": False,
            "frontendModified": False,
            "evidenceHeadlineMode": "direct",
            "sharedEvidencePolicy": "reported separately as includingShared; unresolved school-level evidence is never counted as direct project evidence",
        },
        "inputs": {
            "targetAudit": str(DEFAULT_TARGET_AUDIT.resolve()),
            "coverageMatrix": str(DEFAULT_COVERAGE.resolve()),
            "existingRaw": str(old_raw.resolve()),
            "newRaw": str(new_raw.resolve()),
            "queues": [str(path.resolve()) for path in queue_paths],
        },
        "validation": validate_scope(target_audit, coverage_matrix),
        "coverage": {
            "rawEntities": raw_coverage,
            "candidateStatus": candidate_status,
            "applicationEvidence": evidence_summary,
        },
        "integrity": {
            "existingRaw": old_inventory,
            "newRaw": new_inventory,
            "browserRecoveryQueue": queue_audit,
        },
        "actionGroups": {
            "coverageMatrixCategories": matrix_groups,
            "missingProgramRaw": missing_program_groups,
            "blockedRaw": blocked,
            "evidenceGaps": evidence_gaps,
        },
        "entities": entity_rows,
    }


def markdown_report(audit: dict) -> str:
    validation = audit["validation"]
    raw = audit["coverage"]["rawEntities"]
    candidates = audit["coverage"]["candidateStatus"]
    evidence = audit["coverage"]["applicationEvidence"]
    matrix = raw["matrixCategories"]
    direct = evidence["modes"]["direct"]
    shared = evidence["modes"]["includingShared"]
    lines = [
        "# RankingSelect Top 500 Goal Progress Audit v4",
        "",
        "Generated: `%s`" % audit["generatedAt"],
        "",
        "## Scope Validation",
        "",
        "| Check | Observed | Expected | Pass |",
        "|---|---:|---:|:---:|",
        "| Ranking rows | %d | 2,000 | %s |" % (validation["rankingRows"], "yes" if validation["rankingRowsMatch"] else "no"),
        "| Canonical entities | %d | 811 | %s |" % (validation["canonicalEntitiesTargetAudit"], "yes" if validation["canonicalEntitiesMatch"] else "no"),
    ]
    for source, row in validation["sources"].items():
        lines.append("| %s rows | %d | 500 | %s |" % (source.upper(), row["rows"], "yes" if row["rowsMatch"] else "no"))
    lines += [
        "",
        "## Entity Raw Coverage",
        "",
        "| Category | Entities |",
        "|---|---:|",
    ]
    for category, count in sorted(matrix.items()):
        lines.append("| `%s` | %d |" % (category, count))
    observed = raw["observed"]
    lines += [
        "",
        "Observed mapped manifests cover **%d** entities; **%d** entities have at least one programme URL in the combined raw corpus." % (
            observed.get("anyManifestEntities", 0), observed.get("programRawEntities", 0)
        ),
        "",
        "## Candidate Capture Status",
        "",
        "| Corpus | Total | Captured | Error | Blocked | Missing/Pending |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for corpus in ("existing", "new", "combined"):
        row = candidates[corpus]
        other = row.get("missing", 0) + row.get("pending", 0) + row.get("unknown", 0)
        lines.append("| %s | %d | %d | %d | %d | %d |" % (
            corpus, row.get("total", 0), row.get("captured", 0), row.get("error", 0), row.get("blocked", 0), other
        ))
    lines += [
        "",
        "## Application Evidence Coverage",
        "",
        "Programme denominator: **%d** deduplicated URLs across **%d** canonical entities with programme raw." % (
            evidence["programUniverse"]["programs"], evidence["programUniverse"]["entitiesWithPrograms"]
        ),
        "",
        "Headline figures below use direct programme evidence only. `includingShared` is shown separately because unresolved university-level pages are inferred, not project-specific.",
        "",
        "| Evidence | Direct programmes | Direct rate | Entities any direct | Entities fully direct | Including shared programmes |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category in EVIDENCE_CATEGORIES + ("essentialBundle",):
        d = direct[category]
        s = shared[category]
        lines.append("| `%s` | %d | %.2f%% | %d | %d | %d |" % (
            category,
            d["programLevel"]["covered"],
            d["programLevel"]["coverageRate"] * 100,
            d["entityLevel"]["withAnyCoveredProgram"],
            d["entityLevel"]["allProgramsCovered"],
            s["programLevel"]["covered"],
        ))
    lines += [
        "",
        "`essentialBundle` means requirements + deadline + applicationWindow are all evidenced for the same programme URL.",
        "",
        "## Missing And Blocked Groups",
        "",
    ]
    for category, rows in sorted(audit["actionGroups"]["missingProgramRaw"].items()):
        lines.append("- `%s`: %d entities" % (category, len(rows)))
    blocked = audit["actionGroups"]["blockedRaw"]
    lines += [
        "- Candidate-page blocked: %d entities" % len(blocked["candidateBlocked"]),
        "- Evidence-page blocked: %d entities" % len(blocked["evidenceBlocked"]),
        "- Browser recovery queue: %d unique tasks" % audit["integrity"]["browserRecoveryQueue"]["summary"].get("tasks", 0),
        "",
        "## Integrity",
        "",
        "| Corpus | Manifests | Unreadable | Missing refs | SHA samples | SHA mismatches |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in ("existingRaw", "newRaw"):
        row = audit["integrity"][key]["summary"]
        lines.append("| %s | %d | %d | %d | %d | %d |" % (
            key,
            row.get("manifestFiles", 0),
            row.get("unreadableManifests", 0),
            row.get("missingReferencedFiles", 0),
            row.get("hashSamplesChecked", 0),
            row.get("hashSamplesMismatched", 0),
        ))
    queue_hash = audit["integrity"]["browserRecoveryQueue"]["sourceHashCheck"]
    lines += [
        "",
        "Queue source bodies with standalone SHA manifests: %d checked, %d matched, %d mismatched." % (
            queue_hash["checked"], queue_hash["matched"], queue_hash["mismatched"]
        ),
        "",
        "## Method Notes",
        "",
        "- No deadline parsing, date filtering, data cleaning, manual correction, assembly, or frontend import was performed.",
        "- Candidate status is deduplicated per canonical entity and normalized URL. Status precedence is captured > blocked > error > pending > missing.",
        "- Programme evidence is detected only from captured raw bodies. A `sourceUrl` chain that resolves to a programme URL is direct evidence.",
        "- Unresolved school-level evidence is excluded from direct headline coverage and retained only in the separate `includingShared` view.",
        "- Manifest/file existence is checked across all raw manifests. SHA-256 is checked on deterministic samples after gzip decompression, matching crawler hash semantics.",
        "",
    ]
    return "\n".join(lines)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-audit", type=Path, default=DEFAULT_TARGET_AUDIT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--old-raw", type=Path, default=DEFAULT_OLD_RAW)
    parser.add_argument("--new-raw", type=Path, default=DEFAULT_NEW_RAW)
    parser.add_argument("--queue", type=Path, action="append")
    parser.add_argument("--hash-sample-size", type=int, default=64)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    queue_paths = args.queue if args.queue is not None else [path for path in DEFAULT_QUEUES if path.exists()]
    audit = build_audit(
        load_json(args.target_audit),
        load_json(args.coverage),
        args.old_raw,
        args.new_raw,
        queue_paths,
        args.hash_sample_size,
    )
    audit["inputs"]["targetAudit"] = str(args.target_audit.resolve())
    audit["inputs"]["coverageMatrix"] = str(args.coverage.resolve())
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown_report(audit), encoding="utf-8")
    print(json.dumps({
        "validation": audit["validation"],
        "rawEntities": audit["coverage"]["rawEntities"],
        "candidateStatus": audit["coverage"]["candidateStatus"],
        "programUniverse": audit["coverage"]["applicationEvidence"]["programUniverse"],
        "outputs": {"json": str(args.output_json.resolve()), "markdown": str(args.output_md.resolve())},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
