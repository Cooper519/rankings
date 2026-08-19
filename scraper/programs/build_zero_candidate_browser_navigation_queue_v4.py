"""Build an offline browser-navigation queue for verified zero-candidate schools.

The builder only copies recorded homepage URLs. It verifies the existing
homepage raw body and manifest before admitting an item, performs no network
requests, and never derives a catalogue or search URL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent.parent
INPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top500_verified_zero_catalog_discovery_batch_v4.json"
)
OUTPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top500_zero_candidate_browser_navigation_queue_v4.json"
)
DEFAULT_SHARD_COUNT = 16
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PLATFORM_MARKERS = (
    ("terminalfour", (b"terminalfour", b"t4_")),
    ("wordpress", (b"wp-content/", b"wp-includes/", b"wordpress")),
    ("drupal", (b"drupal-settings-json", b"/sites/default/files/", b"drupal")),
    ("adobe-experience-manager", (b"/etc.clientlibs/", b"cq:page", b"aem-")),
    ("sitecore", (b"sitecore", b"sc_mode")),
    ("squiz-matrix", (b"squiz", b"data-assetid")),
    ("typo3", (b"typo3",)),
    ("joomla", (b"joomla",)),
    ("nextjs", (b"__next_data__", b"/_next/")),
    ("nuxt", (b"__nuxt__", b"/_nuxt/")),
    ("laravel", (b"laravel_session",)),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_host(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text if "://" in text else "//" + text)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    if (
        not host
        or len(host) > 253
        or ".." in host
        or not re.fullmatch(r"[a-z0-9.-]+", host)
        or any(not label or len(label) > 63 for label in host.split("."))
    ):
        return ""
    return host


def normalize_domains(values: Any) -> List[str]:
    if not isinstance(values, list) or not values:
        return []
    domains = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return []
        domain = normalize_host(value)
        if not domain:
            return []
        if domain not in domains:
            domains.append(domain)
    return domains


def host_is_official(host: str, domains: Sequence[str]) -> bool:
    return bool(
        host
        and any(host == domain or host.endswith("." + domain) for domain in domains)
    )


def resolve_recorded_path(value: str, manifest_file: Optional[Path] = None) -> Path:
    path = Path(value)
    if not path.is_absolute() and manifest_file is not None:
        path = manifest_file.parent / path
    return path.resolve()


def verify_homepage_raw(target: Dict[str, Any]) -> Tuple[Dict[str, Any], bytes]:
    provenance = target.get("provenance") or {}
    raw = provenance.get("officialHomepageRaw") or {}
    if not isinstance(raw, dict):
        raise ValueError("officialHomepageRaw is missing")

    raw_file_value = raw.get("rawFile")
    manifest_file_value = raw.get("manifestFile")
    expected_digest = raw.get("sha256")
    if not isinstance(raw_file_value, str) or not raw_file_value:
        raise ValueError("homepage rawFile is missing")
    if not isinstance(manifest_file_value, str) or not manifest_file_value:
        raise ValueError("homepage manifestFile is missing")
    if not isinstance(expected_digest, str) or not SHA256_RE.fullmatch(expected_digest):
        raise ValueError("homepage sha256 is invalid")

    manifest_file = Path(manifest_file_value).resolve()
    manifest = load_json(manifest_file)
    if not isinstance(manifest, dict):
        raise ValueError("homepage manifest is not an object")
    if manifest.get("kind") != "homepage":
        raise ValueError("homepage manifest kind is invalid")
    if manifest.get("sha256") != expected_digest:
        raise ValueError("homepage manifest sha256 disagrees with source batch")

    raw_file = Path(raw_file_value).resolve()
    manifest_raw_value = manifest.get("rawFile")
    if not isinstance(manifest_raw_value, str) or not manifest_raw_value:
        raise ValueError("homepage manifest rawFile is missing")
    manifest_raw_file = resolve_recorded_path(manifest_raw_value, manifest_file)
    if manifest_raw_file != raw_file:
        raise ValueError("homepage rawFile disagrees with manifest")

    body = raw_file.read_bytes()
    computed_digest = hashlib.sha256(body).hexdigest()
    if computed_digest != expected_digest:
        raise ValueError("homepage raw SHA-256 mismatch")
    manifest_bytes = manifest.get("bytes")
    if (
        isinstance(manifest_bytes, bool)
        or not isinstance(manifest_bytes, int)
        or manifest_bytes != len(body)
    ):
        raise ValueError("homepage raw byte count disagrees with manifest")

    return {
        "rawFile": str(raw_file),
        "manifestFile": str(manifest_file),
        "sha256": expected_digest,
        "bytes": len(body),
        "capturedAt": manifest.get("capturedAt") or raw.get("capturedAt"),
        "status": manifest.get("status"),
        "finalUrl": manifest.get("finalUrl"),
        "headers": manifest.get("headers") or raw.get("headers") or {},
    }, body


def detect_platform(body: bytes, headers: Any) -> Tuple[str, str]:
    content = body.lower()
    header_text = json.dumps(headers or {}, ensure_ascii=True).casefold().encode("ascii")
    combined = content + b"\n" + header_text
    application = "unknown"
    for name, markers in PLATFORM_MARKERS:
        if any(marker in combined for marker in markers):
            application = name
            break

    edge = "unknown"
    if b"cf-ray" in header_text or b"cloudflare" in header_text:
        edge = "cloudflare"
    elif b"x-akamai" in header_text or b"akamai" in header_text:
        edge = "akamai"
    elif b"x-vercel" in header_text or b"vercel" in header_text:
        edge = "vercel"
    elif b"x-amz-cf-" in header_text or b"cloudfront" in header_text:
        edge = "cloudfront"
    return application, edge


def deterministic_shard(host: str, platform: str, country: str, shard_count: int) -> int:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    key = (host + "\0" + platform + "\0" + country).encode("utf-8")
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % shard_count


def navigation_workflow(index_url: str) -> Dict[str, Any]:
    return {
        "entryPoint": {
            "action": "navigate-recorded-url",
            "url": index_url,
            "urlSource": "source.indexUrl",
        },
        "steps": [
            {
                "order": 1,
                "action": "inspect-visible-navigation",
                "visibleTextSignals": [
                    "Graduate",
                    "Postgraduate",
                    "Master",
                    "Programs",
                    "Courses",
                    "Academics",
                    "Study",
                    "Degrees",
                ],
                "constraints": [
                    "Use only links or controls present in the rendered DOM.",
                    "Keep navigation on an approved official domain.",
                    "Do not derive a URL from a label or domain.",
                ],
            },
            {
                "order": 2,
                "action": "expand-visible-menus-and-inspect-links",
                "constraints": [
                    "Click only visible menu controls.",
                    "Record the DOM-provided href before following a link.",
                    "Do not construct catalogue paths.",
                ],
            },
            {
                "order": 3,
                "action": "use-visible-site-search-if-present",
                "queries": [
                    "master programs",
                    "postgraduate programs",
                    "graduate degrees",
                ],
                "constraints": [
                    "Use only a search control visible in the rendered DOM.",
                    "Submit through the visible form or control.",
                    "Do not infer or construct a search endpoint.",
                ],
            },
            {
                "order": 4,
                "action": "capture-discovered-evidence",
                "constraints": [
                    "Preserve rendered DOM and manifest before extracting links.",
                    "Accept only DOM-provided URLs on approved official domains.",
                    "Record source page, anchor text, href, final URL, and hash.",
                ],
            },
        ],
        "successCondition": "At least one official master or postgraduate catalogue link is observed in rendered DOM.",
        "noResultStatus": "no-visible-catalog-navigation",
    }


def exclusion_reason(target: Any) -> Optional[str]:
    if not isinstance(target, dict):
        return "invalid-record"
    if target.get("officialVerificationStatus") != "verified":
        return "not-verified"
    if (target.get("catalogDiscovery") or {}).get("status") != "no-candidates":
        return "not-no-candidates"
    domains = normalize_domains(target.get("officialDomains"))
    if not domains:
        return "official-domains-incomplete"
    index_url = target.get("indexUrl")
    if not isinstance(index_url, str) or not index_url:
        return "recorded-homepage-missing"
    parts = urlsplit(index_url)
    host = normalize_host(index_url)
    if parts.scheme.casefold() not in {"http", "https"} or not host:
        return "recorded-homepage-invalid"
    if not host_is_official(host, domains):
        return "recorded-homepage-not-official"
    return None


def build_queue(
    targets: Any,
    shard_count: int = DEFAULT_SHARD_COUNT,
    generated_at: Optional[str] = None,
    source_file: str = "scraper/playwright/top500_verified_zero_catalog_discovery_batch_v4.json",
) -> Dict[str, Any]:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if not isinstance(targets, list):
        raise ValueError("source batch must be a JSON array")

    items = []
    exclusions = Counter()
    seen_ids = set()
    for target in targets:
        reason = exclusion_reason(target)
        if reason is not None:
            exclusions[reason] += 1
            continue

        university_id = target.get("universityId")
        if not isinstance(university_id, str) or not university_id:
            exclusions["university-id-missing"] += 1
            continue
        if university_id in seen_ids:
            exclusions["duplicate-university-id"] += 1
            continue

        try:
            source_raw, body = verify_homepage_raw(target)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            exclusions["homepage-raw-hash-verification-failed"] += 1
            continue

        seen_ids.add(university_id)
        domains = normalize_domains(target.get("officialDomains"))
        index_url = target["indexUrl"]
        host = normalize_host(index_url)
        application_platform, edge_platform = detect_platform(
            body, source_raw.get("headers")
        )
        country = str(target.get("country") or "")
        shard = deterministic_shard(host, application_platform, country, shard_count)
        partition_key = "|".join((host, application_platform, country))
        items.append({
            "taskId": "zero-catalog-browser-navigation:" + university_id,
            "universityId": university_id,
            "name": target.get("name"),
            "country": country,
            "region": target.get("region") or "",
            "url": index_url,
            "kind": "program-catalog-navigation",
            "purpose": "discover-master-catalog-via-visible-navigation-or-site-search",
            "officialDomains": domains,
            "host": host,
            "platform": application_platform,
            "edgePlatform": edge_platform,
            "partitionKey": partition_key,
            "shard": shard,
            "sourceRaw": {
                key: value for key, value in source_raw.items() if key != "headers"
            },
            "sourceCatalogDiscovery": {
                "status": "no-candidates",
                "method": (target.get("catalogDiscovery") or {}).get("method"),
                "networkRequested": (target.get("catalogDiscovery") or {}).get(
                    "networkRequested"
                ),
            },
            "workflow": navigation_workflow(index_url),
            "captchaPolicy": {
                "detectBeforeEveryAction": True,
                "onDetection": "stop",
                "resultStatus": "blocked",
                "bypassAllowed": False,
                "manualSolveAllowed": False,
                "preserveRenderedEvidence": True,
            },
            "status": "pending",
        })

    items.sort(
        key=lambda item: (
            item["host"],
            item["platform"],
            item["country"].casefold(),
            str(item.get("name") or "").casefold(),
            item["universityId"],
        )
    )
    for position, item in enumerate(items):
        item["queuePosition"] = position

    platform_counts = Counter(item["platform"] for item in items)
    edge_counts = Counter(item["edgePlatform"] for item in items)
    country_counts = Counter(item["country"] for item in items)
    host_counts = Counter(item["host"] for item in items)
    shard_counts = Counter(str(item["shard"]) for item in items)
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at or utc_now(),
        "sourceFile": source_file,
        "policy": {
            "networkAccessUsedByBuilder": False,
            "browserExecutionPerformedByBuilder": False,
            "verifiedInstitutionsOnly": True,
            "sourceStatusRequired": "no-candidates",
            "homepageRawHashVerificationRequired": True,
            "entryUrlsCopiedFromSourceOnly": True,
            "guessedUrlsAllowed": False,
            "searchEndpointConstructionAllowed": False,
            "visibleDomElementsOnly": True,
            "captchaAction": "stop",
            "captchaBypassAllowed": False,
        },
        "priority": ["host:asc", "platform:asc", "country:asc", "universityId:asc"],
        "shardStrategy": {
            "scope": "all-items",
            "groupingPriority": ["host", "platform", "country"],
            "groupKey": "host-null-platform-null-country",
            "algorithm": "sha256-group-key-first-8-bytes-modulo",
            "count": shard_count,
        },
        "summary": {
            "sourceRows": len(targets),
            "eligibleTasks": len(items),
            "excludedRows": sum(exclusions.values()),
            "exclusionCounts": dict(sorted(exclusions.items())),
            "uniqueHosts": len(host_counts),
            "hostCounts": dict(sorted(host_counts.items())),
            "platformCounts": dict(sorted(platform_counts.items())),
            "edgePlatformCounts": dict(sorted(edge_counts.items())),
            "countryCounts": dict(sorted(country_counts.items())),
            "shardCounts": dict(sorted(shard_counts.items(), key=lambda row: int(row[0]))),
            "statusCounts": {"pending": len(items)},
        },
        "items": items,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--shards", type=int, default=DEFAULT_SHARD_COUNT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    queue = build_queue(
        load_json(args.input),
        shard_count=args.shards,
        source_file=str(args.input.resolve()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(queue["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
