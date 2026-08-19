"""Build non-binding entity-resolution proposals for the latest four Top 500 lists.

The output is an audit artifact, not an alias map. It never mutates
``university_aliases.json``, crawl targets, raw manifests, or frontend data.
Only same-country, cross-source groups are considered. High-confidence groups
still require review before they may be copied into the canonical alias map.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit_v2.json"
DEFAULT_OUTPUT = ROOT / "scraper" / "programs" / "top500_alias_proposals.json"

SOURCE_ORDER = {"qs": 0, "the": 1, "arwu": 2, "usnews": 3}
STOP_WORDS = {
    "and", "at", "da", "de", "del", "della", "den", "der", "des", "di",
    "do", "du", "el", "et", "for", "in", "la", "las", "le", "los", "of",
    "the", "und", "universidad", "universidade", "universita", "universitaet",
    "universitas", "universitat", "universite", "universiteit", "universitet",
    "universitesi", "universities", "university", "univerza", "univerzita",
    "univerzitet", "van", "y", "zu", "zur",
}
TOKEN_TRANSLATIONS = {
    "autonoma": "autonomous", "autonome": "autonomous",
    "catolica": "catholic", "cattolica": "catholic", "catholique": "catholic",
    "ciencia": "science", "ciencias": "science", "sciences": "science",
    "estatal": "state", "estadual": "state", "federale": "federal",
    "freie": "free", "libre": "free", "nacional": "national",
    "nationale": "national", "politecnica": "polytechnic",
    "politecnico": "polytechnic", "polytechnique": "polytechnic",
    "tecnica": "technical", "technische": "technical", "technique": "technical",
    "tecnico": "technical", "tecnologica": "technology", "tecnologia": "technology",
    "firenze": "florence", "genova": "genoa", "koeln": "cologne",
    "koln": "cologne", "lisboa": "lisbon", "milano": "milan",
    "muenchen": "munich", "munchen": "munich", "napoli": "naples",
    "padova": "padua", "praha": "prague", "roma": "rome",
    "sevilla": "seville", "torino": "turin", "wien": "vienna",
    "zaragoza": "saragossa",
}

# These are containment/abbreviation cases that cannot be derived from exact
# translated tokens alone. They are proposals, not applied aliases.
REVIEWED_HIGH_GROUPS = [
    ["u_the_university_of_newcastle_australia_uon", "u_university_of_newcastle"],
    ["u_the_university_of_queensland", "u_university_of_queensland_australia"],
    ["u_queens_university_at_kingston", "u_queens_university"],
    ["u_indian_institute_of_science", "u_indian_institute_of_science_iisc_bangalore"],
    ["u_national_tsing_hua_university", "u_national_tsing_hua_university_nthu"],
    ["u_china_medical_university_taichung", "u_china_medical_university_taiwan"],
    ["u_universiti_malaya_um", "u_university_of_malaya"],
    ["u_nanyang_technological_university", "u_nanyang_technological_university_singapore_ntu_singapore"],
    ["u_ntnu_norwegian_university_of_science_and_technology", "u_norwegian_university_of_science_and_technology"],
    ["u_north_carolina_state_university", "u_north_carolina_state_university_at_raleigh", "u_north_carolina_state_university_raleigh"],
    ["u_northeastern_university", "u_northeastern_university_us"],
    ["u_ohio_state_university_main_campus", "u_the_ohio_state_university_columbus"],
    ["u_pennsylvania_state_university", "u_pennsylvania_state_university_university_park"],
    ["u_purdue_university", "u_purdue_university_west_lafayette"],
    ["u_rutgers_universitynew_brunswick", "u_rutgers_the_state_university_of_new_jersey_new_brunswick"],
    ["u_stony_brook_university", "u_stony_brook_university_state_university_of_new_york", "u_stony_brook_university_suny"],
    ["u_texas_am_university", "u_texas_am_university_college_station"],
    ["u_university_at_buffalo", "u_university_at_buffalo_suny"],
    ["u_university_of_minnesota", "u_university_of_minnesota_twin_cities"],
    ["u_university_of_missouri", "u_university_of_missouri_columbia"],
    ["u_university_of_pittsburgh", "u_university_of_pittsburgh_pittsburgh_campus"],
    ["u_university_of_texas_southwestern_medical_center", "u_university_of_texas_southwestern_medical_center_dallas"],
    ["u_lomonosov_moscow_state_university", "u_moscow_state_university"],
    ["u_saint_petersburg_state_university", "u_st_petersburg_university"],
    ["u_qatar_university", "u_university_of_qatar"],
    ["u_northeastern_university_shenyang", "u_northeastern_university_china"],
    ["u_northwest_af_university", "u_northwest_af_university_china"],
    ["u_southern_medical_university", "u_southern_medical_university_china"],
    ["u_southwest_university", "u_southwest_university_china"],
    ["u_university_of_science_and_technology_of_china", "u_university_of_science_technology_of_china_cas"],
]

MEDIUM_REVIEW_GROUPS = [
    {
        "ids": ["u_adelaide_university", "u_the_university_of_adelaide"],
        "relation": "successorOf",
        "reason": "Adelaide University is a new 2026 legal entity formed from the University of Adelaide and UniSA; this is temporal succession, not a plain alias.",
    },
    {
        "ids": ["u_indiana_university", "u_indiana_university_bloomington", "u_indiana_university_indianapolis"],
        "relation": "systemCampus",
        "reason": "The unqualified system label is ambiguous while separate campuses occur in the same ranking scope.",
    },
    {
        "ids": ["u_university_of_massachusetts", "u_university_of_massachusetts_amherst", "u_university_of_massachusetts_chan_medical_school", "u_university_of_massachusetts_worcester"],
        "relation": "systemCampus",
        "reason": "The unqualified system label cannot safely be assigned to Amherst or the medical campus without provider evidence.",
    },
    {
        "ids": ["u_university_of_colorado_denveranschutz_medical_campus", "u_university_of_colorado_at_denver", "u_university_of_colorado_denver", "u_university_of_colorado_anschutz_medical_campus"],
        "relation": "systemCampus",
        "reason": "Providers mix Denver and Anschutz at different institutional grains.",
    },
    {
        "ids": ["u_the_university_of_tennessee_knoxville", "u_university_of_tennessee"],
        "relation": "systemCampus",
        "reason": "The US News label omits Knoxville and may denote the system rather than the ranked campus.",
    },
    {
        "ids": ["u_universite_de_paris", "u_universite_paris_cite", "u_universite_de_paris_cite"],
        "relation": "formerName",
        "reason": "Universite de Paris became Universite Paris Cite in 2022; source IDs and accents vary.",
    },
]

EXCLUDED_GROUPS = [
    {
        "ids": ["u_osaka_metropolitan_university", "u_the_university_of_osaka", "u_osaka_university"],
        "reason": "Osaka Metropolitan University and The University of Osaka are separate institutions; only Osaka University and The University of Osaka are aliases.",
    },
    {
        "ids": ["u_northwest_university", "u_northwest_af_university", "u_northwest_af_university_china"],
        "reason": "Northwest University and Northwest A&F University are separate institutions.",
    },
]

CANONICAL_OVERRIDES = {
    "u_universidad_de_buenos_aires_uba": "u_university_of_buenos_aires",
    "u_osaka_university": "u_the_university_of_osaka",
    "u_university_of_sao_paulo": "u_universidade_de_sao_paulo",
}


def ascii_text(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).lower()


def semantic_tokens(name: str) -> tuple[str, ...]:
    text = ascii_text(re.sub(r"\([^)]*\)", " ", name)).replace("&", " and ")
    tokens = []
    for token in re.findall(r"[a-z0-9]+", text):
        if len(token) <= 1 or token in STOP_WORDS:
            continue
        tokens.append(TOKEN_TRANSLATIONS.get(token, token))
    return tuple(sorted(set(tokens)))


def source_set(entity: dict) -> set[str]:
    return set(entity.get("rankingSources") or [])


def choose_canonical(entities: list[dict]) -> str:
    ids = {entity["canonicalId"] for entity in entities}
    for candidate, canonical in CANONICAL_OVERRIDES.items():
        if candidate in ids and canonical in ids:
            return canonical
    covered = [entity for entity in entities if entity.get("coveredByExistingRawTarget")]
    pool = covered or entities
    return min(
        pool,
        key=lambda entity: (
            -len(source_set(entity)),
            min((row.get("rank", 10**9) for row in entity.get("rankingAppearances") or []), default=10**9),
            entity["canonicalId"],
        ),
    )["canonicalId"]


def group_payload(entities: list[dict], reason: str, confidence: str = "high") -> dict:
    canonical = choose_canonical(entities)
    appearances = sorted(
        (row for entity in entities for row in entity.get("rankingAppearances") or []),
        key=lambda row: (SOURCE_ORDER.get(row.get("source"), 99), row.get("rank", 10**9)),
    )
    return {
        "proposalStatus": "review-required",
        "confidence": confidence,
        "relation": "sameInstitution",
        "recommendedCanonicalId": canonical,
        "entityIds": sorted(entity["canonicalId"] for entity in entities),
        "sourceIds": sorted({uid for entity in entities for uid in entity.get("sourceUniversityIds") or [entity["canonicalId"]]}),
        "country": entities[0].get("country", ""),
        "names": sorted({row.get("name", "") for row in appearances}),
        "rankingAppearances": appearances,
        "reason": reason,
    }


def resolve_ids(ids: list[str], entities_by_any_id: dict[str, dict]) -> list[dict]:
    resolved = []
    seen = set()
    for uid in ids:
        entity = entities_by_any_id.get(uid)
        if entity and entity["canonicalId"] not in seen:
            resolved.append(entity)
            seen.add(entity["canonicalId"])
    return resolved


def consolidate_overlapping_groups(groups: list[dict], entities_by_id: dict[str, dict]) -> list[dict]:
    """Union proposal groups that share a current canonical entity."""
    components: list[dict] = []
    for group in groups:
        ids = set(group["entityIds"])
        touching = [component for component in components if ids & component["ids"]]
        if not touching:
            components.append({"ids": ids, "reasons": {group["reason"]}})
            continue
        combined = ids.copy()
        reasons = {group["reason"]}
        for component in touching:
            combined.update(component["ids"])
            reasons.update(component["reasons"])
            components.remove(component)
        components.append({"ids": combined, "reasons": reasons})

    output = []
    for component in components:
        members = [entities_by_id[uid] for uid in sorted(component["ids"])]
        output.append(group_payload(members, " ".join(sorted(component["reasons"]))))
    return output


def build_proposals(audit: dict) -> dict:
    entities = audit.get("entities") or []
    entities_by_id = {entity["canonicalId"]: entity for entity in entities}
    entities_by_any_id = dict(entities_by_id)
    for entity in entities:
        for uid in entity.get("sourceUniversityIds") or []:
            entities_by_any_id.setdefault(uid, entity)
    grouped = defaultdict(list)
    for entity in entities:
        key = (entity.get("country", ""), semantic_tokens(entity.get("name", "")))
        if key[1]:
            grouped[key].append(entity)

    medium_sets = [set(group["ids"]) for group in MEDIUM_REVIEW_GROUPS]
    high = []
    seen = set()
    for (_, tokens), members in grouped.items():
        if len(members) < 2:
            continue
        ids = {member["canonicalId"] for member in members}
        if any(ids <= review_group for review_group in medium_sets):
            # Temporal succession and system/campus ambiguity take priority
            # over a coincidentally identical translated token set.
            continue
        if any(source_set(left) & source_set(right) for index, left in enumerate(members) for right in members[index + 1:]):
            continue
        key = frozenset(ids)
        high.append(group_payload(members, "Exact same-country translated semantic token set: " + ", ".join(tokens)))
        seen.add(key)

    for ids in REVIEWED_HIGH_GROUPS:
        members = resolve_ids(ids, entities_by_any_id)
        if len(members) < 2 or len({member.get("country") for member in members}) != 1:
            continue
        key = frozenset(member["canonicalId"] for member in members)
        if key in seen:
            continue
        high.append(group_payload(members, "Reviewed abbreviation, translation, or explicitly named main-campus equivalence."))
        seen.add(key)

    high = consolidate_overlapping_groups(high, entities_by_id)

    medium = []
    for specification in MEDIUM_REVIEW_GROUPS:
        members = resolve_ids(specification["ids"], entities_by_any_id)
        if len(members) < 2:
            continue
        payload = group_payload(members, specification["reason"], confidence="medium")
        payload["relation"] = specification["relation"]
        payload["recommendedCanonicalId"] = None
        medium.append(payload)

    excluded = []
    for specification in EXCLUDED_GROUPS:
        members = resolve_ids(specification["ids"], entities_by_any_id)
        if len(members) < 2:
            continue
        excluded.append({
            "proposalStatus": "do-not-merge",
            "sourceIds": sorted(member["canonicalId"] for member in members),
            "country": members[0].get("country", ""),
            "names": sorted(member.get("name", "") for member in members),
            "reason": specification["reason"],
        })

    high.sort(key=lambda group: (group["country"], group["recommendedCanonicalId"] or ""))
    medium.sort(key=lambda group: (group["country"], group["sourceIds"]))
    excluded.sort(key=lambda group: (group["country"], group["sourceIds"]))

    gap_counts = Counter(entity.get("country", "") for entity in entities if not entity.get("coveredByExistingRawTarget"))
    proposed_reductions = Counter()
    for group in high:
        gap_ids = {
            entity["canonicalId"] for entity in entities
            if not entity.get("coveredByExistingRawTarget")
        }
        member_gap_count = len(set(group["entityIds"]) & gap_ids)
        if member_gap_count > 1:
            proposed_reductions[group["country"]] += member_gap_count - 1
    top_countries = [
        {
            "country": country,
            "currentGapEntities": count,
            "highConfidenceReductionIfApproved": proposed_reductions[country],
            "projectedGapEntitiesIfApproved": count - proposed_reductions[country],
        }
        for country, count in gap_counts.most_common(10)
    ]

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceAudit": str(DEFAULT_AUDIT),
        "sourceAuditGeneratedAt": audit.get("generatedAt"),
        "policy": {
            "binding": False,
            "automaticMergeAllowed": False,
            "countryBoundaryRequired": True,
            "crossSourceEvidenceRequired": True,
            "frontendDataModified": False,
            "rawCrawlTargetsModified": False,
        },
        "counts": {
            "rankingRows": audit.get("scope", {}).get("rawRankingRows"),
            "currentCanonicalEntities": len(entities),
            "highConfidenceProposalGroups": len(high),
            "mediumConfidenceReviewGroups": len(medium),
            "explicitDoNotMergeGroups": len(excluded),
            "highConfidenceEntityReductionIfApproved": sum(len(group["entityIds"]) - 1 for group in high),
        },
        "top10GapCountries": top_countries,
        "highConfidenceDuplicateGroups": high,
        "mediumConfidenceReviewGroups": medium,
        "explicitDoNotMergeGroups": excluded,
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    audit = json.loads(args.audit.read_text(encoding="utf-8-sig"))
    payload = build_proposals(audit)
    payload["sourceAudit"] = str(args.audit.resolve())
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "[top500-alias-proposals] high=%d medium=%d excluded=%d reduction-if-approved=%d"
        % (
            payload["counts"]["highConfidenceProposalGroups"],
            payload["counts"]["mediumConfidenceReviewGroups"],
            payload["counts"]["explicitDoNotMergeGroups"],
            payload["counts"]["highConfidenceEntityReductionIfApproved"],
        )
    )
    print(f"[top500-alias-proposals] -> {args.output}")


if __name__ == "__main__":
    main()
