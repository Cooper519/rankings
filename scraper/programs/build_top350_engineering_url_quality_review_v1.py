"""Build a deterministic, URL-only quality review for the Top 350 export.

The builder reads only the existing engineering priority queue and its URL-only
text export.  It does not read raw manifests, use the network, or expose
application requirements.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent.parent
PRIORITY_QUEUE = ROOT / "scraper" / "playwright" / "top500_engineering_priority_queue_v4.json"
URL_EXPORT = ROOT / "scraper" / "playwright" / "top350_cs_engineering_official_urls_v1.txt"
OUTPUT = ROOT / "scraper" / "playwright" / "top350_cs_engineering_url_quality_review_v1.json"
SPECIFIC_URL_OUTPUT = ROOT / "scraper" / "playwright" / "top350_cs_engineering_specific_official_urls_v2.txt"


NON_PROGRAM_RULES: Tuple[Tuple[str, re.Pattern, str], ...] = (
    (
        "editorial-search-legal",
        re.compile(
            r"/(?:news|noticies|events?|stories|story|blogs?|articles?|press|media|search|website-disclaimer)(?:/|$)|\.rss$",
            re.IGNORECASE,
        ),
        "URL path identifies an editorial, search, feed, or legal page rather than a programme or programme catalogue.",
    ),
    (
        "corporate-organization-research",
        re.compile(
            r"/(?:companies|about-lut|research|governance|campuses|universite/international|educational-initiatives)(?:/|$)",
            re.IGNORECASE,
        ),
        "URL path identifies a corporate, organizational, research, governance, campus, or institutional-initiative page rather than a programme or programme catalogue.",
    ),
    (
        "services-facilities-campus-life",
        re.compile(
            r"/(?:it-services|quality-system|rooms|university-life|what-do-you-need|administrative-procedures|appointments|mailbox|grants-and-financial-aid|new-students|organizing-your-studies-and-where-to-go-for-advice)(?:/|$)",
            re.IGNORECASE,
        ),
        "URL path identifies an administrative service, facility, funding, or campus-life page rather than a programme or programme catalogue.",
    ),
)

FIB_GENERIC_PATH = re.compile(r"^/en/fib(?:/|$)", re.IGNORECASE)
NON_MASTER_DEGREE_PATH = re.compile(
    r"(?:^|[./_-])(?:undergraduate|bachelors?|doctoral|doctorate|phd)(?:[./_-]|$)",
    re.IGNORECASE,
)
MALFORMED_TRACKING_PATH = re.compile(r"(?:^|/)(?:&|%26)utm_[a-z0-9_%-]+=", re.IGNORECASE)
GENERIC_DIRECTORY_PATH = re.compile(r"/by-areas-of-knowledge/", re.IGNORECASE)


KNOWN_INSTITUTION_ALIAS_SETS = {
    frozenset(("u_radboud_university", "u_radboud_university_nijmegen")),
    frozenset(("u_catholic_university_of_sacred_heart", "u_universita_cattolica_del_sacro_cuore")),
    frozenset(("u_university_of_wuerzburg", "u_university_of_wurzburg")),
    frozenset((
        "u_friedrich_alexander_universitat_erlangen_nurnberg",
        "u_university_of_erlangen_nuremberg",
    )),
    frozenset((
        "u_the_university_of_new_south_wales_unsw_sydney",
        "u_unsw_sydney",
    )),
}

# Canonical IDs in the source retain Unicode spellings.  Canonicalize only for
# matching audited identity pairs; output always preserves the source IDs.
CANONICAL_ID_TRANSLITERATIONS = {
    "u_universit\u00e0_cattolica_del_sacro_cuore": "u_universita_cattolica_del_sacro_cuore",
    "u_university_of_w\u00fcrzburg": "u_university_of_wurzburg",
    "u_friedrich_alexander_universit\u00e4t_erlangen_n\u00fcrnberg": (
        "u_friedrich_alexander_universitat_erlangen_nurnberg"
    ),
}

KNOWN_CROSS_INSTITUTION_RISK_SET = frozenset((
    "u_autonomous_university_of_barcelona",
    "u_university_of_barcelona",
))

def load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("priority queue must be a JSON object")
    return value


def load_url_lines(path: Path) -> List[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def obvious_non_program_finding(url: str) -> Optional[Dict[str, str]]:
    parts = urlsplit(url)
    path = parts.path or "/"
    if path == "/" and not parts.query:
        return {
            "category": "obvious-non-program-catalog",
            "subcategory": "generic-domain-root",
            "reason": "A bare domain root is not a specific programme or programme-catalog URL.",
        }
    if NON_MASTER_DEGREE_PATH.search(f"{parts.hostname or ''}{path}"):
        return {
            "category": "obvious-non-program-catalog",
            "subcategory": "non-master-degree-level",
            "reason": "URL path explicitly identifies an undergraduate, bachelor, doctoral, or PhD page outside the master's product scope.",
        }
    for subtype, pattern, reason in NON_PROGRAM_RULES:
        if pattern.search(path):
            return {
                "category": "obvious-non-program-catalog",
                "subcategory": subtype,
                "reason": reason,
            }
    if parts.hostname and parts.hostname.casefold() == "www.fib.upc.edu" and FIB_GENERIC_PATH.search(path):
        return {
            "category": "obvious-non-program-catalog",
            "subcategory": "generic-school-information",
            "reason": "URL path identifies general school information rather than a programme or programme catalogue.",
        }
    return None


def tracking_path_suggestion(url: str) -> str:
    parts = urlsplit(url)
    match = MALFORMED_TRACKING_PATH.search(parts.path)
    if not match:
        return url
    path = parts.path[:match.start()].rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def malformed_tracking_finding(url: str) -> Optional[Dict[str, str]]:
    if not MALFORMED_TRACKING_PATH.search(urlsplit(url).path):
        return None
    return {
        "category": "malformed-tracking-path",
        "subcategory": "utm-parameters-embedded-in-path",
        "reason": "Tracking parameters are embedded in the URL path after '/&utm_' instead of being encoded as query parameters.",
        "suggestedUrl": tracking_path_suggestion(url),
    }


def canonical_match_id(canonical_id: str) -> str:
    return CANONICAL_ID_TRANSLITERATIONS.get(canonical_id, canonical_id)


def canonical_records(items: Iterable[Mapping[str, Any]]) -> List[Dict[str, Optional[str]]]:
    by_id: Dict[str, set] = defaultdict(set)
    for item in items:
        canonical_id = str(item.get("canonicalId") or "").strip()
        if not canonical_id:
            raise ValueError("every priority queue item must have canonicalId")
        name = item.get("universityName")
        by_id[canonical_id].add(None if name is None else str(name))
    result = []
    for canonical_id in sorted(by_id):
        names = sorted(by_id[canonical_id], key=lambda value: (value is None, str(value).casefold()))
        result.append({"canonicalId": canonical_id, "universityName": names[0]})
    return result


def classify_duplicate(
    url: str,
    records: Sequence[Mapping[str, Optional[str]]],
    non_program: Optional[Mapping[str, str]],
) -> Tuple[str, str]:
    identity_set = frozenset(canonical_match_id(str(row["canonicalId"])) for row in records)
    if identity_set in KNOWN_INSTITUTION_ALIAS_SETS:
        if non_program:
            return (
                "same-institution-alias-non-program-url",
                "The same non-program URL is assigned to canonical IDs that are audited naming variants of one institution.",
            )
        return (
            "same-institution-alias",
            "The same official programme URL is assigned to canonical IDs that are audited naming variants of one institution.",
        )
    if identity_set == KNOWN_CROSS_INSTITUTION_RISK_SET:
        if GENERIC_DIRECTORY_PATH.search(urlsplit(url).path):
            return (
                "generic-directory-cross-institution-mapping-risk",
                "A generic UAB subject directory is assigned to both Autonomous University of Barcelona and University of Barcelona; this is an identity-mapping risk, not evidence of a shared programme.",
            )
        return (
            "cross-institution-mapping-risk",
            "The same official URL is assigned to two distinct Barcelona institutions and requires identity review.",
        )
    return (
        "unclassified-cross-canonical",
        "The same URL is assigned to multiple canonical IDs; no audited alias or shared-programme rule resolves the identity relationship.",
    )


def build_review(
    priority_queue: Mapping[str, Any],
    text_urls: Sequence[str],
    input_metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    items = priority_queue.get("items") or []
    if not isinstance(items, list):
        raise ValueError("priority queue items must be a list")
    if len(text_urls) != len(set(text_urls)):
        raise ValueError("URL text export must contain unique, non-empty lines")

    items_by_url: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("every priority queue item must be an object")
        url = str(item.get("url") or "").strip()
        if not url:
            raise ValueError("every priority queue item must have a URL")
        items_by_url[url].append(item)

    json_urls = set(items_by_url)
    text_url_set = set(text_urls)
    if json_urls != text_url_set:
        raise ValueError(
            "priority queue and URL text export differ: %d JSON-only, %d text-only"
            % (len(json_urls - text_url_set), len(text_url_set - json_urls))
        )

    duplicate_groups = []
    duplicate_by_url: Dict[str, Dict[str, Any]] = {}
    for url in sorted(items_by_url):
        records = canonical_records(items_by_url[url])
        if len(records) <= 1:
            continue
        non_program = obvious_non_program_finding(url)
        classification, reason = classify_duplicate(url, records, non_program)
        group = {
            "url": url,
            "category": "cross-canonical-duplicate",
            "classification": classification,
            "reason": reason,
            "canonicalRecords": records,
            "recordCount": len(items_by_url[url]),
        }
        duplicate_groups.append(group)
        duplicate_by_url[url] = group

    url_reviews = []
    category_counts = Counter()
    subcategory_counts = Counter()
    status_counts = Counter()
    for url in sorted(text_url_set):
        findings: List[Dict[str, Any]] = []
        non_program = obvious_non_program_finding(url)
        if non_program:
            findings.append(non_program)
        malformed = malformed_tracking_finding(url)
        if malformed:
            findings.append(malformed)
        duplicate = duplicate_by_url.get(url)
        if duplicate:
            findings.append({
                "category": duplicate["category"],
                "subcategory": duplicate["classification"],
                "reason": duplicate["reason"],
            })
        for finding in findings:
            category_counts[finding["category"]] += 1
            subcategory_counts[finding["subcategory"]] += 1
        status = "review" if findings else "pass"
        status_counts[status] += 1
        url_reviews.append({
            "url": url,
            "status": status,
            "findings": findings,
            "canonicalRecords": canonical_records(items_by_url[url]),
        })

    duplicate_classification_counts = Counter(
        group["classification"] for group in duplicate_groups
    )
    reviewed_count = len(url_reviews)
    obvious_count = category_counts["obvious-non-program-catalog"]
    malformed_count = category_counts["malformed-tracking-path"]
    duplicate_count = category_counts["cross-canonical-duplicate"]
    metadata = dict(input_metadata or {})
    metadata.update({
        "priorityQueueSchemaVersion": priority_queue.get("schemaVersion"),
        "priorityQueueGeneratedAt": priority_queue.get("generatedAt"),
        "priorityQueueRecordCount": len(items),
        "priorityQueueUniqueUrlCount": len(json_urls),
        "urlExportLineCount": len(text_urls),
        "urlExportUniqueUrlCount": len(text_url_set),
        "urlSetsMatch": True,
    })
    return {
        "schemaVersion": 1,
        "auditScope": "Deterministic URL-only quality review for the Top 350 CS/Engineering official URL export.",
        "policy": {
            "networkAccessUsed": False,
            "rawManifestsRead": False,
            "urlExportGeneratorModified": False,
            "frontendDataReadOrModified": False,
            "applicationDetailFieldsIncluded": False,
            "ambiguousUrlsDefaultToPass": True,
        },
        "inputs": metadata,
        "summary": {
            "reviewedUniqueUrlCount": reviewed_count,
            "statusCounts": {name: status_counts[name] for name in ("pass", "review")},
            "findingCategoryCounts": {
                "obvious-non-program-catalog": obvious_count,
                "malformed-tracking-path": malformed_count,
                "cross-canonical-duplicate": duplicate_count,
            },
            "findingSubcategoryCounts": dict(sorted(subcategory_counts.items())),
            "obviousNonProgramCatalogRatio": round(obvious_count / reviewed_count, 6) if reviewed_count else 0.0,
            "obviousNonProgramCatalogPercent": round(100.0 * obvious_count / reviewed_count, 3) if reviewed_count else 0.0,
            "malformedTrackingPathRatio": round(malformed_count / reviewed_count, 6) if reviewed_count else 0.0,
            "crossCanonicalDuplicateGroupCount": len(duplicate_groups),
            "crossCanonicalDuplicateRecordExcess": sum(group["recordCount"] - 1 for group in duplicate_groups),
            "duplicateClassificationCounts": dict(sorted(duplicate_classification_counts.items())),
            "confirmedSharedProgrammeDirectoryCount": 0,
        },
        "rules": {
            "obviousNonProgramCatalog": "Conservative URL-path rules; ambiguous programme, admission, curriculum, faculty, and localized paths are not rejected.",
            "nonMasterDegreeLevel": "Explicit undergraduate, bachelor, doctoral, and PhD URL paths are outside the master's product scope.",
            "malformedTrackingPath": "A /&utm_* or /%26utm_* token in the URL path is malformed tracking data.",
            "crossCanonicalDuplicate": "Exact URL equality combined with more than one distinct canonicalId.",
        },
        "urlReviews": url_reviews,
        "crossCanonicalDuplicateGroups": duplicate_groups,
    }


def specific_url_lines(review: Mapping[str, Any]) -> List[str]:
    """Return only URLs without a deterministic non-program finding."""
    lines = []
    for row in review.get("urlReviews") or []:
        if not isinstance(row, dict):
            continue
        findings = row.get("findings") or []
        if any(
            isinstance(finding, dict)
            and finding.get("category") == "obvious-non-program-catalog"
            for finding in findings
        ):
            continue
        url = str(row.get("url") or "").strip()
        if url:
            lines.append(url)
    return lines


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--priority-queue", type=Path, default=PRIORITY_QUEUE)
    parser.add_argument("--url-export", type=Path, default=URL_EXPORT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--specific-url-output", type=Path, default=SPECIFIC_URL_OUTPUT)
    return parser.parse_args(argv)


def relative_input_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    priority_queue = load_json(args.priority_queue)
    text_urls = load_url_lines(args.url_export)
    result = build_review(
        priority_queue,
        text_urls,
        input_metadata={
            "priorityQueuePath": relative_input_path(args.priority_queue),
            "priorityQueueSha256": sha256_file(args.priority_queue),
            "urlExportPath": relative_input_path(args.url_export),
            "urlExportSha256": sha256_file(args.url_export),
        },
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    specific_urls = specific_url_lines(result)
    args.specific_url_output.parent.mkdir(parents=True, exist_ok=True)
    args.specific_url_output.write_text(
        "\n".join(specific_urls) + ("\n" if specific_urls else ""),
        encoding="utf-8",
    )
    print(
        "[top350-engineering-url-quality-review] wrote %d specific URLs and %d duplicate groups to %s"
        % (
            len(specific_urls),
            result["summary"]["crossCanonicalDuplicateGroupCount"],
            args.specific_url_output,
        )
    )


if __name__ == "__main__":
    main()
