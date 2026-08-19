"""Merge deterministic JSON shard outputs with strict completeness checks."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def records(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    raise ValueError("shard must be an array or contain an items array")


def record_id(item: dict) -> str:
    value = item.get("canonicalId") or item.get("universityId") or item.get("id")
    if not value:
        raise ValueError("record missing canonicalId/universityId/id")
    return str(value)


def merge_shards(shards: list[Path], expected: Path | None = None) -> dict:
    merged: dict[str, dict] = {}
    errors: list[dict] = []
    source_summaries = []
    for shard in sorted(shards, key=lambda path: path.name):
        payload = load_json(shard)
        source_summaries.append({"file": str(shard.resolve()), "summary": payload.get("summary")})
        errors.extend(payload.get("errors") or [])
        for item in records(payload):
            identifier = record_id(item)
            if identifier in merged:
                raise ValueError(f"duplicate record across shards: {identifier}")
            merged[identifier] = item

    expected_ids = None
    if expected:
        expected_ids = {record_id(item) for item in records(load_json(expected))}
        missing = sorted(expected_ids - merged.keys())
        unexpected = sorted(merged.keys() - expected_ids)
    else:
        missing, unexpected = [], []
    if missing or unexpected or errors:
        raise ValueError(
            f"incomplete shards: missing={len(missing)} unexpected={len(unexpected)} errors={len(errors)}"
        )

    items = sorted(merged.values(), key=lambda item: (item.get("queuePosition", 10**9), record_id(item)))
    status_counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("verificationStatus") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceShards": source_summaries,
        "expectedInput": str(expected.resolve()) if expected else None,
        "summary": {
            "processed": len(items),
            "uniqueIds": len(merged),
            "expected": len(expected_ids) if expected_ids is not None else None,
            "errors": 0,
            "statusCounts": status_counts,
        },
        "items": items,
        "errors": [],
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--pattern", default="*.json")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    shards = list(args.input_dir.glob(args.pattern))
    if not shards:
        raise SystemExit("no shard files matched")
    output = merge_shards(shards, args.expected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
