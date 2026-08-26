"""Build the compact school URL index consumed by the static frontend.

The output keeps school homepages separate from programme-directory URLs and
records how strongly each URL was verified. Rejected identity candidates are
never published. All inputs are existing local evidence; this script performs
no network requests.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "frontend" / "public" / "data"
PLAYWRIGHT = ROOT / "scraper" / "playwright"
OUTPUT = DATA / "school_urls.json"

VERIFICATION_FILES = (
    PLAYWRIGHT / "top500_official_website_verification_v3.json",
    PLAYWRIGHT / "top500_official_website_verification_structured_identity_v4.json",
)
FEATURE2_COVERAGE = DATA / "feature2_coverage.json"
PROGRAM_COVERAGE = DATA / "program_coverage.json"
CSRANKINGS_INSTITUTIONS = ROOT / "raw" / "rankings" / "csrankings" / "institutions.csv"
CSRANKINGS_RANKING = DATA / "rankings" / "csrankings.json"
UNIVERSITY_ALIASES = DATA / "university_aliases.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return default


def web_url(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return text


def first_web_url(values: Iterable[Any]) -> Optional[str]:
    for value in values:
        url = web_url(value)
        if url:
            return url
    return None


def normalized_host(value: Any) -> str:
    url = web_url(value)
    if not url:
        return ""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def hosts_overlap(left: Any, right: Any) -> bool:
    left_host = normalized_host(left)
    right_host = normalized_host(right)
    if not left_host or not right_host:
        return False
    return (
        left_host == right_host
        or left_host.endswith(f".{right_host}")
        or right_host.endswith(f".{left_host}")
    )


def remove_cross_school_program_urls(
    records: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    trusted = [
        (canonical_id, row["url"])
        for canonical_id, row in records.items()
        if row.get("urlKind") != "official-programme-index"
    ]
    return {
        canonical_id: row
        for canonical_id, row in records.items()
        if row.get("urlKind") != "official-programme-index"
        or not any(
            other_id != canonical_id and hosts_overlap(row.get("url"), other_url)
            for other_id, other_url in trusted
        )
    }


def ror_website(item: Dict[str, Any]) -> Optional[str]:
    organization = item.get("rorOrganization")
    if not isinstance(organization, dict):
        return None
    links = organization.get("links")
    if not isinstance(links, list):
        return None
    return first_web_url(
        link.get("value")
        for link in links
        if isinstance(link, dict) and link.get("type") == "website"
    )


def verification_candidate(item: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    verification = item.get("verification")
    evidence = verification.get("evidence", {}) if isinstance(verification, dict) else {}
    status = str(
        item.get("verificationStatus")
        or (verification.get("verificationStatus") if isinstance(verification, dict) else "")
        or ""
    ).lower()
    if status not in {"verified", "blocked", "review"}:
        return None

    live = evidence.get("liveOfficialPage") if isinstance(evidence, dict) else {}
    domain = evidence.get("domainConsistency") if isinstance(evidence, dict) else {}
    live = live if isinstance(live, dict) else {}
    domain = domain if isinstance(domain, dict) else {}
    if status == "verified":
        candidates = (
            live.get("finalUrl"),
            live.get("requestedUrl"),
            domain.get("candidateUrl"),
            ror_website(item),
        )
    else:
        candidates = (
            domain.get("candidateUrl"),
            ror_website(item),
            live.get("requestedUrl"),
        )
    url = first_web_url(candidates)
    return (url, status) if url else None


def add_record(
    records: Dict[str, Dict[str, Any]],
    priorities: Dict[str, int],
    *,
    canonical_id: Any,
    name: Any,
    country: Any,
    url: Any,
    url_kind: str,
    verification_status: str,
    source_file: Path,
    priority: int,
) -> None:
    identifier = str(canonical_id or "").strip()
    clean_url = web_url(url)
    if not identifier or not clean_url or priority <= priorities.get(identifier, -1):
        return
    priorities[identifier] = priority
    records[identifier] = {
        "canonicalId": identifier,
        "name": str(name or "").strip(),
        "country": str(country or "").strip(),
        "url": clean_url,
        "urlKind": url_kind,
        "verificationStatus": verification_status,
        "sourceFile": source_file.relative_to(ROOT).as_posix(),
    }


def build() -> Dict[str, Any]:
    records: Dict[str, Dict[str, Any]] = {}
    priorities: Dict[str, int] = {}
    input_files = []

    for path in VERIFICATION_FILES:
        payload = load_json(path, {})
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            continue
        if path.exists():
            input_files.append(path.relative_to(ROOT).as_posix())
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = verification_candidate(item)
            if not candidate:
                continue
            url, status = candidate
            add_record(
                records,
                priorities,
                canonical_id=item.get("canonicalId"),
                name=item.get("name"),
                country=item.get("country"),
                url=url,
                url_kind="school-homepage",
                verification_status=status,
                source_file=path,
                priority={"verified": 100, "blocked": 70, "review": 60}[status],
            )

    feature_payload = load_json(FEATURE2_COVERAGE, {})
    feature_rows = feature_payload.get("schools", []) if isinstance(feature_payload, dict) else []
    if FEATURE2_COVERAGE.exists():
        input_files.append(FEATURE2_COVERAGE.relative_to(ROOT).as_posix())
    for row in feature_rows if isinstance(feature_rows, list) else []:
        if not isinstance(row, dict) or row.get("coverageStatus") != "covered":
            continue
        url = first_web_url(row.get("urls", []))
        add_record(
            records,
            priorities,
            canonical_id=row.get("canonicalId"),
            name=row.get("name"),
            country=row.get("country"),
            url=url,
            url_kind="official-programme-directory",
            verification_status="verified",
            source_file=FEATURE2_COVERAGE,
            priority=90,
        )

    program_rows = load_json(PROGRAM_COVERAGE, [])
    if PROGRAM_COVERAGE.exists():
        input_files.append(PROGRAM_COVERAGE.relative_to(ROOT).as_posix())
    for row in program_rows if isinstance(program_rows, list) else []:
        if not isinstance(row, dict):
            continue
        add_record(
            records,
            priorities,
            canonical_id=row.get("universityId"),
            name=row.get("name"),
            country=row.get("country"),
            url=row.get("indexUrl"),
            url_kind="official-programme-index",
            verification_status="recorded",
            source_file=PROGRAM_COVERAGE,
            priority=80,
        )

    cs_homepages: Dict[str, str] = {}
    try:
        with CSRANKINGS_INSTITUTIONS.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                name = str(row.get("institution") or "").strip()
                url = web_url(row.get("homepage"))
                if name and url:
                    cs_homepages[name.casefold()] = url
    except (FileNotFoundError, OSError, UnicodeError, csv.Error):
        pass
    if CSRANKINGS_INSTITUTIONS.exists():
        input_files.append(CSRANKINGS_INSTITUTIONS.relative_to(ROOT).as_posix())

    aliases_payload = load_json(UNIVERSITY_ALIASES, {})
    canonical_by_id = aliases_payload.get("canonicalById", {}) if isinstance(aliases_payload, dict) else {}
    cs_rows = load_json(CSRANKINGS_RANKING, [])
    for path in (CSRANKINGS_RANKING, UNIVERSITY_ALIASES):
        if path.exists():
            input_files.append(path.relative_to(ROOT).as_posix())
    for row in cs_rows if isinstance(cs_rows, list) else []:
        if not isinstance(row, dict):
            continue
        university_id = str(row.get("universityId") or "")
        canonical_id = canonical_by_id.get(university_id, university_id)
        add_record(
            records,
            priorities,
            canonical_id=canonical_id,
            name=row.get("name"),
            country=row.get("country"),
            url=cs_homepages.get(str(row.get("name") or "").strip().casefold()),
            url_kind="official-department",
            verification_status="recorded",
            source_file=CSRANKINGS_INSTITUTIONS,
            priority=85,
        )

    records = remove_cross_school_program_urls(records)
    schools = sorted(records.values(), key=lambda row: (row["country"], row["name"], row["canonicalId"]))
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "schoolsWithUrl": len(schools),
            "byUrlKind": dict(sorted(Counter(row["urlKind"] for row in schools).items())),
            "byVerificationStatus": dict(sorted(Counter(row["verificationStatus"] for row in schools).items())),
        },
        "sourceFiles": input_files,
        "schools": schools,
    }


def main() -> None:
    payload = build()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"school_urls.json: {payload['summary']['schoolsWithUrl']} schools")


if __name__ == "__main__":
    main()
