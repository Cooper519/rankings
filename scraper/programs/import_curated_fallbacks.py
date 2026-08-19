"""Import reviewed official records when automated access is blocked by WAF."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scraper.programs.quality import non_program_reason


ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "scraper" / "playwright" / "_programs_v2_raw.json"
STATE = ROOT / "scraper" / "playwright" / "_crawl_progress_v2.json"
FALLBACKS = ROOT / "scraper" / "programs" / "curated_program_fallbacks.json"


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def url_key(value):
    return (value or "").split("#", 1)[0].rstrip("/").lower()


def main():
    raw = load(RAW, [])
    state = load(STATE, {})
    rows = load(FALLBACKS, [])
    seen = {(row.get("universityId"), url_key(row.get("sourceUrl"))) for row in raw}
    added = 0
    touched = set()
    for row in rows:
        uid = row.get("universityId") or ""
        source = row.get("sourceUrl") or ""
        if non_program_reason(row.get("program"), source):
            raise ValueError("curated fallback failed quality gate: %s" % source)
        key = (uid, url_key(source))
        touched.add(uid)
        if key in seen:
            continue
        seen.add(key)
        raw.append({
            **row,
            "deadlines": [],
            "materials": [],
            "requirements": {"gpa": None, "ielts": None, "toefl": None, "language": None, "academic": None},
            "evidenceUrls": [source],
            "fieldSources": {"deadlines": [], "materials": [], "requirements": []},
            "verified": False,
            "updatedAt": date.today().isoformat(),
            "fallbackReason": "blocked_waf",
        })
        added += 1
    for uid in touched:
        count = sum(1 for row in raw if row.get("universityId") == uid)
        current = state.get(uid) if isinstance(state.get(uid), dict) else {}
        state[uid] = {
            **current,
            "status": "partial",
            "found": count,
            "candidateCount": max(int(current.get("candidateCount") or 0), 55),
            "catalogUrl": next((row.get("catalogUrl") for row in rows if row.get("universityId") == uid), ""),
            "failureReason": "blocked_waf: curated official fallback imported; full catalog retry required",
            "qualityRejected": 0,
        }
    RAW.write_bytes(json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8"))
    STATE.write_bytes(json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
    print("[curated-fallbacks] added=%d total=%d" % (added, len(raw)))


if __name__ == "__main__":
    main()
