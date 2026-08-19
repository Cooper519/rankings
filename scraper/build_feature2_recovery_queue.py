"""Build a Feature 2 recovery queue for schools crawled on the wrong domain."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scraper.feature2_merge_results import domain_matches, load, trusted_domains_by_id
except ImportError:  # Support direct execution from the scraper directory.
    from feature2_merge_results import domain_matches, load, trusted_domains_by_id

ROOT = Path(__file__).resolve().parent.parent
COVERAGE = ROOT / "frontend" / "public" / "data" / "feature2_coverage.json"
QUEUE_PATHS = (
    ROOT / "scraper" / "playwright" / "feature2_crawl_queue.json",
    ROOT / "scraper" / "playwright" / "feature2_crawl_queue2.json",
)
OUTPUT = ROOT / "scraper" / "playwright" / "feature2_crawl_recovery_queue.json"


def build() -> list[dict]:
    coverage = load(COVERAGE, {}) or {}
    missing = {
        row.get("canonicalId"): row
        for row in coverage.get("schools") or []
        if row.get("coverageStatus") == "missing" and row.get("canonicalId")
    }
    source_rows = {}
    for path in QUEUE_PATHS:
        for row in load(path, []) or []:
            if isinstance(row, dict) and row.get("canonicalId"):
                source_rows[row["canonicalId"]] = row

    trusted = trusted_domains_by_id()
    records = []
    for canonical_id, coverage_row in missing.items():
        source = source_rows.get(canonical_id) or coverage_row
        domains = sorted(trusted.get(canonical_id) or [])
        current = str(source.get("officialDomain") or "")
        if not domains or domain_matches(current, domains):
            continue
        row = dict(source)
        row["officialDomain"] = domains[0]
        row["previousOfficialDomain"] = current or None
        row["trustedOfficialDomains"] = domains
        row["recoveryReason"] = "previous-domain-not-in-trusted-domain-set"
        records.append(row)
    records.sort(key=lambda row: (row.get("country") or "", row.get("name") or "", row["canonicalId"]))
    return records


def main() -> None:
    records = build()
    OUTPUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "recoveryTargets": len(records),
        "output": str(OUTPUT),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
