"""Build strict Feature 2 targets for official-domain sitemap discovery.

The queue is intentionally derived from the scope/coverage payload and the
identity-matched ROR evidence only.  Existing crawl manifests are not used to
invent or broaden an institution's domain boundary.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
COVERAGE = ROOT / "frontend" / "public" / "data" / "feature2_coverage.json"
VERIFICATION = ROOT / "scraper" / "playwright" / "top500_official_website_verification_v3.json"
OUTPUT = ROOT / "scraper" / "playwright" / "feature2_sitemap_targets.json"

COMMON_ROOT_PATHS = (
    "/graduate-programs",
    "/academics/graduate-programs",
    "/programs/graduate",
    "/academics/graduate",
    "/study/graduate",
    "/study/masters",
    "/postgraduate",
    "/masters",
    "/admissions/graduate/courses",
)
COMMON_SUBDOMAIN_PATHS = (
    ("graduate", "/programs"),
    ("grad", "/programs"),
    ("gradschool", "/programs"),
    ("gradsch", "/prospective-students/programmes"),
    ("gsas", "/programs-of-study"),
    ("study", "/postgraduate"),
    ("engineering", "/academics/graduate-programs"),
    ("www.cs", "/education/ms"),
    ("rackham", "/programs-of-study"),
)


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return default


def host(value: str) -> str:
    parsed = urlparse(str(value or ""))
    candidate = (parsed.hostname or str(value or "")).lower().rstrip(".")
    return candidate[4:] if candidate.startswith("www.") else candidate


def ror_identity_domains() -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    payload = load(VERIFICATION, {}) or {}
    for item in payload.get("items") or []:
        evidence = ((item.get("verification") or {}).get("evidence") or {}).get("registryIdentity") or {}
        if not (evidence.get("nameMatch") and evidence.get("countryMatch")):
            continue
        domains = set()
        organization = item.get("rorOrganization") or {}
        for value in organization.get("domains") or []:
            value = host(value)
            if value and "." in value:
                domains.add(value)
        for link in organization.get("links") or []:
            if link.get("type") == "website":
                value = host(link.get("value"))
                if value and "." in value:
                    domains.add(value)
        if domains and item.get("canonicalId"):
            result.setdefault(str(item["canonicalId"]), set()).update(domains)
    return result


def build() -> list[dict]:
    coverage = load(COVERAGE, {}) or {}
    missing = [
        row for row in coverage.get("schools") or []
        if row.get("coverageStatus") == "missing" and row.get("canonicalId")
    ]
    domains_by_id = ror_identity_domains()
    result = []
    for row in missing:
        cid = str(row["canonicalId"])
        domains = sorted(domains_by_id.get(cid) or set())
        if not domains:
            continue
        primary_domain = domains[0]
        catalog_pages = ["https://www." + primary_domain + path for path in COMMON_ROOT_PATHS]
        catalog_pages.extend(
            "https://" + subdomain + "." + primary_domain + path
            for subdomain, path in COMMON_SUBDOMAIN_PATHS
        )
        result.append({
            "universityId": cid,
            "canonicalId": cid,
            "name": row.get("name") or cid,
            "country": row.get("country") or "",
            "region": "",
            "officialDomains": domains,
            "indexUrl": "https://" + primary_domain + "/",
            "catalogPages": catalog_pages,
            "programUrls": [],
            # This is a local queue capability flag.  The provenance below
            # records that it comes from ROR name/country identity evidence.
            "verificationStatus": "verified",
            "domainVerification": "ror-name-country-match",
            "domainVerificationSource": "top500_official_website_verification_v3.json",
            "catalogSeedPolicy": "common-paths-on-ror-domain-or-child-subdomain",
        })
    return sorted(result, key=lambda item: (item["country"], item["name"], item["universityId"]))


def main() -> None:
    records = build()
    OUTPUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "targets": len(records),
        "output": str(OUTPUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
