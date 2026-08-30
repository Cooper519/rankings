"""Export raw university packages to frontend-consumable JSON.

    raw/universities/<id>/  +  legacy snapshots  ->  frontend/public/data/*.json

Input:
- raw/universities/*/manifest.json, projects.json, sources.json (contract v1)
- frontend/public/data/universities.json        (legacy base; zh names preserved)
- frontend/public/data/programs.json            (legacy curated records)
- frontend/public/data/university_aliases.json  (cross-board dedup map)
- frontend/public/data/rankings/*.json          (five board snapshots, read-only)

Output:
- universities.json, programs.json, program_coverage.json, university_aliases.json
- generated/build_report.json

Usage:
    python -m tools.build_frontend_data [--output frontend/public/data]
"""

import argparse
import calendar
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
RANKING_SOURCES = ["qs", "the", "arwu", "usnews", "csrankings"]

# Country normalisation / region mapping. Region labels must stay aligned with
# frontend/src/hooks/useData.ts EUROPE_REGIONS (the four "* Europe" values).
_COUNTRY_ALIASES = {
    "us": "United States", "usa": "United States",
    "uk": "United Kingdom", "britain": "United Kingdom",
    "uae": "United Arab Emirates", "russian federation": "Russia",
    "south korea": "Korea, South", "republic of korea": "Korea, South",
    "hong kong sar": "Hong Kong", "macao": "Macau",
    "china-taiwan": "Taiwan", "brunei": "Brunei Darussalam",
    "czech republic": "Czechia", "northern cyprus": "Cyprus", "turkiye": "Turkey",
}

_COUNTRY_TO_REGION = {}


def _fill(countries, region):
    for _c in countries:
        _COUNTRY_TO_REGION[_c] = region


_fill(["France", "Germany", "Netherlands", "Belgium", "Austria", "Switzerland",
       "Luxembourg"], "Western Europe")
_fill(["Sweden", "Norway", "Denmark", "Finland", "Iceland", "Ireland", "Estonia",
       "Latvia", "Lithuania"], "Northern Europe")
_fill(["Italy", "Spain", "Portugal", "Greece", "Cyprus", "Malta", "Slovenia",
       "Croatia", "Serbia"], "Southern Europe")
_fill(["Poland", "Czechia", "Hungary", "Romania", "Bulgaria", "Slovakia", "Ukraine",
       "Russia"], "Eastern Europe")
_fill(["United States", "Canada"], "North America")
_fill(["Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Peru", "Costa Rica"], "Latin America")
_fill(["United Kingdom"], "United Kingdom")
_fill(["Australia", "New Zealand"], "Oceania")
_fill(["China", "Hong Kong", "Macau", "Taiwan"], "China")
_fill(["Turkey", "Israel", "Saudi Arabia", "United Arab Emirates", "Qatar", "Jordan",
       "Lebanon", "Oman", "Bahrain", "Egypt", "Iran", "Iraq", "Kuwait", "Morocco"], "Middle East")
_fill(["Japan", "Korea, South", "Singapore", "India", "Malaysia", "Thailand", "Indonesia",
       "Pakistan", "Vietnam", "Philippines", "Kazakhstan", "Uzbekistan", "Brunei Darussalam",
       "Bangladesh", "Sri Lanka"], "Asia")
_fill(["South Africa", "Ghana", "Nigeria", "Kenya"], "Africa")


def normalize_country(value):
    v = (value or "").strip()
    return _COUNTRY_ALIASES.get(v.lower(), v) if v else ""


def region_for(country):
    return _COUNTRY_TO_REGION.get(country, "Other")


_STOP_WORDS = ("the|of|university|universite|universitat|universidad|institute|technology"
               "|technische|technical|royal|school")


def normalize_name(name):
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"\s*\(.*?\)\s*", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\b(" + _STOP_WORDS + r")\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def read_json(path, default):
    try:
        with open(str(path), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def atomic_write_json(path, data):
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, str(path))


def month_end(iso_month):
    year, month = (int(p) for p in iso_month.split("-"))
    return "%s-%02d" % (iso_month, calendar.monthrange(year, month)[1])


def map_applicant_group(value):
    v = (value or "").strip().lower()
    if not v or v == "all":
        return "All"
    if v.replace("-", "_") == "non_eu":
        return "Non-EU"
    if v == "eu":
        return "EU"
    return "Unknown"


_EVENT_WINDOW = ("open", "start", "window", "round")


def _deadline_entry(tl, use_end):
    date_type = tl.get("date_type")
    date = tl.get("date")
    date_end = tl.get("date_end")
    out = None
    if date_type == "exact" and date:
        out = date
    elif date_type == "month" and date:
        out = month_end(date) if "-" in date else None
    elif date_type == "range":
        out = date_end if (use_end and date_end) else date
    if not out:
        return None
    return {
        "round": tl.get("round") or "Regular",
        "date": out,
        "applicantGroup": map_applicant_group(tl.get("applicant_group")),
    }


def _test_text(block, label):
    if not isinstance(block, dict):
        return None
    status = block.get("status")
    score = block.get("min_score")
    if status in ("required", "optional") and score:
        suffix = "required" if status == "required" else "recommended"
        return "%s %s (%s)" % (label, score, suffix)
    if status == "required":
        return "%s required" % label
    return None


def build_requirements(req):
    req = req or {}
    language = req.get("language") or {}
    academic = req.get("academic") or {}
    ielts = toefl = None
    others = []
    for test in language.get("tests") or []:
        name = (test.get("name") or "").strip()
        score = (test.get("min_score") or "").strip()
        if not name or not score:
            continue
        low = name.lower()
        if "ielts" in low and ielts is None:
            ielts = score
        elif "toefl" in low and toefl is None:
            toefl = score
        else:
            others.append("%s %s" % (name, score))
    return {
        "gpa": None,
        "ielts": ielts,
        "toefl": toefl,
        "gre": _test_text(req.get("gre"), "GRE"),
        "gmat": _test_text(req.get("gmat"), "GMAT"),
        "language": " / ".join(others) if others else None,
        "academic": academic.get("description") if academic.get("status") in ("required", "optional") else None,
    }


def _all_verified(statuses):
    return bool(statuses) and all(s == "verified" for s in statuses)


def _dedupe_rows(rows):
    seen, out = set(), []
    for row in rows:
        key = (row["date"], row["round"], row["applicantGroup"])
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def build_program_from_raw(project, sources_by_id, updated_at):
    if project.get("status") not in (None, "active"):
        return None
    deadlines, windows, fees = [], [], []
    requirements = {"gpa": None, "ielts": None, "toefl": None, "gre": None, "gmat": None,
                    "language": None, "academic": None}
    cycle_statuses, timeline_statuses, source_urls = [], [], []
    for cycle in project.get("admission_cycles") or []:
        if cycle.get("status") == "historical":
            continue
        cycle_statuses.append(cycle.get("verification_status"))
        for tag in (cycle.get("source_id"),):
            if tag in sources_by_id:
                source_urls.append(sources_by_id[tag].get("url"))
        for tl in cycle.get("timelines") or []:
            timeline_statuses.append(tl.get("verification_status"))
            sid = tl.get("source_id")
            if sid in sources_by_id:
                source_urls.append(sources_by_id[sid].get("url"))
            event = (tl.get("event") or "").lower()
            if "deadline" in event:
                entry = _deadline_entry(tl, use_end=True)
                if entry:
                    deadlines.append(entry)
            elif any(k in event for k in _EVENT_WINDOW) and tl.get("date_type") in ("exact", "range"):
                entry = _deadline_entry(tl, use_end=False)
                if entry:
                    windows.append(entry)
        cycle_req = build_requirements(cycle.get("requirements") or {})
        for key, value in cycle_req.items():
            if not requirements.get(key) and value:
                requirements[key] = value
        for fee in cycle.get("fees") or []:
            amount = fee.get("amount")
            fees.append({
                "type": fee.get("type"),
                "amount": None if amount == "unknown" else amount,
                "currency": fee.get("currency"),
                "period": fee.get("period"),
                "applicantGroup": map_applicant_group(fee.get("applicant_group")),
            })
    deadlines = _dedupe_rows(deadlines)
    deadlines.sort(key=lambda d: d["date"])
    windows = _dedupe_rows(windows)
    verified = _all_verified([project.get("verification_status")] + cycle_statuses)
    return {
        "id": project["project_id"],
        "universityId": project["university_id"],
        "subject": project.get("subject") or "General",
        "dept": project.get("department") or "",
        "program": project.get("name"),
        "deadlines": deadlines,
        "materials": [],
        "requirements": requirements,
        "fees": fees,
        "sourceUrl": project.get("official_url"),
        "verified": verified,
        "updatedAt": updated_at or datetime.now(timezone.utc).date().isoformat(),
        "deadlineReviewed": bool(deadlines) and _all_verified(timeline_statuses),
        "evidenceUrls": sorted({u for u in source_urls if u}),
        "applicationWindows": windows,
    }


def has_any_requirement(record):
    return any((record.get("requirements") or {}).values())


def run(root, out_dir):
    raw_dir = root / "raw" / "universities"
    data_dir = root / "frontend" / "public" / "data"
    generated_dir = root / "generated"

    universities = read_json(data_dir / "universities.json", {})
    legacy_programs = read_json(data_dir / "programs.json", [])
    aliases = read_json(data_dir / "university_aliases.json", {"version": 1, "canonicalById": {}})
    canonical_by_id = dict(aliases.get("canonicalById") or {})
    reason_by_id = dict(aliases.get("reasonById") or {})

    packages = []
    warnings = []
    if raw_dir.is_dir():
        for uid in sorted(os.listdir(str(raw_dir))):
            pkg_dir = raw_dir / uid
            if not pkg_dir.is_dir():
                continue
            manifest = read_json(pkg_dir / "manifest.json", None)
            projects = read_json(pkg_dir / "projects.json", [])
            sources = read_json(pkg_dir / "sources.json", [])
            if manifest is None:
                warnings.append("%s: missing or unreadable manifest.json" % uid)
                manifest = {"university_id": uid, "name": uid, "country": "", "updated_at": ""}
            packages.append((uid, manifest, projects or [],
                             dict((s.get("source_id"), s) for s in (sources or []))))

    # merge universities
    for uid, manifest, projects, sources_by_id in packages:
        entry = universities.get(uid)
        if entry is None:
            entry = {"id": uid, "name": {"en": manifest.get("name") or uid},
                     "country": "", "region": "", "website": "", "subjects": [], "sources": []}
            universities[uid] = entry
        country = normalize_country(manifest.get("country") or entry.get("country") or "")
        if country:
            entry["country"] = country
        if manifest.get("region"):
            entry["region"] = manifest["region"]
        elif not entry.get("region") or entry.get("region") == "Other":
            entry["region"] = region_for(entry["country"])
        if not entry.get("website") and manifest.get("website"):
            entry["website"] = manifest["website"]
        canonical_by_id.setdefault(uid, uid)

    # programs
    raw_programs = []
    for uid, manifest, projects, sources_by_id in packages:
        updated_at = (manifest.get("updated_at") or "")[:10]
        for project in projects:
            record = build_program_from_raw(project, sources_by_id, updated_at)
            if record and record.get("program"):
                raw_programs.append(record)

    merged = []
    raw_keys = set()
    for record in raw_programs:
        key = (canonical_by_id.get(record["universityId"], record["universityId"]),
               normalize_name(record["program"]))
        raw_keys.add(key)
        merged.append(record)
    legacy_kept = 0
    for legacy in legacy_programs:
        cid = canonical_by_id.get(legacy.get("universityId"), legacy.get("universityId"))
        key = (cid, normalize_name(legacy.get("program") or ""))
        if key not in raw_keys:
            merged.append(legacy)
            legacy_kept += 1

    # subjects on universities
    subjects_by_uni = {}
    for record in merged:
        if record.get("subject") and record["subject"] != "General":
            subjects_by_uni.setdefault(record["universityId"], set()).add(record["subject"])
    for uid, subjects in subjects_by_uni.items():
        entry = universities.get(uid)
        if entry is not None:
            entry["subjects"] = sorted(set(entry.get("subjects") or []) | subjects)

    # ranking sources per university
    rankings = dict((src, read_json(data_dir / "rankings" / (src + ".json"), [])) for src in RANKING_SOURCES)
    ranked = {}
    for src, rows in rankings.items():
        for entry in rows:
            cid = canonical_by_id.get(entry.get("universityId"), entry.get("universityId"))
            ranked.setdefault(cid, set()).add(src)
    for uid, entry in universities.items():
        entry["sources"] = sorted(ranked.get(canonical_by_id.get(uid, uid), set()))

    # aliases: identity for every id we expose
    for uid in universities:
        canonical_by_id.setdefault(uid, uid)
    for src, rows in rankings.items():
        for entry in rows:
            canonical_by_id.setdefault(entry.get("universityId"), entry.get("universityId"))
    aliases_out = {
        "version": int(aliases.get("version") or 1) + 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "canonicalById": canonical_by_id,
        "reasonById": reason_by_id,
    }

    # coverage
    by_uni = {}
    for record in merged:
        cid = canonical_by_id.get(record["universityId"], record["universityId"])
        by_uni.setdefault(cid, []).append(record)
    today = datetime.now(timezone.utc).date().isoformat()
    coverage = []
    for uid, entry in sorted(universities.items()):
        cid = canonical_by_id.get(uid, uid)
        progs = by_uni.get(cid, [])
        deadline_count = sum(1 for p in progs if p.get("deadlines"))
        req_count = sum(1 for p in progs if has_any_requirement(p))
        verified_count = sum(1 for p in progs if p.get("verified"))
        if not progs:
            status, completeness = "pending", 0
        else:
            completeness = round(sum(
                (40 if p.get("deadlines") else 0)
                + (40 if has_any_requirement(p) else 0)
                + (20 if p.get("verified") else 0) for p in progs) / len(progs))
            status = "verified" if verified_count and verified_count == len(progs) else (
                "extracted" if (deadline_count or req_count) else "partial")
        website = entry.get("website") or ""
        host = urlparse(website).netloc if website.startswith("http") else ""
        coverage.append({
            "universityId": uid,
            "name": (entry.get("name") or {}).get("en", uid),
            "country": entry.get("country", ""),
            "region": entry.get("region", ""),
            "status": status,
            "programCount": len(progs),
            "deadlineCount": deadline_count,
            "requirementCount": req_count,
            "verifiedCount": verified_count,
            "completeness": completeness,
            "officialDomains": [host] if host else [],
            "indexUrl": website,
            "updatedAt": today,
        })

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out_dir / "universities.json", universities)
    atomic_write_json(out_dir / "programs.json", merged)
    atomic_write_json(out_dir / "program_coverage.json", coverage)
    atomic_write_json(out_dir / "university_aliases.json", aliases_out)

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "packagesTotal": len(packages),
        "packagesWithProjects": sum(1 for _u, _m, ps, _s in packages if ps),
        "programsFromRaw": len(raw_programs),
        "legacyProgramsKept": legacy_kept,
        "programsTotal": len(merged),
        "programsWithDeadline": sum(1 for p in merged if p.get("deadlines")),
        "programsWithRequirement": sum(1 for p in merged if has_any_requirement(p)),
        "programsVerified": sum(1 for p in merged if p.get("verified")),
        "universitiesTotal": len(universities),
        "warnings": warnings,
    }
    atomic_write_json(generated_dir / "build_report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Export raw packages to frontend JSON.")
    parser.add_argument("--output", type=Path, default=None,
                        help="output dir for frontend JSON (default: frontend/public/data)")
    args = parser.parse_args()
    out_dir = args.output or (ROOT / "frontend" / "public" / "data")
    report = run(ROOT, out_dir)
    print("build_frontend_data report:")
    for key, value in report.items():
        if key != "warnings":
            print("  %s: %s" % (key, value))
    if report["warnings"]:
        print("  warnings (%d):" % len(report["warnings"]))
        for w in report["warnings"][:20]:
            print("    - %s" % w)


if __name__ == "__main__":
    main()
