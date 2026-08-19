"""Sanitize v2 raw program records before they reach programs.json.

This gate repairs a title only when an official program-detail URL has an
unambiguous slug. Category, admissions, research, event, and portal pages are
rejected. A machine-readable report is kept for audit.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

from scraper.programs.quality import BLOCKED_PATH, non_program_reason


ROOT = Path(__file__).resolve().parent.parent.parent
PW = ROOT / "scraper" / "playwright"
RAW = PW / "_programs_v2_raw.json"
STATE = PW / "_crawl_progress_v2.json"
REPORT = PW / "_programs_v2_sanitize_report.json"

GENERIC_SECTION = re.compile(r"^(in the same section|dans la m.me rubrique)(\s+\1)*$", re.I)
GENERIC_TITLE = re.compile(r"^(further information|oferta de m.sters oficials)$", re.I)
CATALOG_SUFFIX = re.compile(r"\s*:\s*fiche parcours\s*:\s*offre de formation\s*$", re.I)
GENERIC_SLUGS = {
    "master", "masters", "program", "programs", "programme", "programmes",
    "all-programmes", "international-study-programmes", "specialized-master-degree",
    "recherche-html", "en", "fr", "studies", "education",
}
GENERIC_FILE_SLUGS = {"titulacio.html", "index.html", "default.html"}
LOW_SIGNAL_MATERIALS = {"bachelor"}


def load(path, default):
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    # Recover from accidental PowerShell scalar serialization if encountered.
    if isinstance(data, dict) and isinstance(data.get("value"), list):
        return data["value"]
    return data


def slug_title(url):
    try:
        path = unquote(urlparse(url).path).strip("/")
    except ValueError:
        return ""
    if not path or BLOCKED_PATH.search("/" + path + "/"):
        return ""
    segments = [segment.lower() for segment in path.split("/") if segment]
    slug = next((segment for segment in reversed(segments) if segment not in GENERIC_FILE_SLUGS), "")
    slug = re.sub(r"-\d{6,}$", "", slug)
    if not slug or slug in GENERIC_SLUGS or re.search(r"20\d{2}", slug):
        return ""
    slug = re.sub(r"^(?:master-s-degree|masters-degree|master-of-science-in|master-of-science|master)-", "", slug)
    slug = re.sub(r"-(?:master|englisch|bmt)$", "", slug)
    words = [word for word in re.split(r"[-_]+", slug) if word]
    if len(words) > 12 or not words:
        return ""
    return " ".join(words).title()


def infer_subject(title):
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode("ascii").lower()
    if re.search(r"computer|informatics|data|software|algorithm|\bai\b|artificial intelligence|machine learning", text):
        return "Computer Science"
    if re.search(r"electrical|electronic|embed|power|signal|telecomm|communication and information technology", text):
        return "Electrical Engineering"
    if re.search(r"mechan|robot|mechatron|aerospac|automot", text):
        return "Mechanical Engineering"
    if re.search(r"math|statistic", text):
        return "Mathematics"
    if re.search(r"physic", text):
        return "Physics"
    if re.search(r"civil|architect|construct|environ|geotec", text):
        return "Civil/Environmental Engineering"
    if re.search(r"econ|manage|business|finance", text):
        return "Economics/Management"
    if re.search(r"biolog|chemistr|life|bio|medical|health", text):
        return "Life Sciences"
    return "General"


def main():
    records = load(RAW, [])
    state = load(STATE, {})
    kept = []
    rejected = []
    repaired = []
    seen = set()

    for record in records:
        uid = record.get("universityId") or ""
        title = re.sub(r"\s+", " ", record.get("program") or "").strip()
        source = record.get("sourceUrl") or ""
        reason = ""
        cleaned_title = CATALOG_SUFFIX.sub("", title).strip()
        if cleaned_title != title:
            repaired.append({"universityId": uid, "from": title, "to": cleaned_title, "sourceUrl": source})
            title = cleaned_title
        if GENERIC_SECTION.search(title) or GENERIC_TITLE.search(title):
            recovered = slug_title(source)
            if recovered:
                repaired.append({"universityId": uid, "from": title, "to": recovered, "sourceUrl": source})
                title = recovered
            else:
                reason = "generic-title-not-recoverable"
        if not reason:
            reason = non_program_reason(title, source)
        key = (uid, source.split("#")[0].rstrip("/").lower())
        if not reason and key in seen:
            reason = "duplicate-url"
        if reason:
            rejected.append({"universityId": uid, "program": title, "sourceUrl": source, "reason": reason})
            continue
        seen.add(key)
        record["program"] = title
        if (record.get("subject") or "General") == "General":
            record["subject"] = infer_subject(title)
        materials = record.get("materials") or []
        record["materials"] = [item for item in materials if str(item).strip().lower() not in LOW_SIGNAL_MATERIALS]
        kept.append(record)

    retained_by_uni = Counter(record.get("universityId") for record in kept)
    rejected_by_uni = Counter(record.get("universityId") for record in rejected)
    if isinstance(state, dict):
        for uid in set(retained_by_uni) | set(rejected_by_uni):
            row = state.get(uid)
            if not isinstance(row, dict):
                continue
            retained = retained_by_uni.get(uid, 0)
            count = rejected_by_uni.get(uid, 0)
            row["found"] = retained
            row["qualityRejected"] = count
            if count and retained == 0:
                row["status"] = "failed"
                row["failureReason"] = "all discovered records rejected by quality gate"
            elif count:
                row["status"] = "partial"

    RAW.write_bytes(json.dumps(kept, ensure_ascii=False, indent=2).encode("utf-8"))
    STATE.write_bytes(json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8"))
    REPORT.write_bytes(json.dumps({
        "generatedAt": date.today().isoformat(),
        "input": len(records), "kept": len(kept), "repaired": repaired,
        "rejected": rejected,
    }, ensure_ascii=False, indent=2).encode("utf-8"))
    print("[sanitize-v2] input=%d kept=%d repaired=%d rejected=%d" % (len(records), len(kept), len(repaired), len(rejected)))
    print("[sanitize-v2] kept-by-university=%s" % dict(retained_by_uni))
    print("[sanitize-v2] -> %s" % REPORT)


if __name__ == "__main__":
    main()
