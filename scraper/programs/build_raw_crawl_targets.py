"""Build the frozen raw-first programme crawl target set.

The user-approved scope predates the current ranking union.  It contains 327
historical European ranking entries.  Five research institutes do not award
master's degrees and are excluded, leaving 322 ranking entries.  Provider
aliases are grouped into physical universities so the crawler visits 293
institutions once while retaining an auditable mapping to all 322 entries.

This script only writes crawler inputs and an audit report.  It does not read
or mutate cleaned programme data in the frontend.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent.parent
PW = ROOT / "scraper" / "playwright"
DATA = ROOT / "frontend" / "public" / "data"
HISTORICAL = PW / "program_catalog_all.json"
ALIASES = DATA / "university_aliases.json"
OUTPUT = PW / "raw_crawl_targets.json"
AUDIT = PW / "raw_crawl_target_audit.json"
OVERRIDE_FILES = (
    PW / "catalog_overrides_priority_a.json",
    PW / "catalog_overrides_priority_b.json",
    PW / "catalog_overrides_priority_c.json",
)

EXPECTED_RANKING_ENTRIES = 322
RANKING_SOURCES = ("qs", "the", "arwu", "usnews", "csrankings")
EUROPE = {"Western Europe", "Northern Europe", "Southern Europe", "Eastern Europe"}
EXCLUDE_COUNTRIES = {"United Kingdom", "Ireland"}
NON_DEGREE_INSTITUTIONS = {
    "u_inria": "research institute; does not award master's degrees",
    "u_cispa_helmholtz_center": "research institute; does not award master's degrees",
    "u_max_planck_society": "research organization; does not award master's degrees",
    "u_cwi": "research institute; does not award master's degrees",
    "u_imdea_software_institute": "research institute; does not award master's degrees",
}
SUPPLEMENTAL_NON_DEGREE_INSTITUTIONS = {
    "u_insait": "research institute within Sofia University; not an independent master's degree provider",
    "u_ipi_pan": "research institute focused on doctoral education; no regular master's degree catalogue",
    "u_kempelen_institute_kinit": "research institute; independent degree authority is unconfirmed",
    "u_imdea_networks_institute": "research institute; programme ownership belongs to partner universities",
    "u_gssi": "doctoral school; no master's degree catalogue",
}
DENIED_HOSTS = {
    "wikipedia.org", "daad.de", "mygermanuniversity.com", "studyportals.com",
    "mastersportal.com", "findamasters.com", "masterstudies.com",
    "topuniversities.com", "timeshighereducation.com", "shanghairanking.com",
    "usnews.com", "reddit.com", "linkedin.com", "facebook.com",
    "instagram.com", "youtube.com", "globalstudyprep.com",
    "globaladmissions.com", "university-directory.eu", "collegelearners.org",
    "studyindenmark.dk", "educations.com", "study.eu",
}


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def repair_mojibake(value):
    """Repair UTF-8 bytes decoded as Windows-1252 without changing ids."""
    text = value or ""
    markers = ("Ã", "Â", "â", "ð", "�")
    for _ in range(3):
        before = sum(text.count(marker) for marker in markers)
        if before == 0:
            break
        try:
            repaired = text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        after = sum(repaired.count(marker) for marker in markers)
        if after >= before:
            break
        text = repaired
    return text


def as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def host_of(url):
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def denied_host(host):
    return any(host == item or host.endswith("." + item) for item in DENIED_HOSTS)


def valid_url(url):
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def add_unique(target, value):
    if value and value not in target:
        target.append(value)


def canonical_id(uid, aliases):
    seen = set()
    current = uid
    while aliases.get(current, current) != current and current not in seen:
        seen.add(current)
        current = aliases[current]
    return current


def read_config_hints(aliases):
    """Collect URLs from existing raw/config files without running cleaners."""
    hints = defaultdict(lambda: {
        "domains": [], "catalogs": [], "programs": [], "evidence": [],
        "catalog_scores": defaultdict(int), "provenance": [],
    })

    def bucket(uid):
        return hints[canonical_id(uid, aliases)]

    def ingest(item, source, base_score):
        if not isinstance(item, dict) or not item.get("universityId"):
            return
        row = bucket(item["universityId"])
        add_unique(row["provenance"], source)
        for domain in item.get("officialDomains") or []:
            domain = str(domain).lower()
            if domain.startswith("www."):
                domain = domain[4:]
            if domain and not denied_host(domain):
                add_unique(row["domains"], domain)
        for field, key in (("programUrls", "programs"), ("evidenceUrls", "evidence")):
            for value in item.get(field) or []:
                url = value if isinstance(value, str) else value.get("url") or value.get("href")
                if valid_url(url) and not denied_host(host_of(url)):
                    add_unique(row[key], url)
        for field in ("indexUrl", "catalogUrl", "listHref"):
            url = item.get(field) or ""
            if not valid_url(url) or denied_host(host_of(url)):
                continue
            add_unique(row["catalogs"], url)
            row["catalog_scores"][url] += base_score
            host = host_of(url)
            if host and not denied_host(host):
                add_unique(row["domains"], host)
        for url in item.get("catalogPages") or []:
            if valid_url(url) and not denied_host(host_of(url)):
                add_unique(row["catalogs"], url)
                row["catalog_scores"][url] += base_score - 1
        for url in row["programs"] + row["evidence"]:
            host = host_of(url)
            if host and not denied_host(host):
                add_unique(row["domains"], host)

    explicit_patterns = (
        "program_crawl_batch_*.json", "program_crawl_linkoping_full.json",
        "program_crawl_psl_full.json", "program_catalog.json",
        "program_catalog_fix.json", "program_crawl_smoke.json",
    )
    seen_files = set()
    for pattern in explicit_patterns:
        for path in PW.glob(pattern):
            if path in seen_files:
                continue
            seen_files.add(path)
            for item in as_list(load(path, [])):
                ingest(item, path.name, 100)

    for path in OVERRIDE_FILES:
        for item in as_list(load(path, [])):
            ingest(item, path.name, 250)

    for filename, score in (("_crawl_progress_v2.json", 70), ("_crawl_progress.json", 35)):
        for uid, state in (load(PW / filename, {}) or {}).items():
            if isinstance(state, dict):
                ingest({"universityId": uid, **state}, filename, score)

    # Existing raw URLs are discovery seeds, not cleaned records.  Keeping
    # them ensures already fetched official pages are recaptured in the new
    # lossless corpus before any later quality decision.
    for filename in ("_programs_v2_raw.json", "_programs_all_raw.json", "_programs_raw.json"):
        for item in as_list(load(PW / filename, [])):
            if not isinstance(item, dict) or not item.get("universityId"):
                continue
            row = bucket(item["universityId"])
            source = item.get("sourceUrl") or ""
            if valid_url(source) and not denied_host(host_of(source)):
                add_unique(row["programs"], source)
                host = host_of(source)
                if host and not denied_host(host):
                    add_unique(row["domains"], host)
            add_unique(row["provenance"], filename)

    # The old queue is intentionally lowest priority because some entries are
    # admissions pages rather than programme catalogues.
    for item in as_list(load(PW / "program_crawl_queue.json", [])):
        ingest(item, "program_crawl_queue.json", 5)
    return hints


def choose_representative(group, cid):
    exact = [item for item in group if item["universityId"] == cid]
    pool = exact or group
    return max(pool, key=lambda item: (
        int(item.get("srcs") or 0),
        len(item.get("name") or ""),
        -len(item.get("universityId") or ""),
    ))


def build():
    historical = load(HISTORICAL, [])
    universities = load(DATA / "universities.json", {})
    alias_payload = load(ALIASES, {})
    aliases = alias_payload.get("canonicalById", {})
    if len(historical) != 327:
        raise RuntimeError("historical scope changed: expected 327 entries, found %d" % len(historical))

    included = [item for item in historical if item.get("universityId") not in NON_DEGREE_INSTITUTIONS]
    excluded = [item for item in historical if item.get("universityId") in NON_DEGREE_INSTITUTIONS]
    if len(included) != EXPECTED_RANKING_ENTRIES:
        raise RuntimeError("target scope changed: expected 322 entries, found %d" % len(included))

    grouped = defaultdict(list)
    for item in included:
        grouped[canonical_id(item["universityId"], aliases)].append(item)
    core_ids = set(grouped)

    current_sources = defaultdict(set)
    current_ids = set()
    for source in RANKING_SOURCES:
        for ranking in load(DATA / "rankings" / (source + ".json"), []):
            cid = canonical_id(ranking.get("universityId"), aliases)
            university = universities.get(cid)
            if not university or university.get("region") not in EUROPE or university.get("country") in EXCLUDE_COUNTRIES:
                continue
            if cid in NON_DEGREE_INSTITUTIONS or cid in SUPPLEMENTAL_NON_DEGREE_INSTITUTIONS:
                continue
            current_ids.add(cid)
            current_sources[cid].add(source)

    # Current ranking data gained Eastern Europe, Turkey, Cyprus and Malta
    # after the historical 322-entry scope was frozen.  Include those schools
    # as a supplemental superset while retaining the 322-entry core metric.
    for cid in sorted(current_ids - core_ids):
        university = universities[cid]
        grouped[cid].append({
            "universityId": cid,
            "name": university.get("name", {}).get("en", cid),
            "country": university.get("country", ""),
            "region": university.get("region", ""),
            "srcs": 0,
            "covered": False,
            "supplemental": True,
        })
    hints = read_config_hints(aliases)
    targets = []
    alias_groups = []
    for cid, group in grouped.items():
        representative = choose_representative(group, cid)
        university = universities.get(cid, {})
        display_name = repair_mojibake(university.get("name", {}).get("en") or representative["name"])
        country = university.get("country") or representative.get("country", "")
        region = university.get("region") or representative.get("region", "")
        hint = hints[cid]
        catalogs = hint["catalogs"]
        index_url = max(
            catalogs,
            key=lambda url: (hint["catalog_scores"].get(url, 0), -catalogs.index(url)),
        ) if catalogs else ""
        source_ids = [item["universityId"] for item in group]
        source_names = [repair_mojibake(item["name"]) for item in group]
        core_group = [item for item in group if not item.get("supplemental")]
        target = {
            "universityId": cid,
            "name": display_name,
            "country": country,
            "region": region,
            "scope": (["core-322"] if cid in core_ids else []) + (["current-five-rankings"] if cid in current_ids else []),
            "rankingEntryCount": len(core_group),
            "sourceUniversityIds": source_ids,
            "sourceNames": source_names,
            "rankingSourceAppearances": max(
                sum(int(item.get("srcs") or 0) for item in core_group),
                len(current_sources.get(cid, set())),
            ),
            "currentRankingSources": sorted(current_sources.get(cid, set())),
            "officialDomains": hint["domains"],
            "indexUrl": index_url,
            "catalogPages": [url for url in catalogs if url != index_url],
            "programUrls": hint["programs"],
            "evidenceUrls": hint["evidence"],
            "discoveryStrategy": "recursive-catalog",
            "hintProvenance": hint["provenance"],
        }
        targets.append(target)
        if len(core_group) > 1:
            alias_groups.append({
                "canonicalId": cid,
                "canonicalName": display_name,
                "rankingEntryCount": len(core_group),
                "sourceUniversityIds": [item["universityId"] for item in core_group],
                "sourceNames": [repair_mojibake(item["name"]) for item in core_group],
            })

    targets.sort(key=lambda item: (
        -item["rankingSourceAppearances"],
        item["country"], item["name"],
    ))
    excluded_rows = [{
        **item,
        "reason": NON_DEGREE_INSTITUTIONS[item["universityId"]],
    } for item in excluded]
    generated = datetime.now(timezone.utc).isoformat()
    audit = {
        "schemaVersion": 1,
        "generatedAt": generated,
        "source": str(HISTORICAL.relative_to(ROOT)).replace("\\", "/"),
        "historicalEntries": len(historical),
        "excludedEntries": len(excluded_rows),
        "includedRankingEntries": len(included),
        "corePhysicalUniversities": len(core_ids),
        "currentPhysicalUniversities": len(current_ids),
        "physicalUniversities": len(targets),
        "supplementalPhysicalUniversities": len(set(grouped) - core_ids),
        "aliasEntryCount": len(included) - len(core_ids),
        "aliasGroupCount": len(alias_groups),
        "expectedRankingEntries": EXPECTED_RANKING_ENTRIES,
        "countries": dict(sorted(Counter(item["country"] for item in targets).items())),
        "regions": dict(sorted(Counter(item["region"] for item in targets).items())),
        "withKnownIndexUrl": sum(bool(item["indexUrl"]) for item in targets),
        "withSeedProgramUrls": sum(bool(item["programUrls"]) for item in targets),
        "excluded": excluded_rows,
        "excludedSupplemental": [
            {"universityId": uid, "reason": reason}
            for uid, reason in sorted(SUPPLEMENTAL_NON_DEGREE_INSTITUTIONS.items())
        ],
        "aliasGroups": sorted(alias_groups, key=lambda item: (-item["rankingEntryCount"], item["canonicalName"])),
    }
    OUTPUT.write_bytes(json.dumps(targets, ensure_ascii=False, indent=2).encode("utf-8"))
    AUDIT.write_bytes(json.dumps(audit, ensure_ascii=False, indent=2).encode("utf-8"))
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    audit = build()
    print("[raw-targets] core entries=%d core universities=%d combined universities=%d aliases=%d" % (
        audit["includedRankingEntries"], audit["corePhysicalUniversities"], audit["physicalUniversities"], audit["aliasEntryCount"],
    ))
    print("[raw-targets] known index=%d seeded programme pages=%d" % (
        audit["withKnownIndexUrl"], audit["withSeedProgramUrls"],
    ))
    print("[raw-targets] -> %s" % OUTPUT)
    print("[raw-targets] -> %s" % AUDIT)


if __name__ == "__main__":
    main()
