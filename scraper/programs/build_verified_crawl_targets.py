"""Build raw crawl and review queues from official-site verification evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "scraper" / "playwright" / "top500_official_website_verification_v3.json"
DEFAULT_STATIC = ROOT / "scraper" / "playwright" / "top500_verified_static_crawl_targets.json"
DEFAULT_BROWSER = ROOT / "scraper" / "playwright" / "top500_blocked_browser_queue.json"
DEFAULT_REVIEW = ROOT / "scraper" / "playwright" / "top500_official_review_queue.json"
DEFAULT_AUDIT = ROOT / "scraper" / "playwright" / "top500_official_target_conversion_audit.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    raise ValueError("input must be an array or contain items")


def host(value: str) -> str:
    try:
        result = (urlsplit(value).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""
    return result[4:] if result.startswith("www.") else result


def candidate_evidence(item: dict) -> tuple[list[str], str]:
    verification = item.get("verification") or {}
    evidence = verification.get("evidence") or {}
    consistency = evidence.get("domainConsistency") or {}
    live = evidence.get("liveOfficialPage") or {}
    domains = []
    for value in consistency.get("rorDomains") or []:
        domain = str(value).casefold()
        domains.append(domain[4:] if domain.startswith("www.") else domain)
    domains = list(dict.fromkeys(value for value in domains if value))
    index_url = live.get("finalUrl") or live.get("requestedUrl") or consistency.get("candidateUrl") or ""
    return domains, str(index_url)


def common_provenance(item: dict) -> dict:
    verification = item.get("verification") or {}
    evidence = verification.get("evidence") or {}
    registry = item.get("registryResolution") or {}
    return {
        "sourceUniversityIds": item.get("sourceUniversityIds") or [],
        "rankingSources": item.get("rankingSources") or [],
        "rankingAppearances": item.get("rankingAppearances") or [],
        "relationshipIds": item.get("relationshipIds") or [],
        "rorId": (evidence.get("registryIdentity") or {}).get("rorId"),
        "rorRawFile": registry.get("rawFile"),
        "rorRawManifestFile": registry.get("rawManifestFile"),
        "rorRawSha256": registry.get("rawSha256"),
        "officialVerificationReasons": verification.get("reasonCodes") or [],
        "officialHomepageRaw": (evidence.get("liveOfficialPage") or {}).get("raw"),
    }


def build(payload: Any) -> dict:
    source = items(payload)
    seen: set[str] = set()
    static: list[dict] = []
    browser: list[dict] = []
    review: list[dict] = []
    for item in source:
        identifier = str(item.get("canonicalId") or item.get("universityId") or "")
        if not identifier or identifier in seen:
            raise ValueError(f"missing or duplicate canonical id: {identifier}")
        seen.add(identifier)
        status = item.get("verificationStatus")
        domains, index_url = candidate_evidence(item)
        provenance = common_provenance(item)
        base = {
            "universityId": identifier,
            "name": item.get("name") or item.get("universityName") or identifier,
            "country": item.get("country") or "",
            "region": item.get("region") or "",
            "officialDomains": domains,
            "indexUrl": index_url,
            "catalogPages": [],
            "programUrls": [],
            "evidenceUrls": [],
            "apiEndpoints": [],
            "discoveryStrategy": "recursive-catalog",
            "provenance": provenance,
        }
        if status == "verified":
            if not domains or not index_url or not any(host(index_url) == domain or host(index_url).endswith("." + domain) for domain in domains):
                raise ValueError(f"verified target lacks domain-consistent URL: {identifier}")
            static.append({**base, "officialVerificationStatus": status})
        elif status == "blocked":
            browser.append({
                **base,
                "officialVerificationStatus": status,
                "browserAction": "verify-homepage-then-discover-program-catalog",
                "status": "pending",
            })
        else:
            review.append({
                **base,
                "officialVerificationStatus": status,
                "reviewReasonCodes": (item.get("verification") or {}).get("reasonCodes") or [],
                "status": "pending",
            })
    total = len(static) + len(browser) + len(review)
    if total != len(source):
        raise ValueError("queue partition is not exhaustive")
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceCount": len(source),
        "static": static,
        "browser": browser,
        "review": review,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--static-output", type=Path, default=DEFAULT_STATIC)
    parser.add_argument("--browser-output", type=Path, default=DEFAULT_BROWSER)
    parser.add_argument("--review-output", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    result = build(load_json(args.input))
    write_json(args.static_output, result["static"])
    write_json(args.browser_output, result["browser"])
    write_json(args.review_output, result["review"])
    audit = {
        "schemaVersion": 1,
        "generatedAt": result["generatedAt"],
        "source": str(args.input.resolve()),
        "policy": {
            "rorAloneCreatesCrawlTarget": False,
            "verifiedLiveHomepageRequiredForStatic": True,
            "blockedTargetsRequireBrowser": True,
            "reviewAndRejectedRequireResolution": True,
            "cleanedDataModified": False,
        },
        "summary": {
            "source": result["sourceCount"],
            "static": len(result["static"]),
            "browser": len(result["browser"]),
            "review": len(result["review"]),
            "partitionTotal": len(result["static"]) + len(result["browser"]) + len(result["review"]),
        },
        "outputs": {
            "static": str(args.static_output.resolve()),
            "browser": str(args.browser_output.resolve()),
            "review": str(args.review_output.resolve()),
        },
    }
    write_json(args.audit_output, audit)
    print(json.dumps(audit["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
