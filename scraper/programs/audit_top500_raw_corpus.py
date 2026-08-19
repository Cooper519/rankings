"""Audit raw programme manifests without parsing or cleaning their content."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scraper.programs.scrape_programs_static import safe_id


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def audit(targets: list[dict], root: Path) -> dict:
    rows = []
    totals = Counter()
    for target in targets:
        uid = target["universityId"]
        manifest_file = root / safe_id(uid) / "manifest.json"
        if not manifest_file.exists():
            rows.append({"universityId": uid, "name": target.get("name"), "manifestStatus": "missing"})
            totals["missingManifests"] += 1
            continue
        manifest = load(manifest_file)
        page_counts = {kind: Counter() for kind in ("program", "evidence", "other")}
        blocked_urls = []
        error_urls = []
        for url, page in (manifest.get("pages") or {}).items():
            kind = page.get("kind") if page.get("kind") in {"program", "evidence"} else "other"
            status = page.get("status") or "unknown"
            page_counts[kind][status] += 1
            if status == "blocked":
                blocked_urls.append({"url": url, "kind": kind, "record": page})
            if status == "error":
                error_urls.append({"url": url, "kind": kind, "record": page})
        candidates = len((manifest.get("discovery") or {}).get("programCandidates") or {})
        row = {
            "universityId": uid,
            "name": target.get("name"),
            "country": target.get("country"),
            "manifestStatus": manifest.get("status"),
            "discoveryStatus": (manifest.get("discovery") or {}).get("status"),
            "discoveryStoppedReason": (manifest.get("discovery") or {}).get("stoppedReason"),
            "programCandidates": candidates,
            "pageCounts": {kind: dict(counts) for kind, counts in page_counts.items()},
            "blockedUrls": blocked_urls,
            "errorUrls": error_urls,
            "manifestFile": str(manifest_file.resolve()),
        }
        rows.append(row)
        totals["manifests"] += 1
        totals["zeroCandidates"] += candidates == 0
        totals["withCandidates"] += candidates > 0
        totals["programCandidates"] += candidates
        for kind, counts in page_counts.items():
            for status, count in counts.items():
                totals[f"{kind}_{status}"] += count
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "rawRoot": str(root.resolve()),
        "summary": {"targets": len(targets), **dict(sorted(totals.items()))},
        "universities": rows,
    }


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(load(args.targets), args.raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
