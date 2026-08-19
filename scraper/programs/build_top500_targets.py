"""Build a deterministic four-ranking Top 500 crawl-target audit.

This is a read-only planning step for the existing raw crawl corpus.  It does
not mutate the frozen raw target list, manifests, cleaned data, or frontend
data.  Entities are merged only when they share a normalized country and one
of these conservative keys:

* the existing ``university_aliases.json`` canonical id;
* a reviewed manual group from ``build_aliases.py``; or
* an exact normalized university name; or
* a reviewed ``sameInstitution``/``formerName`` relationship override.

Reviewed ``successorOf``, ``systemCampus``, and ``distinctInstitution``
relationships are non-merging constraints.  They prevent legacy automatic
rules from collapsing institutions at different temporal or campus grains.

No official URL is inferred.  Draft targets inherit a known ``indexUrl``
from a matched existing raw target; otherwise the field is null.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

try:
    from .build_aliases import MANUAL_GROUPS, country_key, normalize_name
except ImportError:  # Support direct script execution from this directory.
    from build_aliases import MANUAL_GROUPS, country_key, normalize_name


ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "frontend" / "public" / "data"
RANKINGS_DIR = DATA / "rankings"
ALIASES = DATA / "university_aliases.json"
RAW_TARGETS = ROOT / "scraper" / "playwright" / "raw_crawl_targets.json"
OUTPUT = ROOT / "scraper" / "programs" / "top500_targets_audit.json"
RELATIONSHIP_OVERRIDES = (
    ROOT / "scraper" / "programs" / "top500_institution_relationships.json"
)

SOURCES = ("qs", "the", "arwu", "usnews")
SOURCE_ORDER = {source: index for index, source in enumerate(SOURCES)}
EXPECTED_ROWS_PER_SOURCE = 500
TOP500_COUNTRY_ALIASES = {
    "China-Hong Kong": "Hong Kong",
    "China-Macau": "Macau",
    "China-Taiwan": "Taiwan",
    "Macao": "Macau",
    "Czech Republic": "Czechia",
    "Russian Federation": "Russia",
    "Türkiye": "Turkey",
}

RELATION_TYPES = {
    "sameInstitution",
    "formerName",
    "successorOf",
    "systemCampus",
    "distinctInstitution",
}
MERGING_RELATION_TYPES = {"sameInstitution", "formerName"}
NON_MERGING_RELATION_TYPES = RELATION_TYPES - MERGING_RELATION_TYPES


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_relationship_overrides(path: Path | None) -> dict:
    """Load and validate reviewed entity relationships.

    Only ``sameInstitution`` and ``formerName`` collapse ranking rows.  The
    other relationship types are negative constraints: they remain visible
    in the audit and prevent older alias/name rules from collapsing a pair.
    """
    if path is None:
        return {"schemaVersion": 1, "relationships": [], "_source": None}
    if not path.exists():
        raise RuntimeError(f"institution relationship override file not found: {path}")
    payload = load_json(path, {})
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise RuntimeError("institution relationship overrides require schemaVersion 1")
    relationships = payload.get("relationships")
    if not isinstance(relationships, list):
        raise RuntimeError("institution relationship overrides must contain relationships array")
    relationships = list(relationships)

    proposal_imports = payload.get("reviewedProposalImports", [])
    if not isinstance(proposal_imports, list):
        raise RuntimeError("reviewedProposalImports must be an array")
    imported_sources = []
    for proposal_import in proposal_imports:
        if not isinstance(proposal_import, dict):
            raise RuntimeError("each reviewed proposal import must be an object")
        import_id = proposal_import.get("id")
        relative_path = proposal_import.get("path")
        expected_sha256 = proposal_import.get("sha256")
        field = proposal_import.get("field")
        approved_ids = proposal_import.get("approvedCanonicalIds")
        if (
            not isinstance(import_id, str)
            or not import_id
            or not isinstance(relative_path, str)
            or not relative_path
            or not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or not isinstance(field, str)
            or not field
            or not isinstance(approved_ids, list)
            or any(not isinstance(item, str) or not item for item in approved_ids)
            or len(set(approved_ids)) != len(approved_ids)
        ):
            raise RuntimeError(f"invalid reviewed proposal import: {import_id!r}")
        proposal_path = (path.parent / relative_path).resolve()
        if not proposal_path.exists():
            raise RuntimeError(f"{import_id} proposal file not found: {proposal_path}")
        actual_sha256 = file_sha256(proposal_path)
        if actual_sha256.lower() != expected_sha256.lower():
            raise RuntimeError(
                f"{import_id} proposal SHA-256 mismatch: "
                f"expected {expected_sha256.lower()}, found {actual_sha256}"
            )
        proposal_payload = load_json(proposal_path, {})
        candidates = proposal_payload.get(field) if isinstance(proposal_payload, dict) else None
        if not isinstance(candidates, list):
            raise RuntimeError(f"{import_id} proposal field is not an array: {field}")
        candidates_by_id = {
            item.get("recommendedCanonicalId"): item
            for item in candidates
            if isinstance(item, dict) and item.get("recommendedCanonicalId")
        }
        missing = sorted(set(approved_ids) - set(candidates_by_id))
        if missing:
            raise RuntimeError(
                f"{import_id} approved canonical ids missing from proposal: {', '.join(missing)}"
            )
        for canonical_id in approved_ids:
            proposal = candidates_by_id[canonical_id]
            if (
                proposal.get("proposalStatus") != "review-required"
                or proposal.get("confidence") != "high"
                or proposal.get("relation") != "sameInstitution"
            ):
                raise RuntimeError(
                    f"{import_id} proposal {canonical_id} no longer has the reviewed "
                    "high-confidence sameInstitution shape"
                )
            relationships.append(
                {
                    "id": f"{import_id}:{canonical_id}",
                    "type": "sameInstitution",
                    "memberIds": proposal["sourceIds"],
                    "canonicalId": canonical_id,
                    "country": proposal["country"],
                    "rationale": proposal["reason"],
                    "evidence": [
                        f"{relative_path}#{field}:{canonical_id}",
                        f"sha256:{actual_sha256}",
                    ],
                }
            )
        imported_sources.append(
            {
                "id": import_id,
                "path": str(proposal_path),
                "sha256": actual_sha256,
                "field": field,
                "approvedCanonicalIdCount": len(approved_ids),
            }
        )

    seen_ids: set[str] = set()
    for index, relationship in enumerate(relationships):
        label = f"institution relationship #{index + 1}"
        if not isinstance(relationship, dict):
            raise RuntimeError(f"{label} must be an object")
        relationship_id = relationship.get("id")
        if not isinstance(relationship_id, str) or not relationship_id.strip():
            raise RuntimeError(f"{label} requires a non-empty id")
        if relationship_id in seen_ids:
            raise RuntimeError(f"duplicate institution relationship id: {relationship_id}")
        seen_ids.add(relationship_id)
        relation_type = relationship.get("type")
        if relation_type not in RELATION_TYPES:
            raise RuntimeError(
                f"{relationship_id} has invalid type {relation_type!r}; "
                f"expected one of {sorted(RELATION_TYPES)}"
            )
        member_ids = relationship.get("memberIds")
        if (
            not isinstance(member_ids, list)
            or len(member_ids) < 2
            or any(not isinstance(uid, str) or not uid for uid in member_ids)
            or len(set(member_ids)) != len(member_ids)
        ):
            raise RuntimeError(f"{relationship_id} requires at least two unique memberIds")
        if not isinstance(relationship.get("country"), str) or not relationship["country"]:
            raise RuntimeError(f"{relationship_id} requires country")
        if not isinstance(relationship.get("rationale"), str) or not relationship["rationale"]:
            raise RuntimeError(f"{relationship_id} requires rationale")
        canonical_id = relationship.get("canonicalId")
        if relation_type in MERGING_RELATION_TYPES:
            if not isinstance(canonical_id, str) or not canonical_id:
                raise RuntimeError(
                    f"{relationship_id} merging relationship requires canonicalId"
                )
        elif canonical_id is not None:
            raise RuntimeError(
                f"{relationship_id} non-merging relationship cannot declare canonicalId"
            )
        if relation_type in {"formerName", "successorOf"}:
            if (
                len(member_ids) != 2
                or relationship.get("fromId") != member_ids[0]
                or relationship.get("toId") != member_ids[1]
            ):
                raise RuntimeError(
                    f"{relationship_id} directed relationship requires memberIds=[fromId,toId]"
                )

    result = dict(payload)
    result["relationships"] = relationships
    result["_source"] = {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "reviewedProposalSources": imported_sources,
    }
    return result


def resolve_alias(uid: str, aliases: dict[str, str]) -> str:
    """Flatten an alias chain while safely handling malformed cycles."""
    current = uid
    seen = set()
    while current not in seen and aliases.get(current, current) != current:
        seen.add(current)
        current = aliases[current]
    return current


def normalized_country(value: str) -> str:
    base = country_key(value)
    return TOP500_COUNTRY_ALIASES.get(base, base)


class UnionFind:
    def __init__(
        self,
        identities: list[str],
        prohibited_pairs: set[frozenset[str]] | None = None,
    ):
        size = len(identities)
        self.parent = list(range(size))
        self.members = [{identities[index]} for index in range(size)]
        self.prohibited_pairs = prohibited_pairs or set()

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> bool:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return True
        if any(
            frozenset((left_id, right_id)) in self.prohibited_pairs
            for left_id in self.members[left_root]
            for right_id in self.members[right_root]
            if left_id != right_id
        ):
            return False
        keep, merge = min(left_root, right_root), max(left_root, right_root)
        self.parent[merge] = keep
        self.members[keep].update(self.members[merge])
        self.members[merge].clear()
        return True


def union_same_key(rows: list[dict], union: UnionFind, key_fn) -> None:
    first_by_key = {}
    for index, row in enumerate(rows):
        key = key_fn(row)
        if key is None:
            continue
        previous = first_by_key.setdefault(key, index)
        union.union(previous, index)


def relationship_maps(relationships: list[dict]) -> set[frozenset[str]]:
    merge_pairs: set[frozenset[str]] = set()
    prohibited_pairs: set[frozenset[str]] = set()
    for relationship in relationships:
        member_ids = relationship["memberIds"]
        pairs = {
            frozenset((left, right))
            for left_index, left in enumerate(member_ids)
            for right in member_ids[left_index + 1 :]
        }
        if relationship["type"] in MERGING_RELATION_TYPES:
            merge_pairs.update(pairs)
        else:
            prohibited_pairs.update(pairs)
    conflicts = merge_pairs & prohibited_pairs
    if conflicts:
        pair = sorted(next(iter(conflicts)))
        raise RuntimeError(
            "institution relationship overrides both merge and protect pair: "
            + " <> ".join(pair)
        )
    return prohibited_pairs


def manual_group_maps() -> tuple[dict[str, int], dict[int, str]]:
    member_to_group = {}
    canonical_by_group = {}
    for group_index, group in enumerate(MANUAL_GROUPS):
        canonical_by_group[group_index] = group[0]
        for uid in group:
            member_to_group[uid] = group_index
    return member_to_group, canonical_by_group


def choose_canonical_id(
    component: list[dict],
    aliases: dict[str, str],
    manual_canonical_by_group: dict[int, str],
    override_canonical_by_member: dict[str, set[str]],
    protected_member_ids: set[str],
) -> str:
    ids = [row["universityId"] for row in component]
    override_candidates = {
        candidate
        for uid in ids
        for candidate in override_canonical_by_member.get(uid, set())
    }
    if len(override_candidates) == 1:
        return next(iter(override_candidates))
    if len(override_candidates) > 1:
        raise RuntimeError(
            "merged institution component has conflicting override canonicalIds: "
            + ", ".join(sorted(override_candidates))
        )
    # A protected member must retain its own identity unless a reviewed
    # positive override above explicitly selects a shared canonical id.
    if not protected_member_ids.intersection(ids):
        roots = [resolve_alias(uid, aliases) for uid in ids]
        root_counts = Counter(roots)
        if len(root_counts) == 1:
            return next(iter(root_counts))

        manual_candidates = {
            manual_canonical_by_group[row["manualGroup"]]
            for row in component
            if row["manualGroup"] is not None
        }
        if len(manual_candidates) == 1:
            return next(iter(manual_candidates))

    id_counts = Counter(ids)
    first_appearance = {}
    for row in component:
        uid = row["universityId"]
        key = (SOURCE_ORDER[row["source"]], row["rank"], uid)
        first_appearance[uid] = min(first_appearance.get(uid, key), key)
    return min(ids, key=lambda uid: (-id_counts[uid], first_appearance[uid], uid))


def representative_row(component: list[dict], canonical_id: str) -> dict:
    canonical_rows = [row for row in component if row["universityId"] == canonical_id]
    pool = canonical_rows or component
    return min(
        pool,
        key=lambda row: (
            SOURCE_ORDER[row["source"]], row["rank"], row["universityId"], row["name"]
        ),
    )


def entity_ids(entity: dict, aliases: dict[str, str]) -> set[str]:
    ids = set(entity["sourceUniversityIds"])
    ids.add(entity["canonicalId"])
    ids.update(resolve_alias(uid, aliases) for uid in tuple(ids))
    return ids


def target_ids(target: dict, aliases: dict[str, str]) -> set[str]:
    ids = {target.get("universityId")}
    ids.update(target.get("sourceUniversityIds") or [])
    ids.discard(None)
    ids.update(resolve_alias(uid, aliases) for uid in tuple(ids))
    return ids


def build_entities(
    rows: list[dict],
    aliases: dict[str, str],
    relationship_overrides: dict | None = None,
) -> list[dict]:
    relationships = (relationship_overrides or {}).get("relationships", [])
    prohibited_pairs = relationship_maps(relationships)
    protected_member_ids = {
        uid for pair in prohibited_pairs for uid in pair
    }
    member_to_group, manual_canonical_by_group = manual_group_maps()
    prepared = []
    for row in rows:
        item = dict(row)
        item["countryKey"] = normalized_country(item.get("country", ""))
        item["normalizedName"] = normalize_name(item.get("name", ""))
        item["aliasRoot"] = resolve_alias(item["universityId"], aliases)
        item["manualGroup"] = member_to_group.get(item["universityId"])
        prepared.append(item)

    countries_by_id: dict[str, set[str]] = defaultdict(set)
    row_indices_by_id: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(prepared):
        countries_by_id[row["universityId"]].add(row["countryKey"])
        row_indices_by_id[row["universityId"]].append(index)
    for relationship in relationships:
        expected_country = normalized_country(relationship["country"])
        for uid in relationship["memberIds"]:
            found_countries = countries_by_id.get(uid, set())
            if found_countries and found_countries != {expected_country}:
                raise RuntimeError(
                    f"{relationship['id']} country mismatch for {uid}: "
                    f"expected {expected_country}, found {sorted(found_countries)}"
                )

    union = UnionFind(
        [row["universityId"] for row in prepared],
        prohibited_pairs=prohibited_pairs,
    )
    # Country is part of every key: no alias or name may merge across borders.
    union_same_key(prepared, union, lambda row: (row["countryKey"], row["aliasRoot"]))
    union_same_key(
        prepared,
        union,
        lambda row: (
            (row["countryKey"], row["manualGroup"])
            if row["manualGroup"] is not None
            else None
        ),
    )
    union_same_key(
        prepared,
        union,
        lambda row: (
            (row["countryKey"], row["normalizedName"])
            if row["normalizedName"]
            else None
        ),
    )
    # Reviewed positive relationships are applied last.  Protected pairs are
    # enforced by UnionFind for both these and all legacy automatic rules.
    for relationship in relationships:
        if relationship["type"] not in MERGING_RELATION_TYPES:
            continue
        present_member_ids = [
            uid for uid in relationship["memberIds"] if row_indices_by_id.get(uid)
        ]
        if len(present_member_ids) < 2:
            continue
        indexes = [
            index
            for uid in present_member_ids
            for index in row_indices_by_id.get(uid, [])
        ]
        if len(indexes) > 1:
            first = indexes[0]
            for index in indexes[1:]:
                if not union.union(first, index):
                    raise RuntimeError(
                        f"{relationship['id']} conflicts with a protected relationship"
                    )

    components = defaultdict(list)
    for index, row in enumerate(prepared):
        components[union.find(index)].append(row)

    entities = []
    override_canonical_by_member: dict[str, set[str]] = defaultdict(set)
    relationships_by_member: dict[str, list[str]] = defaultdict(list)
    for relationship in relationships:
        present_member_ids = {
            uid for uid in relationship["memberIds"] if row_indices_by_id.get(uid)
        }
        for uid in relationship["memberIds"]:
            relationships_by_member[uid].append(relationship["id"])
            if (
                relationship["type"] in MERGING_RELATION_TYPES
                and len(present_member_ids) >= 2
            ):
                override_canonical_by_member[uid].add(relationship["canonicalId"])
    for component in components.values():
        canonical_id = choose_canonical_id(
            component,
            aliases,
            manual_canonical_by_group,
            override_canonical_by_member,
            protected_member_ids,
        )
        representative = representative_row(component, canonical_id)
        appearances = sorted(
            (
                {
                    "source": row["source"],
                    "rank": row["rank"],
                    "year": row["year"],
                    "universityId": row["universityId"],
                    "name": row["name"],
                }
                for row in component
            ),
            key=lambda item: (SOURCE_ORDER[item["source"]], item["rank"], item["universityId"]),
        )
        ranking_sources = sorted({row["source"] for row in component}, key=SOURCE_ORDER.get)
        source_ids = sorted({row["universityId"] for row in component})
        relationship_ids = sorted(
            {
                relationship_id
                for uid in source_ids
                for relationship_id in relationships_by_member.get(uid, [])
            }
        )
        entities.append(
            {
                "canonicalId": canonical_id,
                "name": representative["name"],
                "country": representative["countryKey"],
                "rankingSourceCount": len(ranking_sources),
                "rankingEntryCount": len(component),
                "rankingSources": ranking_sources,
                "sourceUniversityIds": source_ids,
                "institutionRelationshipOverrideIds": relationship_ids,
                "rankingAppearances": appearances,
            }
        )
    return sorted(entities, key=lambda item: (item["country"], item["name"], item["canonicalId"]))


def match_raw_targets(entities: list[dict], raw_targets: list[dict], aliases: dict[str, str]) -> None:
    raw_id_sets = [target_ids(target, aliases) for target in raw_targets]
    raw_name_keys = [
        (normalized_country(target.get("country", "")), normalize_name(target.get("name", "")))
        for target in raw_targets
    ]
    for entity in entities:
        ids = entity_ids(entity, aliases)
        country = normalized_country(entity["country"])
        name_keys = {
            normalize_name(appearance["name"])
            for appearance in entity["rankingAppearances"]
            if normalize_name(appearance["name"])
        }
        # A canonical id is already deterministic identity evidence.  Country
        # is required for name fallback, where labels alone could collide.
        id_matches = {
            index for index, candidate_ids in enumerate(raw_id_sets) if ids & candidate_ids
        }
        name_matches = {
            index
            for index, (target_country, target_name) in enumerate(raw_name_keys)
            if target_country == country and target_name in name_keys
        }
        matches = sorted(id_matches | name_matches, key=lambda index: raw_targets[index]["universityId"])
        matched_targets = [raw_targets[index] for index in matches]
        entity["coveredByExistingRawTarget"] = bool(matches)
        entity["existingRawTargetIds"] = [target["universityId"] for target in matched_targets]
        entity["coverageMatch"] = (
            "id" if id_matches else "exact-name-country" if name_matches else None
        )
        entity["coverageAmbiguous"] = len(matches) > 1
        known_urls = [target.get("indexUrl") for target in matched_targets if target.get("indexUrl")]
        entity["indexUrl"] = known_urls[0] if known_urls else None


def source_report(source: str, rows: list[dict]) -> dict:
    ranks = [row["rank"] for row in rows]
    years = sorted({row["year"] for row in rows})
    return {
        "rows": len(rows),
        "year": years[0] if len(years) == 1 else None,
        "years": years,
        "rankRange": {"min": min(ranks), "max": max(ranks)},
        "uniqueUniversityIds": len({row["universityId"] for row in rows}),
    }


def resolve_ranking_files(
    rankings_dir: Path = RANKINGS_DIR,
    ranking_files: Mapping[str, Path] | None = None,
) -> dict[str, Path]:
    """Resolve one explicit input file per ranking source."""
    overrides = ranking_files or {}
    unknown = sorted(set(overrides) - set(SOURCES))
    if unknown:
        raise ValueError(f"unknown ranking source overrides: {', '.join(unknown)}")
    return {
        source: Path(overrides.get(source) or rankings_dir / f"{source}.json")
        for source in SOURCES
    }


def crawl_target_draft(entity: dict, raw_targets_by_id: dict[str, dict] | None = None) -> dict:
    matched_ids = entity.get("existingRawTargetIds") or []
    preferred_id = (
        entity["canonicalId"]
        if entity["canonicalId"] in matched_ids
        else matched_ids[0] if matched_ids else entity["canonicalId"]
    )
    inherited = dict((raw_targets_by_id or {}).get(preferred_id, {}))
    inherited.update({
        "universityId": preferred_id,
        "name": entity["name"],
        "country": entity["country"],
        "rankingSources": entity["rankingSources"],
        "sourceUniversityIds": entity["sourceUniversityIds"],
        "coveredByExistingRawTarget": entity["coveredByExistingRawTarget"],
        "existingRawTargetIds": entity["existingRawTargetIds"],
        "indexUrl": inherited.get("indexUrl") or entity["indexUrl"],
    })
    return inherited


def build_audit(
    rankings_dir: Path = RANKINGS_DIR,
    aliases_path: Path = ALIASES,
    raw_targets_path: Path = RAW_TARGETS,
    relationship_overrides_path: Path | None = RELATIONSHIP_OVERRIDES,
    expected_rows_per_source: int | None = EXPECTED_ROWS_PER_SOURCE,
    ranking_files: Mapping[str, Path] | None = None,
) -> dict:
    aliases_payload = load_json(aliases_path, {})
    aliases = aliases_payload.get("canonicalById", {})
    raw_targets = load_json(raw_targets_path, [])
    if not isinstance(raw_targets, list):
        raise RuntimeError("raw crawl targets must be a JSON array")
    relationship_overrides = load_relationship_overrides(relationship_overrides_path)

    input_files = resolve_ranking_files(rankings_dir, ranking_files)
    all_rows = []
    sources = {}
    for source in SOURCES:
        input_path = input_files[source]
        rows = load_json(input_path, [])
        if not isinstance(rows, list):
            raise RuntimeError(f"{source} ranking input must be a JSON array: {input_path}")
        if expected_rows_per_source is not None and len(rows) != expected_rows_per_source:
            raise RuntimeError(
                f"{source} row count changed in {input_path}: "
                f"expected {expected_rows_per_source}, found {len(rows)}"
            )
        for required in ("rank", "year", "universityId", "name", "country"):
            if any(required not in row for row in rows):
                raise RuntimeError(f"{source} has rows missing required field {required}")
        sources[source] = {
            **source_report(source, rows),
            "inputFile": str(input_path.resolve()),
        }
        all_rows.extend({**row, "source": source} for row in rows)

    entities = build_entities(all_rows, aliases, relationship_overrides)
    match_raw_targets(entities, raw_targets, aliases)
    gaps = [entity for entity in entities if not entity["coveredByExistingRawTarget"]]
    used_raw_target_ids = {
        target_id for entity in entities for target_id in entity["existingRawTargetIds"]
    }
    raw_targets_by_id = {target["universityId"]: target for target in raw_targets}
    drafts = [crawl_target_draft(entity, raw_targets_by_id) for entity in entities]
    relationships = relationship_overrides["relationships"]
    relationship_type_counts = Counter(item["type"] for item in relationships)
    active_relationship_ids = {
        relationship_id
        for entity in entities
        for relationship_id in entity["institutionRelationshipOverrideIds"]
    }
    return {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "rankingSources": list(SOURCES),
            "expectedRowsPerSource": expected_rows_per_source,
            "rawRankingRows": len(all_rows),
            "canonicalEntityCount": len(entities),
        },
        "sources": sources,
        "deduplication": {
            "countryBoundaryRequired": True,
            "automaticRules": [
                "existing-canonical-alias",
                "reviewed-manual-alias-group",
                "exact-normalized-name",
                "reviewed-same-institution-override",
                "reviewed-former-name-override",
            ],
            "nonMergingRelationshipTypes": sorted(NON_MERGING_RELATION_TYPES),
            "fuzzyMatchingUsed": False,
        },
        "institutionRelationshipOverrides": {
            "source": relationship_overrides["_source"],
            "relationshipCount": len(relationships),
            "activeRelationshipCount": len(active_relationship_ids),
            "countsByType": {
                relation_type: relationship_type_counts.get(relation_type, 0)
                for relation_type in sorted(RELATION_TYPES)
            },
            "relationships": relationships,
        },
        "existingRawTargetCoverage": {
            "rawTargetCount": len(raw_targets),
            "coveredCanonicalEntityCount": len(entities) - len(gaps),
            "gapCanonicalEntityCount": len(gaps),
            "usedRawTargetCount": len(used_raw_target_ids),
            "unusedRawTargetCount": len(raw_targets) - len(used_raw_target_ids),
        },
        "entities": entities,
        "gaps": [crawl_target_draft(entity, raw_targets_by_id) for entity in gaps],
        "crawlTargetDraft": drafts,
    }


def write_audit(audit: dict, output_path: Path = OUTPUT) -> None:
    output_path.write_bytes(json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8"))


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rankings-dir", type=Path, default=RANKINGS_DIR)
    for source in SOURCES:
        parser.add_argument(
            f"--{source}-file",
            type=Path,
            help=f"explicit {source.upper()} normalized Top 500 JSON input",
        )
    parser.add_argument("--aliases", type=Path, default=ALIASES)
    parser.add_argument("--raw-targets", type=Path, default=RAW_TARGETS)
    parser.add_argument(
        "--relationship-overrides",
        type=Path,
        default=RELATIONSHIP_OVERRIDES,
        help="reviewed institution relationship override JSON",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    ranking_files = {
        source: getattr(args, f"{source}_file")
        for source in SOURCES
        if getattr(args, f"{source}_file") is not None
    }
    audit = build_audit(
        rankings_dir=args.rankings_dir,
        aliases_path=args.aliases,
        raw_targets_path=args.raw_targets,
        relationship_overrides_path=args.relationship_overrides,
        ranking_files=ranking_files,
    )
    write_audit(audit, args.output)
    coverage = audit["existingRawTargetCoverage"]
    print(
        "[top500-targets] rows=%d canonical=%d existing-covered=%d gaps=%d"
        % (
            audit["scope"]["rawRankingRows"],
            audit["scope"]["canonicalEntityCount"],
            coverage["coveredCanonicalEntityCount"],
            coverage["gapCanonicalEntityCount"],
        )
    )
    print(f"[top500-targets] -> {args.output}")


if __name__ == "__main__":
    main()
