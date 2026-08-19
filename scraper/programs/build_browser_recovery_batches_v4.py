"""Build bounded, deterministic browser-recovery batches without network access.

The builder merges the existing recovery queues with only the browser-eligible
``blocked`` identity-triage records.  Captured or CAPTCHA-blocked duplicates
are excluded before pending work is grouped and sharded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_QUEUE = ROOT / "scraper" / "playwright" / "top500_browser_recovery_queue.json"
RECOVERED_QUEUE = (
    ROOT / "scraper" / "playwright" / "top500_recovered_blocked_browser_queue_v3.json"
)
IDENTITY_TRIAGE = (
    ROOT / "scraper" / "playwright" / "top500_official_identity_triage_v3.json"
)
OUTPUT = ROOT / "scraper" / "playwright" / "top500_browser_recovery_batches_v4.json"

DEFAULT_MAX_SHARD_SIZE = 8
KIND_PRIORITY = {"official-homepage": 0, "program": 1, "evidence": 2}
SOURCE_MAIN = "top500_browser_recovery_queue"
SOURCE_RECOVERED = "top500_recovered_blocked_browser_queue_v3"
SOURCE_TRIAGE = "top500_official_identity_triage_v3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _normalized_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    parts = urlsplit(value.strip())
    scheme = parts.scheme.lower()
    hostname = (parts.hostname or "").lower()
    try:
        port = parts.port
    except ValueError:
        port = None
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = "%s:%d" % (hostname, port)
    else:
        netloc = hostname
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "unknown-host").lower()


def _stable_digest(*values: str) -> str:
    encoded = "\0".join(values).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _string_list(values: Any) -> List[str]:
    return sorted({value for value in _as_list(values) if isinstance(value, str) and value})


def _resolve_path(value: Any, base: Path) -> Optional[Path]:
    if isinstance(value, Path):
        path = value
    elif isinstance(value, str) and value:
        path = Path(value)
    else:
        return None
    if not path.is_absolute():
        path = base / path
    return path.resolve()


class ManifestReader:
    """Small cache for source manifests; invalid inputs remain auditable."""

    def __init__(self) -> None:
        self._cache: Dict[str, Optional[Dict[str, Any]]] = {}

    def read(self, value: Any, base: Path) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
        path = _resolve_path(value, base)
        if path is None:
            return None, None
        marker = str(path)
        if marker not in self._cache:
            try:
                loaded = load_json(path)
                self._cache[marker] = loaded if isinstance(loaded, dict) else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                self._cache[marker] = None
        return path, self._cache[marker]


def _record_urls(record: Dict[str, Any]) -> Iterable[str]:
    for field in ("url", "requestedUrl", "responseUrl", "finalUrl"):
        value = record.get(field)
        if isinstance(value, str) and value:
            yield value


def _manifest_records(manifest: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    pages = manifest.get("pages")
    if isinstance(pages, dict):
        for url, record in pages.items():
            if isinstance(record, dict):
                copy = dict(record)
                copy.setdefault("url", url)
                yield copy
    discovery = _as_dict(manifest.get("discovery"))
    visited = discovery.get("visited")
    if isinstance(visited, dict):
        for url, record in visited.items():
            if isinstance(record, dict):
                copy = dict(record)
                copy.setdefault("url", url)
                yield copy
    for section_name in ("programs", "evidence"):
        section = _as_dict(manifest.get(section_name))
        for record in _as_list(section.get("raw")):
            if isinstance(record, dict):
                yield record


def _matching_manifest_record(
    manifest: Dict[str, Any], url: str
) -> Optional[Dict[str, Any]]:
    target = _normalized_url(url)
    exact = []
    response_matches = []
    for record in _manifest_records(manifest):
        urls = list(_record_urls(record))
        if urls and _normalized_url(urls[0]) == target:
            exact.append(record)
        elif any(_normalized_url(candidate) == target for candidate in urls[1:]):
            response_matches.append(record)
    candidates = exact or response_matches
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda record: (
            0 if record.get("sha256") else 1,
            str(record.get("file") or record.get("rawFile") or ""),
        ),
    )[0]


def _evidence_entry(
    raw_file: Any,
    manifest_file: Any,
    sha256: Any,
    base: Path,
    source: str,
    evidence_type: str,
    hash_verified: Optional[bool] = None,
    hash_origin: str = "recorded",
) -> Dict[str, Any]:
    raw_path = _resolve_path(raw_file, base)
    manifest_path = _resolve_path(manifest_file, base)
    digest = sha256 if isinstance(sha256, str) and sha256 else None
    return {
        "source": source,
        "evidenceType": evidence_type,
        "rawFile": str(raw_path) if raw_path is not None else None,
        "manifestFile": str(manifest_path) if manifest_path is not None else None,
        "sha256": digest,
        "hashOrigin": hash_origin if digest else None,
        "hashVerified": hash_verified,
        "rawPresent": raw_path.is_file() if raw_path is not None else False,
        "manifestPresent": manifest_path.is_file() if manifest_path is not None else False,
    }


def _source_evidence_for_queue_item(
    item: Dict[str, Any], source: str, source_file: Path, reader: ManifestReader
) -> List[Dict[str, Any]]:
    base = source_file.parent
    manifest_path, manifest = reader.read(item.get("sourceManifestFile"), base)
    raw_file = item.get("sourceRawFile")
    digest = item.get("sourceSha256")
    hash_origin = "queue"
    if manifest is not None:
        direct_raw = manifest.get("rawFile")
        direct_sha = manifest.get("sha256")
        if raw_file and direct_raw and _resolve_path(raw_file, base) == _resolve_path(
            direct_raw, manifest_path.parent if manifest_path is not None else base
        ):
            digest = digest or direct_sha
            hash_origin = "source-manifest"
        else:
            record = _matching_manifest_record(manifest, str(item.get("url") or ""))
            if record is not None:
                raw_file = raw_file or record.get("rawFile") or record.get("file")
                digest = digest or record.get("sha256")
                base = manifest_path.parent if manifest_path is not None else base
                hash_origin = "crawler-manifest-record"
    return [
        _evidence_entry(
            raw_file,
            manifest_path or item.get("sourceManifestFile"),
            digest,
            base,
            source,
            "static-page",
            hash_origin=hash_origin,
        )
    ]


def _source_evidence_for_recovered_item(
    item: Dict[str, Any], source_file: Path
) -> List[Dict[str, Any]]:
    base = source_file.parent
    provenance = _as_dict(item.get("provenance"))
    evidence = []
    homepage = _as_dict(provenance.get("officialHomepageRaw"))
    if homepage:
        evidence.append(
            _evidence_entry(
                homepage.get("rawFile"),
                homepage.get("manifestFile"),
                homepage.get("sha256"),
                base,
                SOURCE_RECOVERED,
                "static-homepage",
                hash_origin="official-homepage-raw",
            )
        )
    evidence.append(
        _evidence_entry(
            provenance.get("rorRawFile"),
            provenance.get("rorRawManifestFile"),
            provenance.get("rorRawSha256"),
            base,
            SOURCE_RECOVERED,
            "ror-identity",
            hash_origin="ror-provenance",
        )
    )
    return evidence


def _source_evidence_for_triage_item(
    item: Dict[str, Any], source_file: Path
) -> List[Dict[str, Any]]:
    evidence = []
    references = _as_list(_as_dict(item.get("rorRawEvidence")).get("references"))
    for reference in references:
        if not isinstance(reference, dict):
            continue
        evidence.append(
            _evidence_entry(
                reference.get("rawFile"),
                reference.get("manifestFile"),
                reference.get("actualSha256") or reference.get("expectedSha256"),
                ROOT,
                SOURCE_TRIAGE,
                "ror-identity",
                hash_verified=reference.get("hashVerified")
                if isinstance(reference.get("hashVerified"), bool)
                else None,
                hash_origin="triage-ror-audit",
            )
        )
    if not evidence:
        evidence.append(
            _evidence_entry(
                None, None, None, source_file.parent, SOURCE_TRIAGE, "ror-identity-missing"
            )
        )
    return evidence


def _headers_from_manifest(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if manifest is None:
        return {}
    headers = manifest.get("headers")
    return headers if isinstance(headers, dict) else {}


def detect_platform(headers: Dict[str, Any], hints: Iterable[str] = ()) -> str:
    parts = []
    for key, value in headers.items():
        parts.append(str(key))
        parts.append(str(value))
    parts.extend(str(value) for value in hints if value)
    text = " ".join(parts).casefold()
    checks = (
        ("cloudflare", ("cloudflare", "cf-ray", "cf-mitigated", "cf-cache-status")),
        ("akamai", ("akamai", "akamai ghost", "x-akamai", "ak_bmsc")),
        ("imperva", ("imperva", "incapsula", "x-iinfo", "incap_ses")),
        ("sucuri", ("sucuri", "x-sucuri")),
        ("cloudfront", ("cloudfront", "x-amz-cf-")),
        ("azure-front-door", ("azure front door", "x-azure-ref")),
        ("fastly", ("fastly", "x-served-by")),
    )
    for platform, markers in checks:
        if any(marker in text for marker in markers):
            return platform
    return "unknown"


def _queue_record(
    item: Dict[str, Any], source: str, source_file: Path, index: int, reader: ManifestReader
) -> Optional[Dict[str, Any]]:
    url = item.get("url")
    kind = item.get("kind")
    if not isinstance(url, str) or not url or not isinstance(kind, str) or not kind:
        return None
    manifest_path, manifest = reader.read(item.get("sourceManifestFile"), source_file.parent)
    headers = _headers_from_manifest(manifest)
    evidence = _source_evidence_for_queue_item(item, source, source_file, reader)
    return {
        "universityId": item.get("universityId"),
        "name": item.get("name"),
        "country": item.get("country") or "Unknown",
        "url": url,
        "kind": kind,
        "purpose": item.get("purpose"),
        "officialDomains": _string_list(item.get("officialDomains")),
        "reasonCodes": _string_list(item.get("reasonCodes")),
        "status": str(item.get("status") or "pending").lower(),
        "captchaDetected": bool(item.get("captchaDetected")),
        "platform": detect_platform(headers, [item.get("reasonCodes"), item.get("browserTitle")]),
        "sourceEvidence": evidence,
        "queueReference": {
            "source": source,
            "sourceFile": str(source_file.resolve()),
            "itemIndex": index,
            "universityId": item.get("universityId"),
            "url": url,
            "kind": kind,
        },
        "browserRawFile": item.get("browserRawFile"),
        "browserManifestFile": item.get("browserManifestFile"),
        "browserSha256": item.get("browserSha256"),
    }


def _recovered_record(
    item: Dict[str, Any], source_file: Path, index: int
) -> Optional[Dict[str, Any]]:
    url = item.get("indexUrl")
    if not isinstance(url, str) or not url:
        return None
    provenance = _as_dict(item.get("provenance"))
    homepage = _as_dict(provenance.get("officialHomepageRaw"))
    return {
        "universityId": item.get("universityId"),
        "name": item.get("name"),
        "country": item.get("country") or "Unknown",
        "url": url,
        "kind": "official-homepage",
        "purpose": item.get("browserAction") or "verify-homepage-then-discover-program-catalog",
        "officialDomains": _string_list(item.get("officialDomains")),
        "reasonCodes": _string_list(provenance.get("officialVerificationReasons")),
        "status": str(item.get("status") or "pending").lower(),
        "captchaDetected": bool(item.get("captchaDetected")),
        "platform": detect_platform(_as_dict(homepage.get("headers"))),
        "sourceEvidence": _source_evidence_for_recovered_item(item, source_file),
        "queueReference": {
            "source": SOURCE_RECOVERED,
            "sourceFile": str(source_file.resolve()),
            "itemIndex": index,
            "universityId": item.get("universityId"),
            "url": url,
            "kind": "official-homepage",
        },
        "browserRawFile": item.get("browserRawFile"),
        "browserManifestFile": item.get("browserManifestFile"),
        "browserSha256": item.get("browserSha256"),
    }


def _triage_record(
    item: Dict[str, Any], source_file: Path, index: int
) -> Optional[Dict[str, Any]]:
    if item.get("category") != "blocked":
        return None
    live_page = _as_dict(item.get("livePage"))
    url = live_page.get("requestedUrl") or live_page.get("finalUrl")
    if not isinstance(url, str) or not url:
        return None
    ror_identity = _as_dict(item.get("rorIdentity"))
    return {
        "universityId": item.get("canonicalId"),
        "name": item.get("name"),
        "country": item.get("country") or "Unknown",
        "url": url,
        "kind": "official-homepage",
        "purpose": "recover-browser-rendered-identity-evidence",
        "officialDomains": _string_list(ror_identity.get("selectedDomains")),
        "reasonCodes": _string_list(item.get("reasonCodes")),
        "status": "pending",
        "captchaDetected": False,
        "platform": "unknown",
        "sourceEvidence": _source_evidence_for_triage_item(item, source_file),
        "queueReference": {
            "source": SOURCE_TRIAGE,
            "sourceFile": str(source_file.resolve()),
            "itemIndex": index,
            "universityId": item.get("canonicalId"),
            "url": url,
            "kind": "official-homepage",
            "statusGuardrail": item.get("statusGuardrail"),
        },
        "browserRawFile": None,
        "browserManifestFile": None,
        "browserSha256": None,
    }


def _evidence_key(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        entry.get("source"),
        entry.get("evidenceType"),
        entry.get("rawFile"),
        entry.get("manifestFile"),
        entry.get("sha256"),
    )


def _merge_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for record in records:
        key = (record["kind"], _normalized_url(record["url"]))
        grouped.setdefault(key, []).append(record)

    merged = []
    for (kind, normalized_url), members in sorted(grouped.items()):
        members.sort(
            key=lambda item: (
                KIND_PRIORITY.get(item["kind"], 99),
                str(item.get("country") or "").casefold(),
                str(item.get("universityId") or ""),
                item["url"],
            )
        )
        statuses = {member["status"] for member in members}
        captcha = any(member.get("captchaDetected") for member in members)
        if captcha:
            status = "blocked"
        elif "captured" in statuses or any(member.get("browserSha256") for member in members):
            status = "captured"
        elif "blocked" in statuses:
            status = "blocked"
        elif "pending" in statuses:
            status = "pending"
        elif "error" in statuses:
            status = "error"
        else:
            status = sorted(statuses)[0] if statuses else "unknown"

        evidence_by_key = {}
        for member in members:
            for entry in member["sourceEvidence"]:
                evidence_by_key[_evidence_key(entry)] = entry
        source_evidence = [evidence_by_key[key] for key in sorted(evidence_by_key, key=str)]
        platforms = [
            member["platform"] for member in members if member.get("platform") != "unknown"
        ]
        platform = sorted(platforms)[0] if platforms else "unknown"
        countries = sorted({str(member.get("country") or "Unknown") for member in members})
        university_ids = sorted(
            {str(member["universityId"]) for member in members if member.get("universityId")}
        )
        names = sorted({str(member["name"]) for member in members if member.get("name")})
        domains = sorted(
            {domain for member in members for domain in member.get("officialDomains") or []}
        )
        reason_codes = sorted(
            {reason for member in members for reason in member.get("reasonCodes") or []}
        )
        task_key = "brv4-" + _stable_digest(kind, normalized_url)[:20]
        primary_evidence = next(
            (entry for entry in source_evidence if entry.get("rawFile") or entry.get("manifestFile")),
            source_evidence[0] if source_evidence else {},
        )
        merged.append(
            {
                "taskKey": task_key,
                "universityId": university_ids[0] if university_ids else None,
                "universityIds": university_ids,
                "name": names[0] if names else None,
                "names": names,
                "country": countries[0] if len(countries) == 1 else "Multiple",
                "countries": countries,
                "url": members[0]["url"],
                "normalizedUrl": normalized_url,
                "host": _host(normalized_url),
                "kind": kind,
                "purpose": next(
                    (member.get("purpose") for member in members if member.get("purpose")), None
                ),
                "officialDomains": domains,
                "reasonCodes": reason_codes,
                "platform": platform,
                "status": status,
                "captchaDetected": captcha,
                "sourceRawFile": primary_evidence.get("rawFile"),
                "sourceManifestFile": primary_evidence.get("manifestFile"),
                "sourceSha256": primary_evidence.get("sha256"),
                "sourceEvidence": source_evidence,
                "queueReferences": [member["queueReference"] for member in members],
                "mergedRecordCount": len(members),
                "captchaPolicy": "stop",
            }
        )
    return merged


def _bounded_shards(items: List[Dict[str, Any]], max_size: int) -> List[List[Dict[str, Any]]]:
    ordered = sorted(
        items,
        key=lambda item: (_stable_digest(item["taskKey"]), item["taskKey"]),
    )
    return [ordered[start : start + max_size] for start in range(0, len(ordered), max_size)]


def build_batches(
    main_queue: Dict[str, Any],
    recovered_queue: List[Dict[str, Any]],
    identity_triage: Dict[str, Any],
    main_file: Path = MAIN_QUEUE,
    recovered_file: Path = RECOVERED_QUEUE,
    triage_file: Path = IDENTITY_TRIAGE,
    max_shard_size: int = DEFAULT_MAX_SHARD_SIZE,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    if max_shard_size < 1:
        raise ValueError("max_shard_size must be at least 1")
    if not isinstance(main_queue, dict):
        raise TypeError("main_queue must be an object")
    if not isinstance(recovered_queue, list):
        raise TypeError("recovered_queue must be an array")
    if not isinstance(identity_triage, dict):
        raise TypeError("identity_triage must be an object")

    reader = ManifestReader()
    records = []
    main_items = _as_list(main_queue.get("items"))
    for index, item in enumerate(main_items):
        if isinstance(item, dict):
            record = _queue_record(item, SOURCE_MAIN, main_file, index, reader)
            if record is not None:
                records.append(record)
    for index, item in enumerate(recovered_queue):
        if isinstance(item, dict):
            record = _recovered_record(item, recovered_file, index)
            if record is not None:
                records.append(record)
    triage_items = _as_list(identity_triage.get("items"))
    triage_eligible = 0
    for index, item in enumerate(triage_items):
        if isinstance(item, dict) and item.get("category") == "blocked":
            triage_eligible += 1
            record = _triage_record(item, triage_file, index)
            if record is not None:
                records.append(record)

    merged = _merge_records(records)
    pending = [item for item in merged if item["status"] == "pending"]
    excluded = [item for item in merged if item["status"] != "pending"]

    groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}
    for item in pending:
        key = (item["kind"], item["country"], item["host"], item["platform"])
        groups.setdefault(key, []).append(item)

    batches = []
    priority = 0
    sorted_groups = sorted(
        groups.items(),
        key=lambda row: (
            KIND_PRIORITY.get(row[0][0], 99),
            row[0][1].casefold(),
            row[0][2],
            row[0][3],
        ),
    )
    for group_key, group_items in sorted_groups:
        kind, country, host, platform = group_key
        shards = _bounded_shards(group_items, max_shard_size)
        group_id = "brg4-" + _stable_digest(kind, country, host, platform)[:16]
        for shard_index, shard_items in enumerate(shards):
            batch_id = "%s-s%02d-of-%02d" % (group_id, shard_index + 1, len(shards))
            batch_items = []
            for item in shard_items:
                copy = dict(item)
                copy["batchId"] = batch_id
                copy["shardIndex"] = shard_index
                copy["shardCount"] = len(shards)
                copy["queuePosition"] = priority + len(batch_items)
                batch_items.append(copy)
            batches.append(
                {
                    "batchId": batch_id,
                    "priority": len(batches),
                    "groupId": group_id,
                    "kind": kind,
                    "country": country,
                    "host": host,
                    "platform": platform,
                    "shardIndex": shard_index,
                    "shardNumber": shard_index + 1,
                    "shardCount": len(shards),
                    "itemCount": len(batch_items),
                    "status": "pending",
                    "captchaPolicy": "stop",
                    "items": batch_items,
                }
            )
            priority += len(batch_items)

    pending_kind_counts = Counter(item["kind"] for item in pending)
    platform_counts = Counter(item["platform"] for item in pending)
    country_counts = Counter(item["country"] for item in pending)
    excluded_status_counts = Counter(item["status"] for item in excluded)
    source_evidence_total = sum(len(item["sourceEvidence"]) for item in pending)
    source_hash_count = sum(
        1
        for item in pending
        if any(entry.get("sha256") for entry in item["sourceEvidence"])
    )
    largest_shard = max((batch["itemCount"] for batch in batches), default=0)

    return {
        "schemaVersion": 4,
        "generatedAt": generated_at or utc_now(),
        "sources": [
            {"name": SOURCE_MAIN, "file": str(main_file.resolve()), "records": len(main_items)},
            {
                "name": SOURCE_RECOVERED,
                "file": str(recovered_file.resolve()),
                "records": len(recovered_queue),
            },
            {
                "name": SOURCE_TRIAGE,
                "file": str(triage_file.resolve()),
                "records": len(triage_items),
                "eligibleBlockedRecords": triage_eligible,
            },
        ],
        "policy": {
            "networkAccessUsed": False,
            "rawEvidencePreserved": True,
            "verifiedStatusModified": False,
            "rawDataModified": False,
            "frontendModified": False,
            "pendingOnly": True,
            "deduplicationKey": "kind+normalizedUrl",
            "kindPriority": ["official-homepage", "program", "evidence", "other"],
            "captcha": {
                "onDetection": "stop",
                "scope": "current-batch",
                "bypassProhibited": True,
                "persistRenderedEvidence": True,
                "resumeRequiresUserAction": True,
            },
        },
        "shardStrategy": {
            "groupBy": ["kind", "country", "host", "platform"],
            "algorithm": "sha256-task-key-order-then-bounded-chunks",
            "maxShardSize": max_shard_size,
            "deterministic": True,
        },
        "summary": {
            "inputRecords": len(records),
            "uniqueTasks": len(merged),
            "duplicateRecordsMerged": len(records) - len(merged),
            "pendingTasks": len(pending),
            "excludedTasks": len(excluded),
            "excludedStatusCounts": dict(sorted(excluded_status_counts.items())),
            "kindCounts": dict(sorted(pending_kind_counts.items())),
            "platformCounts": dict(sorted(platform_counts.items())),
            "countryCounts": dict(sorted(country_counts.items())),
            "groups": len(groups),
            "shards": len(batches),
            "largestShard": largest_shard,
            "sourceEvidenceRecords": source_evidence_total,
            "tasksWithSourceSha256": source_hash_count,
        },
        "excludedItems": excluded,
        "batches": batches,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-queue", type=Path, default=MAIN_QUEUE)
    parser.add_argument("--recovered-queue", type=Path, default=RECOVERED_QUEUE)
    parser.add_argument("--identity-triage", type=Path, default=IDENTITY_TRIAGE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--max-shard-size", type=int, default=DEFAULT_MAX_SHARD_SIZE)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    result = build_batches(
        load_json(args.main_queue),
        load_json(args.recovered_queue),
        load_json(args.identity_triage),
        main_file=args.main_queue,
        recovered_file=args.recovered_queue,
        triage_file=args.identity_triage,
        max_shard_size=args.max_shard_size,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
