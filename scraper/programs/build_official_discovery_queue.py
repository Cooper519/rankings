"""Build a conservative official-program discovery queue for Top 500 gaps.

This module performs no network requests and makes no claim that a search
result is official. Official domains and catalogue URLs remain empty until a
later, explicit verification step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
INPUT = ROOT / "scraper" / "programs" / "top500_targets_audit.json"
OUTPUT = ROOT / "scraper" / "playwright" / "top500_official_discovery_queue.json"
PROPOSALS = ROOT / "scraper" / "programs" / "top500_alias_proposals.json"

SOURCE_ORDER = {"qs": 0, "the": 1, "arwu": 2, "usnews": 3}
DEFAULT_SHARD_COUNT = 16
US_COUNTRIES = {"USA", "United States", "United States of America"}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalized_sources(entity: dict) -> list[str]:
    sources = set(entity.get("rankingSources") or [])
    return sorted(sources, key=lambda source: (SOURCE_ORDER.get(source, 99), source))


def build_queries(name: str, country: str) -> list[dict[str, object]]:
    """Return discovery hints only; these are never treated as verification."""
    queries: list[dict[str, object]] = [
        {
            "query": f'"{name}" {country} official graduate programs',
            "purpose": "official-graduate-catalog",
            "domainHint": None,
            "domainHintIsVerification": False,
        },
        {
            "query": f'"{name}" {country} official master programs',
            "purpose": "official-master-catalog",
            "domainHint": None,
            "domainHintIsVerification": False,
        },
    ]
    if country in US_COUNTRIES:
        queries.append(
            {
                "query": f'site:.edu "{name}" official master programs',
                "purpose": "us-edu-discovery-hint",
                "domainHint": ".edu",
                "domainHintIsVerification": False,
            }
        )
    return queries


def deterministic_shard(canonical_id: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    digest = hashlib.sha256(canonical_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % shard_count


def entity_sort_key(entity: dict) -> tuple:
    sources = normalized_sources(entity)
    appearances = entity.get("rankingAppearances") or []
    best_rank = min(
        (row["rank"] for row in appearances if isinstance(row.get("rank"), int)),
        default=10**9,
    )
    return (
        (entity.get("country") or "").casefold(),
        -len(sources),
        best_rank,
        (entity.get("name") or "").casefold(),
        entity.get("canonicalId") or "",
    )


def build_queue(
    audit: dict,
    shard_count: int = DEFAULT_SHARD_COUNT,
    source_audit: str | Path | None = None,
    proposals: dict | None = None,
    source_proposals: str | Path | None = None,
) -> dict:
    entities = audit.get("entities") or []
    full_by_id = {entity.get("canonicalId"): entity for entity in entities}
    gaps = audit.get("gaps")
    if gaps is None:
        gaps = [
            entity
            for entity in entities
            if not entity.get("coveredByExistingRawTarget", False)
        ]
    else:
        # Audit schema v1 emits compact gaps with ``universityId``. Hydrate
        # them from entities so rank evidence remains available in the queue.
        gaps = [
            full_by_id.get(gap.get("canonicalId") or gap.get("universityId"), gap)
            for gap in gaps
        ]

    proposal_by_entity_id = {}
    for proposal_index, proposal in enumerate(
        (proposals or {}).get("highConfidenceDuplicateGroups") or []
    ):
        group_id = f"high-{proposal_index:03d}"
        for entity_id in proposal.get("entityIds") or []:
            if entity_id in proposal_by_entity_id:
                raise RuntimeError(f"overlapping alias proposal for {entity_id}")
            proposal_by_entity_id[entity_id] = {
                "proposalGroupId": group_id,
                "proposalStatus": proposal.get("proposalStatus", "review-required"),
                "confidence": proposal.get("confidence", "high"),
                "relation": proposal.get("relation", "sameInstitution"),
                "recommendedCanonicalId": proposal.get("recommendedCanonicalId"),
                "memberEntityIds": sorted(set(proposal.get("entityIds") or [])),
                "binding": False,
            }

    ordered = sorted(gaps, key=entity_sort_key)
    items = []
    for position, entity in enumerate(ordered):
        canonical_id = entity.get("canonicalId") or entity["universityId"]
        country = entity.get("country") or ""
        sources = normalized_sources(entity)
        items.append(
            {
                "queuePosition": position,
                "canonicalId": canonical_id,
                "name": entity["name"],
                "country": country,
                "sourceUniversityIds": sorted(set(entity.get("sourceUniversityIds") or [])),
                "rankingSources": sources,
                "rankingSourceCount": len(sources),
                "rankingAppearances": entity.get("rankingAppearances") or [],
                "queries": build_queries(entity["name"], country),
                "officialDomains": [],
                "indexUrl": None,
                "verificationStatus": "pending",
                "shard": deterministic_shard(canonical_id, shard_count),
                "aliasProposal": proposal_by_entity_id.get(canonical_id),
            }
        )

    return {
        "schemaVersion": 1,
        "sourceAudit": str(source_audit or "scraper/programs/top500_targets_audit.json"),
        "sourceAuditGeneratedAt": audit.get("generatedAt"),
        "sourceAliasProposals": str(source_proposals) if source_proposals else None,
        "sourceAliasProposalsGeneratedAt": (proposals or {}).get("generatedAt"),
        "policy": {
            "networkAccessUsed": False,
            "searchResultsAreOfficialEvidence": False,
            "officialDomainRequiresManualVerification": True,
            "usEduQueryIsDiscoveryHintOnly": True,
            "aliasProposalsAreBinding": False,
            "queueEntitiesMergedByProposal": False,
        },
        "sort": ["country:asc", "rankingSourceCount:desc", "bestRank:asc", "name:asc"],
        "shardStrategy": {
            "algorithm": "sha256-canonical-id-first-8-bytes-modulo",
            "count": shard_count,
        },
        "total": len(items),
        "items": items,
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit",
        "--input",
        dest="audit",
        type=Path,
        default=INPUT,
        help="Top 500 target audit JSON (the --input spelling is retained as an alias)",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument(
        "--proposals",
        type=Path,
        default=None,
        help="Optional non-binding alias proposal audit used only for queue annotations",
    )
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARD_COUNT)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    proposals = load_json(args.proposals) if args.proposals else None
    queue = build_queue(
        load_json(args.audit),
        args.shards,
        source_audit=args.audit.resolve(),
        proposals=proposals,
        source_proposals=args.proposals.resolve() if args.proposals else None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"[official-discovery-queue] wrote {queue['total']} items to {args.output}")


if __name__ == "__main__":
    main()
