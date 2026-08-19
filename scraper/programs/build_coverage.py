"""Build program-data coverage records and a prioritized crawl queue."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "frontend" / "public" / "data"
PW = ROOT / "scraper" / "playwright"
SOURCES = ("qs", "the", "arwu", "usnews", "csrankings")
EUROPE = {"Western Europe", "Northern Europe", "Southern Europe", "Eastern Europe"}
EXCLUDE_COUNTRIES = {"United Kingdom", "Ireland"}
DENY_HOSTS = {
    "wikipedia.org", "mastersportal.com", "studyportals.com", "study.eu",
    "findamasters.com", "masterstudies.com", "university-directory.eu",
    "globaladmissions.com", "collegelearners.org", "mygermanuniversity.com",
    "topuniversities.com", "timeshighereducation.com", "usnews.com",
    "globalstudyprep.com", "mastermania.com", "standyou.com", "goaustria.org",
}


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def host_of(url):
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def denied(host):
    return any(host == d or host.endswith("." + d) for d in DENY_HOSTS)


def main():
    universities = load(DATA / "universities.json", {})
    programs = load(DATA / "programs.json", [])
    alias_data = load(DATA / "university_aliases.json", {"canonicalById": {}})
    canonical_by_id = alias_data.get("canonicalById", {})
    progress_v1 = load(PW / "_crawl_progress.json", {})
    progress_v2 = load(PW / "_crawl_progress_v2.json", {})

    def canonical(uid):
        return canonical_by_id.get(uid, uid)

    ranked_sources = defaultdict(set)
    best_rank = defaultdict(lambda: 99999)
    for source in SOURCES:
        for row in load(DATA / "rankings" / (source + ".json"), []):
            cid = canonical(row.get("universityId"))
            ranked_sources[cid].add(source)
            best_rank[cid] = min(best_rank[cid], int(row.get("rank") or 99999))

    by_uni = defaultdict(list)
    for program in programs:
        by_uni[canonical(program.get("universityId"))].append(program)

    host_votes = defaultdict(Counter)
    catalog_urls = defaultdict(list)
    for program in programs:
        cid = canonical(program.get("universityId"))
        host = host_of(program.get("sourceUrl", ""))
        if host and not denied(host):
            host_votes[cid][host] += 5 if program.get("verified") else 1
    for progress, weight in ((progress_v1, 1), (progress_v2, 4)):
        for uid, state in progress.items():
            cid = canonical(uid)
            url = state.get("catalogUrl") or state.get("listHref") or ""
            host = host_of(url)
            if url and host and not denied(host):
                catalog_urls[cid].append((weight, url))
                host_votes[cid][host] += weight

    canonical_ids = sorted(set(canonical(uid) for uid in universities))
    rows = []
    queue = []
    for cid in canonical_ids:
        uni = universities.get(cid)
        if not uni:
            continue
        is_target = uni.get("region") in EUROPE and uni.get("country") not in EXCLUDE_COUNTRIES
        if not is_target or cid not in ranked_sources:
            continue
        records = by_uni.get(cid, [])
        program_count = len(records)
        deadline_count = sum(1 for p in records if p.get("deadlines"))
        requirement_count = sum(1 for p in records if any((p.get("requirements") or {}).get(k) for k in ("gpa", "ielts", "toefl", "language", "academic")))
        verified_count = sum(1 for p in records if p.get("verified"))
        official_domains = [h for h, _ in host_votes[cid].most_common(3)]
        index_url = max(catalog_urls[cid], key=lambda item: item[0])[1] if catalog_urls[cid] else ""

        if program_count == 0:
            status = "pending"
        elif deadline_count == 0 or requirement_count == 0:
            status = "partial"
        elif verified_count == program_count:
            status = "verified"
        else:
            status = "extracted"
        completeness = round((
            min(program_count / 6.0, 1.0) * 0.35 +
            (deadline_count / max(program_count, 1)) * 0.25 +
            (requirement_count / max(program_count, 1)) * 0.25 +
            (verified_count / max(program_count, 1)) * 0.15
        ) * 100)
        priority = (
            (100 if program_count == 0 else 30) +
            (40 if deadline_count == 0 else 0) +
            (30 if requirement_count == 0 else 0) +
            len(ranked_sources[cid]) * 8 +
            max(0, 20 - best_rank[cid] // 25)
        )
        row = {
            "universityId": cid,
            "name": uni["name"]["en"],
            "country": uni.get("country", ""),
            "region": uni.get("region", ""),
            "status": status,
            "programCount": program_count,
            "deadlineCount": deadline_count,
            "requirementCount": requirement_count,
            "verifiedCount": verified_count,
            "completeness": completeness,
            "rankingSources": sorted(ranked_sources[cid]),
            "bestRank": best_rank[cid],
            "officialDomains": official_domains,
            "indexUrl": index_url,
            "priority": priority,
            "updatedAt": date.today().isoformat(),
        }
        rows.append(row)
        if status in {"pending", "partial"}:
            queue.append({
                "universityId": cid,
                "name": row["name"],
                "country": row["country"],
                "region": row["region"],
                "officialDomains": official_domains,
                "indexUrl": index_url,
                "priority": priority,
                "reason": "missing-programs" if program_count == 0 else "missing-application-fields",
            })

    rows.sort(key=lambda x: (-x["priority"], x["name"]))
    queue.sort(key=lambda x: (-x["priority"], x["name"]))
    (DATA / "program_coverage.json").write_bytes(json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8"))
    (PW / "program_crawl_queue.json").write_bytes(json.dumps(queue, ensure_ascii=False, indent=2).encode("utf-8"))
    missing_queue = [item for item in queue if item["reason"] == "missing-programs"]
    (PW / "program_crawl_missing.json").write_bytes(json.dumps(missing_queue, ensure_ascii=False, indent=2).encode("utf-8"))
    statuses = Counter(row["status"] for row in rows)
    print("[coverage] targets=%d queue=%d statuses=%s" % (len(rows), len(queue), dict(statuses)))
    print("[coverage] -> %s" % (DATA / "program_coverage.json"))
    print("[coverage] -> %s" % (PW / "program_crawl_queue.json"))
    print("[coverage] missing-programs=%d -> %s" % (len(missing_queue), PW / "program_crawl_missing.json"))


if __name__ == "__main__":
    main()
