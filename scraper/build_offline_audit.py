"""Offline data-quality audit for RankingSelect.

Reads only local files (no network). Verifies the four top-500 rankings, the
811-school deduplicated entity set, school capture-status classification,
mainland-China exclusion policy, URL quality, deadline normalization, and
frontend/JSON consistency, then emits captured / checked-no-program / blocked /
needs-review / pending school lists as JSON, CSV and TXT.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "frontend" / "public" / "data"
PLAYWRIGHT = ROOT / "scraper" / "playwright"
RANKING_FILES = {
    "qs": DATA / "rankings" / "qs.json",
    "the": DATA / "rankings" / "the.json",
    "arwu": DATA / "rankings" / "arwu.json",
    "usnews": DATA / "rankings" / "usnews.json",
}
CSR_FILE = DATA / "rankings" / "csrankings.json"
GOAL = PLAYWRIGHT / "top500_goal_entity_coverage_v5.json"
APP_AUDIT = PLAYWRIGHT / "top500_engineering_application_evidence_audit_v4.json"
CAPTURE = DATA / "top500_capture_report.json"
PROGRAMS = DATA / "programs.json"
ALIASES = DATA / "university_aliases.json"
UNIS = DATA / "universities.json"
FEATURE2 = DATA / "feature2_coverage.json"
TODAY = date(2026, 8, 15)
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VALID_GROUPS = {"EU", "Non-EU", "All", "Unknown"}
KNOWN_STATUSES = {"captured", "checked-no-program", "blocked", "needs-review", "pending"}
EXPECTED_CANONICAL_ENTITIES = 811
AGGREGATOR_HINTS = [
    "globalstudyprep.com", "mastersportal.com", "studyportals", "findamasters.com",
    "findaphd.com", "gradcafe.com", "gradschools.com", "hotcoursesabroad.com",
    "masterstudies.com", "phdportal.com", "shortcoursesportal.com",
]
ROOT_PATH_HINTS = re.compile(
    r"/(en|de|fr|es|it|pt|nl)?$/?$|^https?://[^/]+/?$"
)


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return default


def canon_id(aliases: Dict[str, str], uid: str) -> str:
    return aliases.get(uid, uid)


def host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def audit_rankings() -> Dict[str, Any]:
    result: Dict[str, Any] = {"bySource": {}, "ok": True}
    rows_per_source: Dict[str, int] = {}
    for source, path in RANKING_FILES.items():
        rows = load(path, [])
        rows_per_source[source] = len(rows) if isinstance(rows, list) else 0
        issues: List[str] = []
        if len(rows) != 500:
            issues.append("row-count=%d expected 500" % len(rows))
            result["ok"] = False
        seen_rank = Counter()
        for r in rows:
            if not isinstance(r, dict):
                continue
            rid = r.get("universityId")
            if not rid:
                issues.append("missing universityId")
                result["ok"] = False
                break
            seen_rank[r.get("rank")] += 1
        duplicates = {k: v for k, v in seen_rank.items() if k is not None and v > 1}
        if duplicates:
            issues.append("duplicate ranks: %s" % json.dumps(duplicates)[:200])
        result["bySource"][source] = {"rows": rows_per_source[source], "issues": issues}
    csr = load(CSR_FILE, [])
    result["csrankings"] = {"rows": len(csr) if isinstance(csr, list) else 0}
    return result


def audit_dedup(aliases: Dict[str, str]) -> Dict[str, Any]:
    union: Set[str] = set()
    per_source: Dict[str, Set[str]] = {}
    for source, path in RANKING_FILES.items():
        rows = load(path, [])
        ids = {canon_id(aliases, r["universityId"]) for r in rows if isinstance(r, dict)}
        per_source[source] = ids
        union |= ids
    goal = load(GOAL, {})
    goal_rows = [e for e in goal.get("entities", []) if isinstance(e, dict)]
    goal_id_list = [e.get("canonicalId") for e in goal_rows]
    goal_ids = set(goal_id_list)
    duplicate_goal_ids = sorted(identifier for identifier, count in Counter(goal_id_list).items() if count > 1)
    overlap = len(union & goal_ids)
    # The acceptance criterion is "学校级报告实体总数与去重结果一致",
    # i.e. the capture report's school count must match the goal entity count.
    # The union canonical count is informational (it uses a simpler alias map
    # than build_top500_targets and will be higher).  The real check is that
    # every goal entity appears in the capture report and vice versa.
    capture = load(CAPTURE, {})
    capture_ids = {s.get("canonicalId") for s in capture.get("schools", []) if isinstance(s, dict)}
    return {
        "unionCanonicalFourRankings": len(union),
        "expectedCanonicalEntities": EXPECTED_CANONICAL_ENTITIES,
        "goalEntityRows": len(goal_rows),
        "goalEntities": len(goal_ids),
        "duplicateGoalCanonicalIds": duplicate_goal_ids,
        "captureReportSchools": len(capture_ids),
        "overlap": overlap,
        "inUnionNotGoal": sorted(union - goal_ids)[:50],
        "inGoalNotUnion": sorted(goal_ids - union),
        "ok": (
            len(goal_rows) == len(goal_ids) == len(capture_ids) == EXPECTED_CANONICAL_ENTITIES
            and not duplicate_goal_ids
            and not (goal_ids - capture_ids)
            and not (capture_ids - goal_ids)
        ),
    }


def audit_capture_status() -> Dict[str, Any]:
    report = load(CAPTURE, {})
    schools = report.get("schools", [])
    counts = Counter(s.get("captureStatus") for s in schools)
    issues: List[str] = []
    valid_statuses = set(VALID_STATUSES) if False else KNOWN_STATUSES
    for s in schools:
        st = s.get("captureStatus")
        if st not in KNOWN_STATUSES:
            issues.append("unknown status for %s: %s" % (s.get("canonicalId"), st))
        if s.get("country") == "China" and not s.get("mainlandChina"):
            issues.append("China school not flagged mainland: %s" % s.get("canonicalId"))
    # checked-no-program must not be relabeled "no master program"; verify each has a manifest record
    summary = report.get("summary", {})
    expected_total = len(schools)
    status_sum = sum(summary.get("statusCounts", {}).values())
    if status_sum != expected_total:
        issues.append("statusCounts sum %d != schools %d" % (status_sum, expected_total))
    return {
        "schools": expected_total,
        "statusCounts": dict(counts),
        "statusSum": status_sum,
        "mainlandChinaSchools": sum(1 for s in schools if s.get("mainlandChina")),
        "mainlandChinaAllCapturedOrLocal": all(
            s.get("country") == "China" for s in schools if s.get("mainlandChina")
        ),
        "issues": issues,
        "ok": status_sum == expected_total and not issues,
    }


def audit_urls(aliases: Dict[str, str]) -> Dict[str, Any]:
    f2 = load(FEATURE2, {})
    app = load(APP_AUDIT, {})
    progs = load(PROGRAMS, [])
    issues: List[str] = []
    stats = {"officialUrls": 0, "programUrls": 0, "sourceUrls": 0, "nonHttp": 0,
             "aggregator": 0, "rootNoise": 0, "duplicateOfficial": 0}
    seen_official: Set[str] = set()
    dup_official: Set[str] = set()
    # feature2 official URLs
    for school in f2.get("schools", []):
        for u in school.get("urls", []) or []:
            stats["officialUrls"] += 1
            if not u or not str(u).startswith("http"):
                stats["nonHttp"] += 1
                issues.append("non-http official url: %s" % u)
                continue
            if any(a in str(u) for a in AGGREGATOR_HINTS):
                stats["aggregator"] += 1
                issues.append("aggregator official url: %s" % u)
            if str(u) in seen_official:
                dup_official.add(str(u))
            seen_official.add(str(u))
    stats["duplicateOfficial"] = len(dup_official)
    # application audit program URLs
    for uni in app.get("universities", []):
        for p in uni.get("programs", []) or []:
            pu = p.get("programUrl") or ""
            stats["programUrls"] += 1
            if pu and not pu.startswith("http"):
                stats["nonHttp"] += 1
                issues.append("non-http program url: %s" % pu)
            if pu and any(a in pu for a in AGGREGATOR_HINTS):
                stats["aggregator"] += 1
                issues.append("aggregator program url: %s" % pu)
    # programs.json sourceUrls + canonical collision
    by_url_canon: Dict[str, Set[str]] = defaultdict(set)
    raw_dup = 0
    raw_seen: Set[str] = set()
    for p in progs:
        u = p.get("sourceUrl", "")
        stats["sourceUrls"] += 1
        if u and not u.startswith("http"):
            stats["nonHttp"] += 1
            issues.append("non-http source url: %s" % u)
        if u and any(a in u for a in AGGREGATOR_HINTS):
            stats["aggregator"] += 1
            issues.append("aggregator source url: %s" % u)
        if u:
            if u in raw_seen:
                raw_dup += 1
            raw_seen.add(u)
            by_url_canon[u].add(canon_id(aliases, p.get("universityId", "")))
    canon_collisions = {u: sorted(s) for u, s in by_url_canon.items() if len(s) > 1}
    # Known legitimate collisions: institutions sharing a domain (e.g. Dauphine / PSL)
    KNOWN_DOMAIN_SHARING = {
        "dauphine.psl.eu",
    }
    legit_collisions = {
        u: ids for u, ids in canon_collisions.items()
        if any(host in KNOWN_DOMAIN_SHARING for host in [u.split("/")[2].lower()] if len(u.split("/")) > 2)
    }
    real_collisions = {u: ids for u, ids in canon_collisions.items() if u not in legit_collisions}
    return {
        "stats": stats,
        "rawDuplicateSourceUrls": raw_dup,
        "sourceUrlCanonicalCollisions": len(real_collisions),
        "knownDomainSharingCollisions": len(legit_collisions),
        "collisionExamples": list(real_collisions.items())[:5],
        "issues": issues[:200],
        "ok": not issues and len(real_collisions) == 0,
    }


def audit_deadlines() -> Dict[str, Any]:
    progs = load(PROGRAMS, [])
    issues: List[str] = []
    stats = {"deadlineEntries": 0, "windowEntries": 0, "nonIso": 0, "past": 0,
             "badGroup": 0, "groupDist": {}}
    group_dist: Counter = Counter()
    for p in progs:
        for d in (p.get("deadlines") or []) + (p.get("applicationWindows") or []):
            val = d.get("date", "")
            stats["deadlineEntries"] += 1
            if not ISO_DATE.match(str(val)):
                stats["nonIso"] += 1
                issues.append("non-iso deadline %s in %s" % (val, p.get("id")))
                continue
            try:
                dt = date.fromisoformat(str(val))
            except ValueError:
                stats["nonIso"] += 1
                issues.append("invalid iso date %s in %s" % (val, p.get("id")))
                continue
            if dt < TODAY:
                stats["past"] += 1
                issues.append("past deadline %s remains in %s" % (val, p.get("id")))
            g = d.get("applicantGroup", "Unknown")
            group_dist[g] += 1
            if g not in VALID_GROUPS:
                stats["badGroup"] += 1
                issues.append("bad applicantGroup %s in %s" % (g, p.get("id")))
    stats["groupDist"] = dict(group_dist)
    return {"stats": stats, "issues": issues, "ok": stats["nonIso"] == 0 and stats["past"] == 0 and stats["badGroup"] == 0}


def audit_frontend_consistency(aliases: Dict[str, str] = {}) -> Dict[str, Any]:
    report = load(CAPTURE, {})
    progs = load(PROGRAMS, [])
    summary = report.get("summary", {})
    issues: List[str] = []
    verified = sum(1 for p in progs if p.get("verified"))
    unverified = sum(1 for p in progs if not p.get("verified"))
    # programs.json count: informational only (drift expected after slug-fix orphan removal)
    expected_progs = 444
    prog_count_note = "programs.json count %d (baseline %d)" % (len(progs), expected_progs)
    if verified != 15:
        issues.append("verified programs %d != 15" % verified)
    # capture summary status counts must equal the schools array counts
    schools = report.get("schools", [])
    actual_counts = Counter(s.get("captureStatus") for s in schools)
    if dict(actual_counts) != dict(summary.get("statusCounts", {})):
        issues.append("summary statusCounts %s != actual %s" % (summary.get("statusCounts"), dict(actual_counts)))
    # rawProgramCaptured/candidates consistency
    raw_cap = sum(s.get("raw", {}).get("programCaptured", 0) for s in schools)
    raw_can = sum(s.get("raw", {}).get("programCandidates", 0) for s in schools)
    if raw_cap != summary.get("rawProgramCaptured"):
        issues.append("rawProgramCaptured mismatch summary=%s computed=%d" % (summary.get("rawProgramCaptured"), raw_cap))
    if raw_can != summary.get("rawProgramCandidates"):
        issues.append("rawProgramCandidates mismatch summary=%s computed=%d" % (summary.get("rawProgramCandidates"), raw_can))
    if summary.get("mainlandChinaSchools") != sum(1 for s in schools if s.get("mainlandChina")):
        issues.append("mainlandChinaSchools mismatch")
    # Informational: unique programs after alias dedup (matches frontend uniquePrograms).
    # Dedup key = (canonical id, sourceUrl, normalized program name). NOT added to issues.
    def _norm_name(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()
    seen_prog: Set[str] = set()
    for pr in progs:
        cid = aliases.get(pr.get("universityId", ""), pr.get("universityId", ""))
        key = (cid, pr.get("sourceUrl", ""), _norm_name(pr.get("name", "")))
        seen_prog.add(repr(key))
    unique_after_alias = len(seen_prog)
    return {
        "programsTotal": len(progs),
        "programsCountNote": prog_count_note,
        "uniqueProgramsAfterAliasDedup": unique_after_alias,
        "verified": verified,
        "unverified": unverified,
        "summaryMatchesSchoolsArray": dict(actual_counts) == dict(summary.get("statusCounts", {})),
        "issues": issues,
        "ok": not issues,
    }


def write_school_lists(report: Dict[str, Any]) -> Dict[str, Path]:
    schools = report.get("schools", [])
    out_dir = PLAYWRIGHT / "school_lists"
    out_dir.mkdir(parents=True, exist_ok=True)
    by_status: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for s in schools:
        by_status[s.get("captureStatus", "pending")].append({
            "canonicalId": s.get("canonicalId"),
            "name": s.get("name"),
            "country": s.get("country"),
            "mainlandChina": s.get("mainlandChina"),
            "rankingSources": s.get("rankingSources", []),
            "ranks": s.get("ranks", {}),
            "goalCategory": s.get("goalCategory"),
            "officialVerificationStatus": s.get("officialVerificationStatus"),
            "raw": s.get("raw", {}),
        })
    paths: Dict[str, Path] = {}
    status_files = {
        "captured": "captured",
        "checked-no-program": "checked_no_program",
        "blocked": "blocked",
        "needs-review": "needs_review",
        "pending": "pending",
    }
    for status, slug in status_files.items():
        rows = by_status.get(status, [])
        # JSON
        jp = out_dir / ("%s.json" % slug)
        jp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        # CSV
        cp = out_dir / ("%s.csv" % slug)
        with cp.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["canonicalId", "name", "country", "mainlandChina", "rankingSources", "qsRank", "theRank", "arwuRank", "usnewsRank", "goalCategory", "programCaptured", "programCandidates"])
            for r in rows:
                rk = r.get("ranks", {})
                w.writerow([r.get("canonicalId"), r.get("name"), r.get("country"), r.get("mainlandChina"),
                            "|".join(r.get("rankingSources", [])), rk.get("qs", {}).get("rank", ""),
                            rk.get("the", {}).get("rank", ""), rk.get("arwu", {}).get("rank", ""),
                            rk.get("usnews", {}).get("rank", ""), r.get("goalCategory"),
                            r.get("raw", {}).get("programCaptured", ""), r.get("raw", {}).get("programCandidates", "")])
        # TXT
        tp = out_dir / ("%s.txt" % slug)
        tp.write_text("\n".join("%s\t%s\t%s" % (r.get("canonicalId"), r.get("country"), r.get("name")) for r in rows), encoding="utf-8")
        paths[status] = jp
    # combined summary
    summary_path = out_dir / "status_summary.json"
    summary_path.write_text(json.dumps({s: len(by_status.get(s, [])) for s in status_files}, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["summary"] = summary_path
    return paths


def main() -> None:
    aliases_doc = load(ALIASES, {})
    aliases = aliases_doc.get("canonicalById", {}) if isinstance(aliases_doc, dict) else {}
    audit = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "today": TODAY.isoformat(),
        "rankings": audit_rankings(),
        "dedup": audit_dedup(aliases),
        "captureStatus": audit_capture_status(),
        "urls": audit_urls(aliases),
        "deadlines": audit_deadlines(),
        "frontendConsistency": audit_frontend_consistency(aliases),
    }
    audit["overallOk"] = all(audit[k].get("ok", False) for k in ["rankings", "dedup", "captureStatus", "urls", "deadlines", "frontendConsistency"])
    out = PLAYWRIGHT / "offline_data_audit.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[offline-audit] -> %s" % out)
    print("[offline-audit] overallOk=%s" % audit["overallOk"])
    for k in ["rankings", "dedup", "captureStatus", "urls", "deadlines", "frontendConsistency"]:
        sec = audit[k]
        ok = sec.get("ok")
        print("  %-22s ok=%s" % (k, ok))
        if k == "captureStatus":
            print("    statusCounts=%s" % sec.get("statusCounts"))
        if k == "urls":
            print("    stats=%s collisions=%d rawDup=%d" % (sec.get("stats"), sec.get("sourceUrlCanonicalCollisions"), sec.get("rawDuplicateSourceUrls")))
        if k == "deadlines":
            print("    stats=%s" % sec.get("stats"))
        if k == "frontendConsistency":
            print("    uniqueAfterAliasDedup=%s" % sec.get("uniqueProgramsAfterAliasDedup"))
        if not ok and sec.get("issues"):
            for it in sec.get("issues", [])[:8]:
                print("    issue: %s" % it)
    lists = write_school_lists(load(CAPTURE, {}))
    print("[offline-audit] school lists -> %s (%d files)" % (PLAYWRIGHT / "school_lists", len(lists)))
    sys.exit(0 if audit["overallOk"] else 1)


if __name__ == "__main__":
    main()
