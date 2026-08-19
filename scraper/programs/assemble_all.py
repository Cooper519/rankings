"""Merge full crawler output (_programs_all_raw.json) + L2 fix output (_programs_raw.json)
into frontend/public/data/programs.json.

Strategy:
  - base = existing programs.json (seed verified + prior unverified), junk-filtered (unverified only)
  - pool = L2 _programs_raw.json + crawler _programs_all_raw.json
  - normalize deadlines (parse ISO, drop past < TODAY, keep Non-EU/EU/Round labels)
  - dedup: verified(seed) wins; same (universityId, norm program) keeps one; junk dropped
  - stable id: {universityId}_{slug(subject)}_{slug(program)}

Usage:  $env:PYTHONIOENCODING="utf-8"; python -m scraper.programs.assemble_all
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent.parent
PROG_JSON = ROOT / "frontend" / "public" / "data" / "programs.json"
RAW_ALL = ROOT / "scraper" / "playwright" / "_programs_all_raw.json"
RAW_L2 = ROOT / "scraper" / "playwright" / "_programs_raw.json"
RAW_V2 = ROOT / "scraper" / "playwright" / "_programs_v2_raw.json"

sys.path.insert(0, str(ROOT))
from scraper.programs.normalize import normalize_deadlines
from scraper.programs.quality import non_program_reason_strict


def slug(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    return s[:40] or "prog"


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def make_id(uid: str, subject: str, program: str, seen: set) -> str:
    base = f"{uid}_{slug(subject)}_{slug(program)}"
    cand = base
    n = 2
    while cand in seen:
        cand = f"{base}_{n}"; n += 1
    seen.add(cand)
    return cand


def load(path: Path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


JUNK_TITLE = re.compile(
    r"cookie|cookies|cookie\s*(管理|panel|面板)|homepage|navigation|further information|"
    r"accessibility\s*setting|all areas|^students?$|admis\s*sion\s*depart|"
    r"该网页无法正常运作|le site utilise des cookies|ce site utilise des cookies|"
    r"this website uses cookies|404|search$|^suche$|^search\s*$|^74$|"
    r"^master.?s degree programmes?$|^master.?s programmes?$|^master.?s$|^programmes?$|^programs?$|^all programmes?$|^courses?$|"
    r"^masters?$|^bachelors?$|^study programmes?$|^degree programmes?$|^graduate programmes?$|open day|prepare for your studies|"
    r"admission requirements?|application procedure|how (and when )?to apply|tuition fees?|entry requirements?|"
    r"film festival|news|event\b|open day|webinar|summer school|graduation ceremony|\banniversary\b|"
    r"^idex programs?$|^les programmes europ(?:e|é)ens de recherche$|"
    r"^chef d[ '’]?equipe$|^polydaire$|^eco marathon shell$|^stages?$",
    re.IGNORECASE,
)

DENY_HOSTS = {
    "wikipedia.org", "mastersportal.com", "studyportals.com", "findamasters.com",
    "masterstudies.com", "university-directory.eu", "globaladmissions.com",
    "collegelearners.org", "mygermanuniversity.com", "topuniversities.com",
    "timeshighereducation.com", "usnews.com",
    "globalstudyprep.com", "mastermania.com", "standyou.com", "goaustria.org",
}


def source_host(url: str) -> str:
    try:
        host = (urlparse(url or "").hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def denied_source(url: str) -> bool:
    host = source_host(url)
    return any(host == item or host.endswith("." + item) for item in DENY_HOSTS)


def is_junk(rec: dict) -> bool:
    prog = (rec.get("program") or "").strip()
    dl = rec.get("deadlines") or []
    mats = rec.get("materials") or []
    req = rec.get("requirements") or {}
    has_signal = bool(dl) or any(req.get(key) for key in ("gpa", "ielts", "toefl", "language", "academic"))
    if JUNK_TITLE.search(prog):
        return True
    if non_program_reason_strict(prog, rec.get("sourceUrl") or rec.get("url") or ""):
        return True
    if denied_source(rec.get("sourceUrl") or rec.get("url") or ""):
        return True
    if len(prog) <= 8 and not has_signal and not mats:
        return True
    return False


def main():
    base_full = load(PROG_JSON)
    base = [p for p in base_full if p.get("verified") or not is_junk(p)]
    dropped_base = len(base_full) - len(base)
    raw_l2 = load(RAW_L2)
    raw_all = load(RAW_ALL)
    raw_v2 = load(RAW_V2)
    pool = raw_l2 + raw_all + raw_v2
    print(f"[assemble_all] base programs.json: {len(base_full)} (junk-filtered -> {len(base)}, dropped {dropped_base})")
    print(f"[assemble_all] L2 _programs_raw.json: {len(raw_l2)}")
    print(f"[assemble_all] crawler _programs_all_raw.json: {len(raw_all)}")
    print(f"[assemble_all] crawler _programs_v2_raw.json: {len(raw_v2)}")
    print(f"[assemble_all] pool: {len(pool)}")

    seen_ids = {p.get("id") for p in base}
    key_index = {}
    for p in base:
        key_index[(p.get("universityId"), norm_name(p.get("program")))] = p

    added = 0
    skipped_dup = 0
    skipped_junk = 0
    internal_seen = set()
    for r in pool:
        uid = r.get("universityId")
        nprog = norm_name(r.get("program"))
        if not uid or not nprog:
            continue
        ikey = (uid, nprog)
        if ikey in internal_seen:
            continue
        internal_seen.add(ikey)
        pre_rec = {"program": r.get("program") or "", "deadlines": r.get("deadlines") or [],
                   "materials": r.get("materials") or [], "requirements": r.get("requirements") or {},
                   "sourceUrl": r.get("sourceUrl") or r.get("url") or ""}
        if is_junk(pre_rec):
            skipped_junk += 1
            continue
        if ikey in key_index and key_index[ikey].get("verified"):
            skipped_dup += 1
            continue
        replacement_id = None
        if ikey in key_index and not key_index[ikey].get("verified"):
            existing = key_index[ikey]
            new_dl = normalize_deadlines(r.get("deadlines") or [])
            if r.get("deadlineReviewed") or len(new_dl) > len(existing.get("deadlines") or []):
                replacement_id = existing.get("id")
                base.remove(existing)
            else:
                skipped_dup += 1
                continue
        deadlines = normalize_deadlines(r.get("deadlines") or [])
        rec = {
            "id": replacement_id or make_id(uid, r.get("subject") or "General", r.get("program") or "Program", seen_ids),
            "universityId": uid,
            "subject": r.get("subject") or "General",
            "dept": r.get("dept") or "",
            "program": r.get("program") or "",
            "deadlines": deadlines,
            "materials": r.get("materials") or [],
            "requirements": {
                "gpa": (r.get("requirements") or {}).get("gpa"),
                "ielts": (r.get("requirements") or {}).get("ielts"),
                "toefl": (r.get("requirements") or {}).get("toefl"),
                "language": (r.get("requirements") or {}).get("language"),
                "academic": (r.get("requirements") or {}).get("academic"),
            },
            "sourceUrl": r.get("sourceUrl") or r.get("url") or "",
            "verified": False,
            "updatedAt": r.get("updatedAt") or "",
            "evidenceUrls": r.get("evidenceUrls") or ([r.get("sourceUrl")] if r.get("sourceUrl") else []),
            "fieldSources": r.get("fieldSources") or {},
            "deadlineReviewed": bool(r.get("deadlineReviewed")),
        }
        base.append(rec)
        key_index[(uid, nprog)] = rec
        added += 1

    for p in base:
        p["deadlines"] = normalize_deadlines(p.get("deadlines") or [])
    base.sort(key=lambda p: (not p.get("verified", False), p.get("universityId", ""), p.get("subject", ""), p.get("program", "")))
    PROG_JSON.parent.mkdir(parents=True, exist_ok=True)
    PROG_JSON.write_bytes(json.dumps(base, ensure_ascii=False, indent=2).encode("utf-8"))
    verified = sum(1 for p in base if p.get("verified"))
    print(f"[assemble_all] merged -> {len(base)} programs (verified {verified}, unverified {len(base)-verified})")
    print(f"[assemble_all] added {added} | skipped dup {skipped_dup} | skipped junk {skipped_junk}")
    print(f"[assemble_all] -> {PROG_JSON}")


if __name__ == "__main__":
    main()
