"""Build a deterministic queue for missing application evidence.

The queue is derived exclusively from the raw evidence audit, the conservative
Top 500 identity audit, and existing raw manifests.  It performs no network
requests and never constructs or guesses a URL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT = ROOT / "scraper" / "playwright" / "_raw_application_evidence_audit.json"
TOP500_AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit.json"
RAW_ROOT = ROOT / "scraper" / "playwright" / "_programs_full_raw"
OUTPUT = ROOT / "scraper" / "playwright" / "application_gap_queue.json"

CATEGORIES = ("deadline", "applicationWindow", "requirements", "documents", "language")
PROGRAM_CATEGORIES = CATEGORIES[1:]
DEFAULT_SHARD_COUNT = 16
DEFAULT_PROGRAM_SAMPLE_LIMIT = 50


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def deterministic_shard(canonical_id: str, program_url: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    key = f"{canonical_id}\0{program_url}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % shard_count


def read_manifests(raw_root: Path) -> list[dict]:
    manifests = []
    if not raw_root.exists():
        return manifests
    for path in sorted(raw_root.glob("*/manifest.json"), key=lambda item: item.as_posix()):
        try:
            manifest = load_json(path)
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(manifest, dict):
            manifests.append(manifest)
    return manifests


def top500_ids(audit: dict | None) -> set[str]:
    result = set()
    for entity in (audit or {}).get("entities") or []:
        result.add(entity.get("canonicalId"))
        result.update(entity.get("sourceUniversityIds") or [])
        result.update(entity.get("existingRawTargetIds") or [])
    result.discard(None)
    return result


def manifest_index(manifests: Iterable[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for manifest in manifests:
        ids = {manifest.get("universityId")}
        ids.update(manifest.get("sourceUniversityIds") or [])
        for university_id in sorted(item for item in ids if item):
            index.setdefault(university_id, []).append(manifest)
    return index


def manifests_for_university(university: dict, index: dict[str, list[dict]]) -> list[dict]:
    ids = {university.get("canonicalId")}
    ids.update(university.get("aliasIds") or [])
    found = []
    seen = set()
    for university_id in sorted(item for item in ids if item):
        for manifest in index.get(university_id, []):
            marker = id(manifest)
            if marker not in seen:
                seen.add(marker)
                found.append(manifest)
    return sorted(
        found,
        key=lambda manifest: (
            manifest.get("universityId") or "",
            manifest.get("indexUrl") or "",
            tuple(sorted(manifest.get("officialDomains") or [])),
        ),
    )


def official_domains(manifests: Iterable[dict]) -> list[str]:
    return sorted(
        {
            domain.strip().lower()
            for manifest in manifests
            for domain in (manifest.get("officialDomains") or [])
            if isinstance(domain, str) and domain.strip()
        }
    )


def source_url_for_program(program_url: str, manifests: Iterable[dict]) -> str | None:
    """Return only a source URL explicitly recorded for this candidate."""
    for manifest in manifests:
        candidates = ((manifest.get("discovery") or {}).get("programCandidates") or {})
        candidate = candidates.get(program_url)
        if isinstance(candidate, dict) and candidate.get("sourceUrl"):
            return candidate["sourceUrl"]
    return None


def university_source_url(manifests: Iterable[dict]) -> str | None:
    """Use a recorded catalogue URL; do not derive one from a domain."""
    urls = sorted(
        {
            manifest.get("indexUrl")
            for manifest in manifests
            if isinstance(manifest.get("indexUrl"), str) and manifest["indexUrl"]
        }
    )
    return urls[0] if urls else None


def evidence_links(program: dict) -> dict[str, list[str]]:
    links = {}
    for category in CATEGORIES:
        evidence = program.get("deadline") if category == "deadline" else (program.get("coverage") or {}).get(category)
        links[category] = sorted(
            {
                source.get("url")
                for source in (evidence or {}).get("sources") or []
                if isinstance(source, dict) and source.get("url")
            }
        )
    return links


def missing_categories(program: dict) -> list[str]:
    missing = []
    for category in CATEGORIES:
        evidence = program.get("deadline") if category == "deadline" else (program.get("coverage") or {}).get(category)
        if not (evidence or {}).get("covered", False):
            missing.append(category)
    return missing


def university_priority(university: dict, is_top500: bool) -> tuple:
    program_count = int(university.get("programCount") or len(university.get("programs") or []))
    rates = [
        float(((university.get("coverage") or {}).get(category) or {}).get("coverageRate") or 0)
        for category in PROGRAM_CATEGORIES
    ]
    rates.append(float(((university.get("deadlineGap") or {}).get("coverageRate") or 0)))
    average_coverage = sum(rates) / len(rates)
    return (
        0 if is_top500 else 1,
        -program_count,
        average_coverage,
        (university.get("universityName") or "").casefold(),
        university.get("canonicalId") or "",
    )


def build_queue(
    evidence_audit: dict,
    ranking_audit: dict | None,
    manifests: Iterable[dict],
    shard_count: int = DEFAULT_SHARD_COUNT,
    sample_limit: int = DEFAULT_PROGRAM_SAMPLE_LIMIT,
) -> dict:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if sample_limit < 0:
        raise ValueError("sample_limit must not be negative")

    ranked_ids = top500_ids(ranking_audit)
    by_id = manifest_index(manifests)
    universities = []
    for university in evidence_audit.get("universities") or []:
        canonical_id = university.get("canonicalId")
        aliases = set(university.get("aliasIds") or [])
        is_top500 = canonical_id in ranked_ids or bool(aliases & ranked_ids)
        universities.append((university_priority(university, is_top500), university, is_top500))
    universities.sort(key=lambda row: row[0])

    deadline_tasks = []
    program_tasks = []
    university_summaries = []
    complete_gap_totals = Counter({category: 0 for category in CATEGORIES})

    for _, university, is_top500 in universities:
        canonical_id = university["canonicalId"]
        known_manifests = manifests_for_university(university, by_id)
        domains = official_domains(known_manifests)
        programs_with_gaps = []
        gap_counts = Counter({category: 0 for category in CATEGORIES})

        for program in university.get("programs") or []:
            missing = missing_categories(program)
            for category in missing:
                gap_counts[category] += 1
                complete_gap_totals[category] += 1
            program_missing = [category for category in missing if category in PROGRAM_CATEGORIES]
            if program_missing:
                programs_with_gaps.append((program, missing, program_missing))

        if gap_counts["deadline"]:
            deadline_tasks.append(
                {
                    "taskType": "universityDeadline",
                    "canonicalId": canonical_id,
                    "universityName": university.get("universityName"),
                    "country": university.get("country"),
                    "top500": is_top500,
                    "programUrl": None,
                    "sourceUrl": university_source_url(known_manifests),
                    "officialDomains": domains,
                    "existingEvidenceLinks": {"deadline": []},
                    "missingCategories": ["deadline"],
                    "affectedProgramCount": gap_counts["deadline"],
                    "status": "pending",
                }
            )

        programs_with_gaps.sort(
            key=lambda row: (-len(row[2]), -len(row[1]), row[0].get("url") or "")
        )
        sampled = programs_with_gaps[:sample_limit]
        for program, missing, program_missing in sampled:
            program_url = program.get("url")
            program_tasks.append(
                {
                    "taskType": "programEvidence",
                    "canonicalId": canonical_id,
                    "universityName": university.get("universityName"),
                    "country": university.get("country"),
                    "top500": is_top500,
                    "programUrl": program_url,
                    "sourceUrl": source_url_for_program(program_url, known_manifests) if program_url else None,
                    "officialDomains": domains,
                    "existingEvidenceLinks": evidence_links(program),
                    "missingCategories": program_missing,
                    "deadlineMissing": "deadline" in missing,
                    "status": "pending",
                    "shard": deterministic_shard(canonical_id, program_url or "", shard_count),
                }
            )

        university_summaries.append(
            {
                "canonicalId": canonical_id,
                "universityName": university.get("universityName"),
                "top500": is_top500,
                "programCount": int(university.get("programCount") or len(university.get("programs") or [])),
                "completeGapCounts": {category: gap_counts[category] for category in CATEGORIES},
                "eligibleProgramTaskCount": len(programs_with_gaps),
                "sampledProgramTaskCount": len(sampled),
                "omittedProgramTaskCount": max(0, len(programs_with_gaps) - len(sampled)),
            }
        )

    tasks = deadline_tasks + program_tasks
    for position, task in enumerate(tasks):
        task["queuePosition"] = position

    return {
        "schemaVersion": 1,
        "sourceAudit": "scraper/playwright/_raw_application_evidence_audit.json",
        "sourceAuditGeneratedAt": evidence_audit.get("generatedAt"),
        "policy": {
            "networkAccessUsed": False,
            "urlsAreCopiedFromEvidenceOrManifestOnly": True,
            "programSampleLimitPerUniversity": sample_limit,
            "universityDeadlineTaskLimitPerUniversity": 1,
        },
        "priority": [
            "universityDeadline:first",
            "fourRankingTop500:first",
            "programCount:desc",
            "meanEvidenceCoverage:asc",
            "missingCategoryCount:desc",
        ],
        "shardStrategy": {
            "scope": "programEvidence",
            "algorithm": "sha256-canonical-id-null-program-url-first-8-bytes-modulo",
            "count": shard_count,
        },
        "summary": {
            "universityCount": len(universities),
            "deadlineTaskCount": len(deadline_tasks),
            "programTaskCount": len(program_tasks),
            "taskCount": len(tasks),
            "completeGapCounts": {category: complete_gap_totals[category] for category in CATEGORIES},
            "omittedProgramTaskCount": sum(item["omittedProgramTaskCount"] for item in university_summaries),
        },
        "universities": university_summaries,
        "tasks": tasks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--top500-audit", type=Path, default=TOP500_AUDIT)
    parser.add_argument("--raw-root", type=Path, default=RAW_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARD_COUNT)
    parser.add_argument("--sample-limit", type=int, default=DEFAULT_PROGRAM_SAMPLE_LIMIT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queue = build_queue(
        load_json(args.audit, {}),
        load_json(args.top500_audit, {}),
        read_manifests(args.raw_root),
        shard_count=args.shards,
        sample_limit=args.sample_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[application-gap-queue] wrote {queue['summary']['taskCount']} tasks "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
