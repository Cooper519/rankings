"""Build the first detailed-crawl target set from four ranking snapshots.

Round 1 includes ranks 50 through 250 (inclusive) from QS, THE, ARWU, and
U.S. News. Mainland-China rows are excluded using the shared country policy;
Hong Kong, Macau, and Taiwan remain in scope. This command performs no network
requests and never guesses an official domain.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from .scope_policy import is_mainland_china_country


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "frontend" / "public" / "data"
RANKINGS = DATA / "rankings"
ALIASES = DATA / "university_aliases.json"
UNIVERSITIES = DATA / "universities.json"
SCHOOL_URLS = DATA / "school_urls.json"
OUTPUT = ROOT / "raw" / "rankings" / "round1_50_250_targets.json"
AUDIT = ROOT / "raw" / "rankings" / "round1_50_250_audit.json"
SOURCES = ("qs", "the", "arwu", "usnews")
MIN_RANK = 50
MAX_RANK = 250


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def canonical_id(identifier: str, aliases: Mapping[str, str]) -> str:
    current = identifier
    seen = set()
    while aliases.get(current) and aliases[current] != current and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def host_of(url: str) -> str:
    try:
        host = (urlsplit(url or "").hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def rank_value(row: Mapping[str, Any]) -> int:
    value = row.get("rank")
    if isinstance(value, bool):
        raise ValueError("ranking rank cannot be boolean")
    return int(value)


def in_scope(row: Mapping[str, Any]) -> bool:
    rank = rank_value(row)
    return MIN_RANK <= rank <= MAX_RANK and not is_mainland_china_country(row.get("country"))


def choose_url(rows: List[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    priorities = {
        "official-programme-directory": 4,
        "official-programme-index": 3,
        "school-homepage": 2,
        "official-department": 1,
    }
    usable = [row for row in rows if host_of(str(row.get("url") or ""))]
    if not usable:
        return None
    return max(
        usable,
        key=lambda row: (
            priorities.get(str(row.get("urlKind") or ""), 0),
            str(row.get("verificationStatus") or "") == "verified",
            str(row.get("url") or ""),
        ),
    )


def build(
    ranking_rows: Mapping[str, Iterable[Mapping[str, Any]]],
    aliases: Mapping[str, str],
    universities: Mapping[str, Mapping[str, Any]],
    school_url_rows: Iterable[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    source_counts: Counter[str] = Counter()
    excluded_mainland = Counter()
    for source in SOURCES:
        rows = list(ranking_rows.get(source, []))
        for row in rows:
            rank = rank_value(row)
            if not MIN_RANK <= rank <= MAX_RANK:
                continue
            if is_mainland_china_country(row.get("country")):
                excluded_mainland[source] += 1
                continue
            identifier = str(row.get("universityId") or "").strip()
            if not identifier:
                raise ValueError(f"{source} row is missing universityId")
            canonical = canonical_id(identifier, aliases)
            grouped[canonical].append({
                "source": source,
                "rank": rank,
                "year": int(row.get("year") or 0),
                "universityId": identifier,
                "name": str(row.get("name") or "").strip(),
                "country": str(row.get("country") or "").strip(),
            })
            source_counts[source] += 1

    urls_by_id: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for row in school_url_rows:
        identifier = str(row.get("canonicalId") or "").strip()
        if identifier:
            urls_by_id[canonical_id(identifier, aliases)].append(row)

    targets = []
    for identifier, appearances in grouped.items():
        appearances.sort(key=lambda row: (SOURCES.index(row["source"]), row["rank"], row["name"]))
        university = universities.get(identifier, {})
        representative = min(appearances, key=lambda row: (row["rank"], SOURCES.index(row["source"])))
        name_value = university.get("name") if isinstance(university, dict) else None
        canonical_name = name_value.get("en") if isinstance(name_value, dict) else ""
        name = str(canonical_name or representative["name"])
        country = str(university.get("country") or representative["country"])
        region = str(university.get("region") or "")
        selected_url = choose_url(urls_by_id.get(identifier, []))
        index_url = str((selected_url or {}).get("url") or "")
        domain = host_of(index_url)
        targets.append({
            "universityId": identifier,
            "name": name,
            "country": country,
            "region": region,
            "officialDomains": [domain] if domain else [],
            "indexUrl": index_url,
            "catalogPages": [],
            "programUrls": [],
            "evidenceUrls": [],
            "apiEndpoints": [],
            "discoveryStrategy": "recursive-catalog",
            "officialVerificationStatus": str((selected_url or {}).get("verificationStatus") or "missing"),
            "urlKind": (selected_url or {}).get("urlKind"),
            "rankingSources": sorted({row["source"] for row in appearances}, key=SOURCES.index),
            "rankingAppearances": appearances,
            "scope": {
                "round": "round1",
                "rankMin": MIN_RANK,
                "rankMax": MAX_RANK,
                "mainlandChinaExcluded": True,
            },
        })
    targets.sort(key=lambda row: (
        min(item["rank"] for item in row["rankingAppearances"]),
        row["country"],
        row["name"],
        row["universityId"],
    ))
    audit = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "rankingSources": list(SOURCES),
            "rankMin": MIN_RANK,
            "rankMax": MAX_RANK,
            "rankBoundsInclusive": True,
            "mainlandChinaExcluded": True,
            "hongKongMacauTaiwanIncluded": True,
        },
        "summary": {
            "rankingEntries": sum(source_counts.values()),
            "canonicalUniversities": len(targets),
            "withOfficialUrl": sum(bool(row["indexUrl"]) for row in targets),
            "withoutOfficialUrl": sum(not row["indexUrl"] for row in targets),
            "entriesBySource": dict(source_counts),
            "excludedMainlandBySource": dict(excluded_mainland),
            "countries": dict(sorted(Counter(row["country"] for row in targets).items())),
        },
        "inputs": {
            "rankings": [f"frontend/public/data/rankings/{source}.json" for source in SOURCES],
            "aliases": "frontend/public/data/university_aliases.json",
            "schoolUrls": "frontend/public/data/school_urls.json",
        },
    }
    return targets, audit


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--audit-output", type=Path, default=AUDIT)
    args = parser.parse_args(argv)
    aliases_payload = load_json(ALIASES, {})
    school_payload = load_json(SCHOOL_URLS, {})
    targets, audit = build(
        {source: load_json(RANKINGS / f"{source}.json", []) for source in SOURCES},
        aliases_payload.get("canonicalById", {}),
        load_json(UNIVERSITIES, {}),
        school_payload.get("schools", []),
    )
    write_json(args.output, targets)
    write_json(args.audit_output, audit)
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))
    print(f"[round1-targets] -> {args.output}")


if __name__ == "__main__":
    main()
