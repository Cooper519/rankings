"""Apply reviewed, official-source facts to sanitized v2 crawl records."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "scraper" / "playwright" / "_programs_v2_raw.json"
OVERRIDES = ROOT / "scraper" / "programs" / "curated_program_overrides.json"
REPORT = ROOT / "scraper" / "playwright" / "_programs_v2_override_report.json"


def load(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def url_key(value):
    return (value or "").split("#", 1)[0].rstrip("/").lower()


def merge_unique(left, right):
    result = list(left or [])
    seen = {str(value).strip().lower() for value in result}
    for value in right or []:
        key = str(value).strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def apply(record, override):
    changed = []
    if override.get("replaceDeadlines"):
        deadlines = list(override.get("deadlines") or [])
        if record.get("deadlines") != deadlines or not record.get("deadlineReviewed"):
            record["deadlines"] = deadlines
            record["deadlineReviewed"] = True
            changed.append("deadlines")
        deadline_sources = override.get("deadlineSources") or []
        if deadline_sources:
            record["evidenceUrls"] = merge_unique(record.get("evidenceUrls"), deadline_sources)
            field_sources = record.setdefault("fieldSources", {})
            field_sources["deadlines"] = list(deadline_sources)
    requirements = record.setdefault("requirements", {})
    for key, value in (override.get("requirements") or {}).items():
        if value and requirements.get(key) != value:
            requirements[key] = value
            changed.append("requirements." + key)
    materials = merge_unique(record.get("materials"), override.get("materials"))
    if materials != (record.get("materials") or []):
        record["materials"] = materials
        changed.append("materials")
    sources = override.get("sources") or []
    if sources:
        record["evidenceUrls"] = merge_unique(record.get("evidenceUrls"), sources)
        field_sources = record.setdefault("fieldSources", {})
        if override.get("requirements"):
            field_sources["requirements"] = merge_unique(field_sources.get("requirements"), sources)
        if override.get("materials"):
            field_sources["materials"] = merge_unique(field_sources.get("materials"), sources)
    return changed


def main():
    records = load(RAW, [])
    config = load(OVERRIDES, {})
    by_university = config.get("universities") or {}
    by_program = {url_key(key): value for key, value in (config.get("programs") or {}).items()}
    report = []
    for record in records:
        changed = []
        common = by_university.get(record.get("universityId"))
        if common:
            changed.extend(apply(record, common))
        specific = by_program.get(url_key(record.get("sourceUrl")))
        if specific:
            changed.extend(apply(record, specific))
        if changed:
            report.append({
                "universityId": record.get("universityId"),
                "program": record.get("program"),
                "sourceUrl": record.get("sourceUrl"),
                "fields": sorted(set(changed)),
            })
    RAW.write_bytes(json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8"))
    REPORT.write_bytes(json.dumps({"updated": len(report), "records": report}, ensure_ascii=False, indent=2).encode("utf-8"))
    print("[curated-overrides] updated=%d -> %s" % (len(report), REPORT))


if __name__ == "__main__":
    main()
