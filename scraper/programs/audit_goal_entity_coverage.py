"""Build an entity-level raw-first coverage matrix for the four Top 500 lists."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scraper.programs.scrape_programs_static import safe_id


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verification_map(*payloads: Any) -> dict[str, dict]:
    output = {}
    for payload in payloads:
        for item in (payload.get("items") or []):
            identifier = item.get("canonicalId") or item.get("universityId")
            if identifier:
                output[str(identifier)] = item
    return output


def manifest_summary(root: Path, identifier: str) -> dict | None:
    path = root / safe_id(identifier) / "manifest.json"
    if not path.exists():
        return None
    manifest = load(path)
    page_counts = Counter()
    for page in (manifest.get("pages") or {}).values():
        page_counts[(page.get("kind") or "other", page.get("status") or "unknown")] += 1
    candidates = len((manifest.get("discovery") or {}).get("programCandidates") or {})
    return {
        "manifestFile": str(path.resolve()),
        "manifestStatus": manifest.get("status"),
        "programCandidates": candidates,
        "programCaptured": page_counts[("program", "captured")],
        "programError": page_counts[("program", "error")],
        "programBlocked": page_counts[("program", "blocked")],
        "evidenceCaptured": page_counts[("evidence", "captured")],
        "evidenceError": page_counts[("evidence", "error")],
        "evidenceBlocked": page_counts[("evidence", "blocked")],
    }


def _preferred_summary(
    roots_and_ids: Iterable[tuple[Path, str]],
) -> tuple[dict | None, str | None, list[dict]]:
    found = []
    for root, identifier in roots_and_ids:
        summary = manifest_summary(root, identifier)
        if summary:
            found.append(dict(summary, rawRoot=str(root.resolve()), targetId=identifier))
    preferred = next(
        (summary for summary in found if summary.get("programCandidates", 0) > 0),
        found[0] if found else None,
    )
    return (
        preferred,
        preferred.get("targetId") if preferred else None,
        found,
    )


def build(
    audit: dict,
    old_root: Path,
    new_root: Path,
    verifications: dict[str, dict],
    supplemental_roots: Iterable[Path] = (),
) -> dict:
    rows = []
    categories = Counter()
    source_categories: dict[str, Counter] = {}
    for entity in audit.get("entities") or []:
        identifier = entity["canonicalId"]
        existing, existing_id, existing_sources = _preferred_summary(
            (old_root, target_id)
            for target_id in (entity.get("existingRawTargetIds") or [])
        )
        new, _new_id, new_sources = _preferred_summary(
            (root, identifier)
            for root in [new_root] + list(supplemental_roots)
        )
        verification = verifications.get(identifier) or {}
        official_status = verification.get("verificationStatus")
        if existing and existing.get("programCandidates", 0) > 0:
            category = "existing-program-raw"
        elif new and new.get("programCandidates", 0) > 0:
            category = "new-program-raw"
        elif new:
            category = "verified-zero-candidates"
        elif existing:
            category = "existing-zero-candidates"
        elif official_status == "verified":
            category = "verified-target-manifest-missing"
        elif official_status == "blocked":
            category = "official-blocked"
        elif official_status == "rejected":
            category = "official-rejected"
        elif official_status == "review":
            category = "official-review"
        elif entity.get("coveredByExistingRawTarget"):
            category = "existing-target-manifest-missing"
        else:
            category = "official-discovery-missing"
        categories[category] += 1
        for source in entity.get("rankingSources") or []:
            source_categories.setdefault(source, Counter())[category] += 1
        rows.append({
            "canonicalId": identifier,
            "name": entity.get("name"),
            "country": entity.get("country"),
            "rankingSources": entity.get("rankingSources") or [],
            "sourceUniversityIds": entity.get("sourceUniversityIds") or [],
            "category": category,
            "existingRawTargetId": existing_id,
            "existingRaw": existing,
            "existingRawSources": existing_sources,
            "newRaw": new,
            "newRawSources": new_sources,
            "officialVerificationStatus": official_status,
            "officialReasonCodes": (verification.get("verification") or {}).get("reasonCodes") or [],
        })
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "entities": len(rows),
            "categories": dict(categories),
            "byRankingSource": {source: dict(counts) for source, counts in sorted(source_categories.items())},
        },
        "entities": rows,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--old-raw", type=Path, required=True)
    parser.add_argument("--new-raw", type=Path, required=True)
    parser.add_argument("--supplemental-raw", type=Path, action="append", default=[])
    parser.add_argument("--verification", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build(
        load(args.audit), args.old_raw, args.new_raw,
        verification_map(*(load(path) for path in args.verification)),
        args.supplemental_raw,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
