"""Combine official-site and programme raw blockers into one browser queue."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def build(homepage_targets: list[dict], coverage: dict) -> dict:
    tasks = []
    seen = set()

    def add(task):
        key = (task["universityId"], task["url"], task["kind"])
        if key not in seen:
            seen.add(key)
            tasks.append(task)

    for target in homepage_targets:
        url = target.get("indexUrl") or ""
        if not url:
            continue
        raw = (target.get("provenance") or {}).get("officialHomepageRaw") or {}
        add({
            "universityId": target["universityId"],
            "name": target.get("name"),
            "country": target.get("country"),
            "url": url,
            "kind": "official-homepage",
            "purpose": "verify-homepage-then-discover-program-catalog",
            "officialDomains": target.get("officialDomains") or [],
            "sourceRawFile": raw.get("rawFile"),
            "sourceManifestFile": raw.get("manifestFile"),
            "sourceStatus": raw.get("status"),
            "reasonCodes": (target.get("provenance") or {}).get("officialVerificationReasons") or [],
            "status": "pending",
        })
    for university in coverage.get("universities") or []:
        for blocked in university.get("blockedUrls") or []:
            record = blocked.get("record") or {}
            add({
                "universityId": university["universityId"],
                "name": university.get("name"),
                "country": university.get("country"),
                "url": blocked["url"],
                "kind": blocked.get("kind") or "other",
                "purpose": "capture-blocked-raw-page",
                "officialDomains": [],
                "sourceRawFile": record.get("rawFile"),
                "sourceManifestFile": university.get("manifestFile"),
                "sourceStatus": record.get("statusCode") or record.get("httpStatus"),
                "reasonCodes": ["static-page-blocked"],
                "status": "pending",
            })
    kind_counts = {}
    for task in tasks:
        kind_counts[task["kind"]] = kind_counts.get(task["kind"], 0) + 1
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "browserCaptureRequired": True,
            "rawEvidencePreserved": True,
            "cleanedDataModified": False,
        },
        "summary": {"tasks": len(tasks), "uniqueKeys": len(seen), "kindCounts": kind_counts},
        "items": tasks,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homepage-targets", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build(load(args.homepage_targets), load(args.coverage))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
