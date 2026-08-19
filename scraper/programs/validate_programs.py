"""Quality gate for raw v2 records and assembled frontend program data."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from scraper.programs.quality import (
    denied_source,
    non_program_reason,
    non_program_reason_strict,
    source_host,
)


ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "frontend" / "public" / "data"
PW = ROOT / "scraper" / "playwright"
DOMAIN_EXCEPTIONS = ROOT / "scraper" / "programs" / "official_domain_exceptions.json"
def load(path):
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def validate(records, raw_v2=False):
    universities = load(DATA / "universities.json")
    if not isinstance(universities, dict):
        universities = {}
    coverage = {row["universityId"]: row for row in load(DATA / "program_coverage.json")}
    aliases = load(DATA / "university_aliases.json") or {}
    canonical = aliases.get("canonicalById", {}) if isinstance(aliases, dict) else {}
    domain_exceptions = load(DOMAIN_EXCEPTIONS) or {}
    errors = []
    warnings = []
    ids = Counter()

    for index, record in enumerate(records):
        label = record.get("id") or ("row-%d" % index)
        uid = record.get("universityId") or ""
        title = (record.get("program") or "").strip()
        source = record.get("sourceUrl") or ""
        host = source_host(source)
        if not uid or uid not in universities:
            errors.append((label, "orphan universityId", uid))
        semantic_reason = (
            non_program_reason(title, source)
            if raw_v2
            else non_program_reason_strict(title, source)
        )
        if semantic_reason and (raw_v2 or not record.get("verified")):
            errors.append((label, "non-program record: " + semantic_reason, title or source))
        if denied_source(source):
            errors.append((label, "third-party source is not allowed", host))
        if raw_v2:
            cid = canonical.get(uid, uid)
            row = coverage.get(cid, {})
            allowed = row.get("officialDomains") or []
            catalog_host = source_host(record.get("catalogUrl") or "")
            allowed = list(allowed) + list(record.get("officialDomains") or []) + list(domain_exceptions.get(uid) or [])
            allowed += [catalog_host] if catalog_host else []
            if allowed and not any(host == item or host.endswith("." + item) or item.endswith("." + host) for item in allowed):
                errors.append((label, "source does not match official/catalog domain", host))
        for deadline in record.get("deadlines") or []:
            value = deadline.get("date") or ""
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                if not raw_v2:
                    errors.append((label, "deadline is not ISO", value))
                continue
            try:
                parsed = date.fromisoformat(value)
                if parsed < date.today():
                    errors.append((label, "past deadline remains", value))
            except ValueError:
                errors.append((label, "invalid deadline", value))
        if record.get("id"):
            ids[record["id"]] += 1
        if not record.get("deadlines") and not any((record.get("requirements") or {}).get(k) for k in ("gpa", "ielts", "toefl", "language", "academic")):
            warnings.append((label, "no deadline or hard requirement", ""))

    for program_id, count in ids.items():
        if count > 1:
            errors.append((program_id, "duplicate program id", str(count)))
    return errors, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-v2", action="store_true")
    args = parser.parse_args()
    path = PW / "_programs_v2_raw.json" if args.raw_v2 else DATA / "programs.json"
    records = load(path)
    errors, warnings = validate(records, raw_v2=args.raw_v2)
    print("[validate] file=%s records=%d errors=%d warnings=%d" % (path.name, len(records), len(errors), len(warnings)))
    for item in errors[:30]:
        print("  ERROR | %s | %s | %s" % item)
    for item in warnings[:10]:
        print("  WARN  | %s | %s | %s" % item)
    if len(warnings) > 10:
        print("  ... %d more warnings" % (len(warnings) - 10))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
