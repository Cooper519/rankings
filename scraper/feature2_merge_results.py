"""Merge Feature 2 crawl evidence into the frontend coverage payload.

The crawler is deliberately broad because it has to discover links from many
different university CMSs. This module is the conservative boundary: only
URLs on a trusted institution domain and with a specific graduate/programme
signal are allowed into the public coverage file. Rejected crawl URLs remain
auditable in ``feature2_crawl_quality_v1.json``.
"""
from __future__ import annotations

import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping
from urllib.parse import urldefrag, unquote_plus, urlparse

ROOT = Path(__file__).resolve().parent.parent
RESULT_PATHS = (
    ROOT / "scraper" / "playwright" / "feature2_crawl_results.json",
    ROOT / "scraper" / "playwright" / "feature2_crawl_results2.json",
    ROOT / "scraper" / "playwright" / "feature2_crawl_results_recovery.json",
)
SCOPE = ROOT / "scraper" / "playwright" / "top350_cs_engineering_feature2_scope_v1.json"
REVIEW_PATH = ROOT / "scraper" / "playwright" / "top350_cs_engineering_url_quality_review_v1.json"
AUDIT = ROOT / "scraper" / "programs" / "top500_targets_audit_v3.json"
VERIFICATION = ROOT / "scraper" / "playwright" / "top500_official_website_verification_v3.json"
APPLICATION_AUDIT = ROOT / "scraper" / "playwright" / "top500_engineering_application_evidence_audit_v4.json"
OLD_RAW = ROOT / "scraper" / "playwright" / "_programs_full_raw"
NEW_RAW = ROOT / "scraper" / "playwright" / "_top500_programs_raw"
CAPTURED_RAW_ROOTS = (
    OLD_RAW,
    NEW_RAW,
    ROOT / "scraper" / "playwright" / "_top500_catalog_discovery_raw_v4",
    ROOT / "scraper" / "playwright" / "_top500_browser_recovered_raw_v4",
    ROOT / "scraper" / "playwright" / "_top350_engineering_url_recovery_batch_01_raw",
    ROOT / "scraper" / "playwright" / "_top350_engineering_browser_recovered_raw_v1",
    ROOT / "scraper" / "playwright" / "feature2_static_raw_v1",
    ROOT / "scraper" / "playwright" / "feature2_static_raw_v2",
)
FRONTEND_COVERAGE = ROOT / "frontend" / "public" / "data" / "feature2_coverage.json"
QUALITY_REPORT = ROOT / "scraper" / "playwright" / "feature2_crawl_quality_v1.json"

SPECIFIC = re.compile(r"(?:\bmaster(?:s)?\b|\bpostgraduate\b|\bgraduate\b|\bgrad(?:uate)?[-_ ]?school\b|\bm\.sc\b|\bmsc\b|\bdegree(?:s)?\b|\bprogram(?:me)?s?\b|\bcourse(?:s)?\b|\bcurriculum\b|\bcatalog\b)", re.I)
GRADUATE_LEVEL = re.compile(r"(?:\bmaster(?:s)?\b|\bpostgraduate\b|\bgraduate\b|\bgrad[-_ ]?school\b|\bm\.sc\b|\bmsc\b)", re.I)
CATALOG_SIGNAL = re.compile(r"(?:\bdegree(?:s)?\b|\bprogram(?:me)?s?\b|\bcourse(?:s)?\b|\bcurriculum\b|\bcatalog\b)", re.I)
WRONG_LEVEL = re.compile(r"(?:undergraduate|bachelor)", re.I)
DOCTORAL_LEVEL = re.compile(r"(?:\bdoctoral\b|\bdoctorate\b|\bphd\b|\bph\.d\b)", re.I)
NON_MASTER_QUALIFICATION = re.compile(
    r"(?:\b(?:graduate|postgraduate|post[-_ ]?bacc(?:alaureate)?)\b[-_/ ]*"
    r"(?:certificate|diploma|minor)\b|\b(?:cert|certificates?|diplomas?|minors?)\b)",
    re.I,
)
NOISE = re.compile(r"(?:/news(?:/|$)|/story(?:/|$)|/events?(?:/|$)|/calendar(?:/|$)|/blog(?:/|$)|/careers?(?:/|$)|/jobs?(?:/|$)|\bresearch\b|\bforschung\b|\bcalendars?\b|free[-_ ]?speech|trustees?|privacy|accessibility|feedback|donate|alumni)", re.I)
NON_PROGRAM_DETAIL = re.compile(
    r"(?:/(?:fees?(?:[-_/ ]funding)?|funding|tuition(?:[-_ ]fees)?|scholarships?|"
    r"financial[-_ ]aid|accommodation|housing)(?:/|$)|masters?[-_ ]?thesis|"
    r"master[-_ ]?labs?|master[-_ ]?students?|oferty[-_ ]?pracy)",
    re.I,
)
AGGREGATOR = re.compile(r"(?:standyou|mastersportal|studyportals|findamasters|globalstudyprep|studyabroad|hotcourses|student\.com|wikipedia)", re.I)
APPLICATION_NOISE = re.compile(
    r"(?:mentor(?:ing)?[-_ ]?program|graduate[-_ ]student[-_ ]life|"
    r"exchange[-_ ]program|graduate[-_ ]groups?)",
    re.I,
)
APPLICATION_CATALOG_ENDPOINT = re.compile(
    r"/(?:online[-_])?(?:graduate(?:[-_ ]program(?:me)?s?)?|"
    r"masters?(?:[-_ ]program(?:me)?s?)?|postgraduate(?:[-_]\d+)?|"
    r"graduate[-_]english)(?:\.(?:html?|php|aspx?))?/?$",
    re.I,
)
POSTGRADUATE_GUIDE = re.compile(r"(?:postgrad|postgraduate).*(?:guide|handbook)", re.I)
CS_ENGINEERING_URL = re.compile(
    r"\b(?:computer[-_ ]science|computing|informatics|information[-_ ]technology|"
    r"software|data[-_ ]science|artificial[-_ ]intelligence|machine[-_ ]learning|"
    r"cyber[-_ ]?security|robotics|engineering|electrical|electronics|mechanical|"
    r"civil|chemical|biomedical|aerospace|environmental|energy|materials|"
    r"industrial|mechatronics|automation|manufacturing)\b",
    re.I,
)
CAPTURED_MASTER_LEVEL = re.compile(
    r"(?:\bmaster(?:'?s)?\b|\bmsc\b|\bm\.sc\b|\bm\.?s\.?\b|\bmeng\b|\bm\.eng\b|"
    r"\bpostgraduate\b|\bgraduate\b|\blaurea magistrale\b)",
    re.I,
)
CAPTURED_CATALOG_TITLE = re.compile(
    r"(?:\bmaster(?:'?s)?(?:[-\s/&]+(?:degree|study|academic|taught|coursework|professional))*"
    r"[-\s/&]+(?:programmes|programs|degrees?|courses?|catalog(?:ue)?|studies)\b|"
    r"\b(?:postgraduate|graduate)(?:[-\s/&]+(?:degree|academic|taught|coursework|professional))*"
    r"[-\s/&]+(?:programmes|programs|degrees?|courses?|catalog(?:ue)?)\b|"
    r"\bfind your master\b|\brange of degree programmes\b|"
    r"\ba[- ]?z of postgraduate\b|\bsearch programmes and courses\b)",
    re.I,
)
CAPTURED_CATALOG_ENDPOINT = re.compile(
    r"(?:^(?:masters?|postgraduate|graduate)$|"
    r"^(?:masters?|postgraduate|graduate)[-_](?:degree[-_])?(?:programmes?|programs?|degrees?|courses?|studies)$|"
    r"^(?:graduate[-_])?degree[-_](?:programmes?|programs?)$|"
    r"^(?:programmes?|programs?)[-_](?:graduate|postgraduate|masters?)$|"
    r"^(?:programmes?|programs?)[-_]of[-_]study$|"
    r"^(?:search|find)[-_](?:graduate[-_]|postgraduate[-_]|masters?[-_])?(?:programmes?|programs?|courses?)$|"
    r"^degree[-_](?:programmes?|programs?)\.(?:html?|aspx?)$)",
    re.I,
)
CAPTURED_PAGE_NOISE = re.compile(
    r"(?:\b(?:apply|application|admissions?|requirements?|deadline|tuition|fees?|funding|"
    r"scholarships?|financial|aid|contact|faq|open[- ]?day|orientation|language|cv form|"
    r"selection procedure|thesis|student life|awards?|giving|polic(?:y|ies)|guidance|"
    r"registration|register|current students?|future students?|coming soon|time to degree|awarded|"
    r"promoting excellence|accelerated|email updates?|timetables?|schedules?|advisors?|approvals?)\b|page not found|not found|"
    r"what is (?:a )?postgraduate|everything you need to know|graduate resources?|check\s*list|"
    r"request information|types? of postgraduate degrees?|wordpress at)",
    re.I,
)
CAPTURED_ORGANIZATION_NOISE = re.compile(
    r"(?:\b(?:board|council|office|committee|alumni|resources?|student life)\b)",
    re.I,
)
CAPTURED_BACHELOR_LEVEL = re.compile(
    r"(?:\bundergraduate\b|\bbachelor(?:'?s)?\b|\bb\.?sc\.?\b|\bb\.?eng\.?\b|"
    r"\bb\.?a\.?\b|\bb\.?tech\.?\b|\bbs\s*/\s*ms\b)",
    re.I,
)
CAPTURED_NON_SCOPE_CATALOG = re.compile(
    r"(?:\b(?:medicine|medical|nursing|clinical|health|business|finance|law|humanities|"
    r"theology|education|architecture|bioethics|professional development|professional studies|"
    r"transdisciplinary)\b|\b(?:school|faculty|department) of arts?\b(?!\s+and\s+sciences?))",
    re.I,
)
CAPTURED_NON_ENGINEERING_SCIENCE = re.compile(
    r"(?:\bearth and environmental sciences?\b|\benvironmental sciences?\b|"
    r"\bbiological and biomedical sciences?\b|\bbiomedical sciences?\b)",
    re.I,
)
CAPTURED_URL_NOISE = re.compile(
    r"/(?:[^/?#]*/)*(?:financial[^/?#]*|scholarships?|awards?|giving|polic(?:y|ies)|"
    r"guidance|registration|current[^/?#]*students?|future[-_]students?|coming[-_]soon|"
    r"finance[-_]your[-_]masters?[-_]degree|register[^/?#]*|join[-_]us|why[-_][^/?#]+|"
    r"strategic[-_]priorities|degree[-_]types|[^/?#]*(?:timetables?|schedules?|check[-_]?list|"
    r"resources?|request[-_]information)[^/?#]*)(?:\.[^/?#]+)?(?:/|$)",
    re.I,
)
CAPTURED_CENTRAL_SUBDOMAIN = re.compile(
    r"^(?:www|study|online|catalog|grad|graduate|graduateschool|gradschool|gradsch|gsas|rackham|"
    r"sgs|pg|pgcollege|postgraduate|programs|programmes|university)$",
    re.I,
)


def load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return default


def host(value: str) -> str:
    parsed = urlparse(value or "")
    value = (parsed.hostname or value or "").lower().rstrip(".")
    return value[4:] if value.startswith("www.") else value


def domain_matches(value: str, domains: Iterable[str]) -> bool:
    candidate = host(value)
    return any(host(str(domain)) and (candidate == host(str(domain)) or candidate.endswith("." + host(str(domain)))) for domain in domains)


def add_domain(domains: set[str], value: str) -> None:
    candidate = host(value)
    if candidate and "." in candidate:
        domains.add(candidate)


def ror_domains_by_id(verification: Mapping[str, Any] | None = None) -> Dict[str, set[str]]:
    """Collect only name-and-country matched ROR domains, independent of manifests."""
    result: Dict[str, set[str]] = defaultdict(set)
    verification = verification if verification is not None else (load(VERIFICATION, {}) or {})
    for item in verification.get("items") or []:
        evidence = ((item.get("verification") or {}).get("evidence") or {}).get("registryIdentity") or {}
        if not (evidence.get("nameMatch") and evidence.get("countryMatch")):
            continue
        ids = [item.get("canonicalId")] + list(item.get("sourceUniversityIds") or [])
        org = item.get("rorOrganization") or {}
        domains = set(str(value) for value in org.get("domains") or [])
        for link in org.get("links") or []:
            if link.get("type") == "website":
                domains.add(str(link.get("value") or ""))
        for identifier in ids:
            if identifier:
                for value in domains:
                    add_domain(result[identifier], value)
    return result


def trusted_domains_by_id() -> Dict[str, set[str]]:
    """Collect domains from captured manifests and identity-matched ROR data."""
    result: Dict[str, set[str]] = defaultdict(set)
    audit = load(AUDIT, {}) or {}
    for entity in audit.get("entities") or []:
        cid = entity.get("canonicalId")
        if not cid:
            continue
        for root, ids in ((OLD_RAW, entity.get("existingRawTargetIds") or []), (NEW_RAW, [cid])):
            for target_id in ids:
                manifest = load(root / str(target_id) / "manifest.json", {}) or {}
                for value in manifest.get("officialDomains") or []:
                    add_domain(result[cid], str(value))
    for cid, domains in ror_domains_by_id().items():
        result[cid].update(domains)
    return result


def normalize_url(value: Any) -> str:
    raw = html.unescape(str(value or "")).strip()
    raw, _fragment = urldefrag(raw)
    if not raw:
        return ""
    parsed = urlparse(raw)
    return raw.rstrip("/") if parsed.path not in ("", "/") else raw


def url_signal_text(parsed: Any) -> str:
    """Decode path/query tokens for policy checks while preserving the source URL."""
    return " ".join((
        parsed.hostname or "",
        unquote_plus(parsed.path or ""),
        unquote_plus(parsed.query or ""),
    ))


def accept_crawl_url(row: Mapping[str, Any], item: Mapping[str, Any], trusted: Mapping[str, set[str]]) -> tuple[bool, str, str]:
    url = normalize_url(item.get("url"))
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "invalid-url", url
    if AGGREGATOR.search(url):
        return False, "aggregator", url
    cid = str(row.get("canonicalId") or "")
    domains = trusted.get(cid) or set()
    if not domains:
        return False, "no-trusted-domain", url
    if not domain_matches(parsed.hostname, domains):
        return False, "off-trusted-domain", url
    text = url_signal_text(parsed)
    if not SPECIFIC.search(text):
        return False, "not-specific", url
    if WRONG_LEVEL.search(text):
        return False, "wrong-level", url
    if DOCTORAL_LEVEL.search(text):
        return False, "wrong-level", url
    if NON_MASTER_QUALIFICATION.search(text):
        return False, "non-master-qualification", url
    if NON_PROGRAM_DETAIL.search(text):
        return False, "generic-or-noise", url
    if not GRADUATE_LEVEL.search(text):
        return False, "not-graduate-level", url
    if NOISE.search(text) and not (GRADUATE_LEVEL.search(text) and CATALOG_SIGNAL.search(text)):
        return False, "generic-or-noise", url
    if re.search(r"(?:call[-_ ]?for|announcement)", text, re.I) and not CATALOG_SIGNAL.search(text):
        return False, "announcement", url
    if not parsed.path.strip("/") and not SPECIFIC.search(parsed.hostname or ""):
        return False, "root-url", url
    url_type = str(item.get("type") or "")
    if url_type in {"application-deadline", "admission-requirements", "required-documents", "language-requirements"}:
        if not (GRADUATE_LEVEL.search(text) or CATALOG_SIGNAL.search(text)):
            return False, "generic-admissions", url
    return True, "accepted", url


def review_urls(review: Mapping[str, Any], valid_ids: set[str], trusted: Mapping[str, set[str]]) -> Dict[str, set[str]]:
    result: Dict[str, set[str]] = defaultdict(set)
    for row in review.get("urlReviews") or []:
        if not isinstance(row, dict):
            continue
        findings = [finding for finding in row.get("findings") or [] if isinstance(finding, dict)]
        if any(finding.get("category") == "obvious-non-program-catalog" for finding in findings):
            continue
        if any(finding.get("subcategory") == "generic-directory-cross-institution-mapping-risk" for finding in findings):
            continue
        url = normalize_url(row.get("url"))
        if not url:
            continue
        parsed = urlparse(url)
        review_text = url_signal_text(parsed)
        if (WRONG_LEVEL.search(review_text) or DOCTORAL_LEVEL.search(review_text)
                or NON_MASTER_QUALIFICATION.search(review_text)
                or NON_PROGRAM_DETAIL.search(review_text)):
            continue
        for record in row.get("canonicalRecords") or []:
            cid = str(record.get("canonicalId") or "")
            if cid in valid_ids:
                domains = trusted.get(cid) or set()
                if domains and not domain_matches(url, domains):
                    continue
                result[cid].add(url)
    return result


def accept_application_audit_url(
    canonical_id: str,
    program: Mapping[str, Any],
    ror_trusted: Mapping[str, set[str]],
) -> tuple[bool, str, str]:
    """Apply the stricter policy required for reusing application-audit URLs."""
    if program.get("status") != "captured":
        return False, "application-not-captured", normalize_url(program.get("programUrl"))
    if not program.get("feature2Eligible"):
        return False, "application-out-of-scope", normalize_url(program.get("programUrl"))
    program_cid = str(program.get("canonicalId") or canonical_id)
    if program_cid != canonical_id:
        return False, "application-canonical-id-mismatch", normalize_url(program.get("programUrl"))
    ok, reason, url = accept_crawl_url(
        {"canonicalId": canonical_id},
        {"type": "application-audit", "url": program.get("programUrl")},
        ror_trusted,
    )
    if not ok:
        return False, reason, url
    parsed = urlparse(url)
    text = url_signal_text(parsed)
    if APPLICATION_NOISE.search(text):
        return False, "application-non-program", url
    if APPLICATION_CATALOG_ENDPOINT.search(parsed.path):
        return True, "accepted-application-catalog", url
    if CATALOG_SIGNAL.search(parsed.path) and re.search(r"\bmaster(?:s)?\b", parsed.query, re.I):
        return True, "accepted-application-catalog", url
    if POSTGRADUATE_GUIDE.search(parsed.path):
        return True, "accepted-application-catalog", url
    if re.search(r"\bmaster(?:s)?\b", text, re.I) and CS_ENGINEERING_URL.search(text):
        return True, "accepted-application-scope-program", url
    return False, "application-not-catalog-or-scope-program", url


def application_audit_urls(
    audit: Mapping[str, Any],
    valid_ids: set[str],
    missing_ids: set[str],
    ror_trusted: Mapping[str, set[str]],
) -> tuple[Dict[str, set[str]], list[dict], Counter]:
    """Select high-confidence audit URLs only for schools still missing coverage."""
    result: Dict[str, set[str]] = defaultdict(set)
    accepted: list[dict] = []
    rejected: Counter = Counter()
    for university in audit.get("universities") or []:
        if not isinstance(university, dict):
            continue
        cid = str(university.get("canonicalId") or "")
        if cid not in valid_ids or cid not in missing_ids:
            continue
        for program in university.get("programs") or []:
            if not isinstance(program, dict):
                continue
            ok, reason, url = accept_application_audit_url(cid, program, ror_trusted)
            if ok:
                if url not in result[cid]:
                    accepted.append({"canonicalId": cid, "url": url, "reason": reason})
                result[cid].add(url)
            else:
                rejected[reason] += 1
    return result, accepted, rejected


def raw_target_to_canonical(audit: Mapping[str, Any] | None = None) -> Dict[str, str]:
    """Map raw target aliases without silently resolving identity collisions."""
    audit = audit if audit is not None else (load(AUDIT, {}) or {})
    result: Dict[str, str] = {}
    ambiguous: set[str] = set()
    for entity in audit.get("entities") or []:
        cid = str(entity.get("canonicalId") or "")
        if not cid:
            continue
        identifiers = [cid]
        identifiers.extend(str(value) for value in entity.get("sourceUniversityIds") or [] if value)
        identifiers.extend(str(value) for value in entity.get("existingRawTargetIds") or [] if value)
        if entity.get("existingRawTargetId"):
            identifiers.append(str(entity["existingRawTargetId"]))
        for identifier in identifiers:
            if identifier in result and result[identifier] != cid:
                ambiguous.add(identifier)
            else:
                result[identifier] = cid
    for identifier in ambiguous:
        result.pop(identifier, None)
    return result


def captured_record_title(record: Mapping[str, Any]) -> str:
    return str(record.get("documentTitle") or record.get("title") or "").strip()


def captured_record_final_url(url: str, record: Mapping[str, Any]) -> str:
    return normalize_url(record.get("responseUrl") or record.get("finalUrl") or url)


def captured_record_status_code(record: Mapping[str, Any]) -> int | None:
    for key in ("statusCode", "httpStatus"):
        value = record.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def captured_catalog_endpoint(url: str) -> bool:
    parsed = urlparse(url)
    segments = [unquote_plus(value) for value in parsed.path.rstrip("/").split("/") if value]
    if not segments:
        return False
    last = segments[-1]
    if CAPTURED_CATALOG_ENDPOINT.search(last):
        return True
    if len(segments) >= 2 and re.search(r"master|graduate|postgraduate", segments[-2], re.I):
        return bool(re.fullmatch(r"(?:degree[-_])?(?:programmes?|programs?|degrees?|courses?|overview)(?:\.(?:html?|aspx?))?", last, re.I))
    return False


def captured_catalog_is_central(url: str, domains: Iterable[str]) -> bool:
    candidate = host(url)
    for value in domains:
        domain = host(str(value))
        if not domain:
            continue
        if candidate == domain:
            return True
        if candidate.endswith("." + domain):
            prefix = candidate[: -(len(domain) + 1)]
            if any(CAPTURED_CENTRAL_SUBDOMAIN.fullmatch(label) for label in prefix.split(".")):
                return True
    return False


def captured_url_fingerprint(url: str) -> str:
    parsed = urlparse(normalize_url(url))
    hostname = host(parsed.hostname or "")
    return "|".join((hostname, unquote_plus(parsed.path).casefold().rstrip("/"), unquote_plus(parsed.query).casefold()))


def accept_captured_manifest_url(
    canonical_id: str,
    url: str,
    record: Mapping[str, Any],
    candidate: Mapping[str, Any],
    ror_trusted: Mapping[str, set[str]],
) -> tuple[bool, str, str, int]:
    """Accept a fetched catalogue or a fetched CS/engineering master's page."""
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    if record.get("status") != "captured":
        return False, "captured-not-captured", normalized, 0
    if record.get("blocked") or record.get("dynamicShell"):
        return False, "captured-blocked-or-dynamic", normalized, 0
    if record.get("eligibleAsProgramEvidence") is False:
        return False, "captured-discovery-only", normalized, 0
    if str(record.get("kind") or "").casefold() not in {"program", "category", "catalog"}:
        return False, "captured-wrong-kind", normalized, 0
    status_code = captured_record_status_code(record)
    if status_code is not None and not 200 <= status_code < 400:
        return False, "captured-http-status", normalized, 0
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, "invalid-url", normalized, 0
    domains = ror_trusted.get(canonical_id) or set()
    final_url = captured_record_final_url(normalized, record)
    if not domains:
        return False, "no-ror-domain", normalized, 0
    if not domain_matches(normalized, domains) or not domain_matches(final_url, domains):
        return False, "off-ror-domain", normalized, 0
    if AGGREGATOR.search(normalized):
        return False, "aggregator", normalized, 0

    title = captured_record_title(record)
    candidate_text = str(candidate.get("text") or "")
    record_text = str(record.get("text") or "")
    decoded_url = unquote_plus(normalized)
    surface = " ".join((decoded_url, title, candidate_text, record_text))
    if "page not found" in title.casefold() or re.search(r"\b404\b", title):
        return False, "captured-not-found-page", normalized, 0
    text_length = record.get("textLength")
    if isinstance(text_length, int) and text_length < 400:
        return False, "captured-thin-page", normalized, 0
    if DOCTORAL_LEVEL.search(decoded_url) or NON_MASTER_QUALIFICATION.search(decoded_url):
        return False, "wrong-level", normalized, 0
    if NON_PROGRAM_DETAIL.search(decoded_url) or NOISE.search(decoded_url):
        return False, "generic-or-noise", normalized, 0
    if CAPTURED_URL_NOISE.search(decoded_url):
        return False, "generic-or-noise", normalized, 0

    path_segments = [value for value in parsed.path.rstrip("/").split("/") if value]
    last_segment = unquote_plus(path_segments[-1]) if path_segments else ""
    title_noise = bool(CAPTURED_PAGE_NOISE.search(title))
    last_segment_noise = bool(CAPTURED_PAGE_NOISE.search(last_segment.replace("-", " ")))
    primary_title = re.split(r"\s+(?:\||::|[-–—])\s+", title, maxsplit=1)[0]
    title_catalog = bool(CAPTURED_CATALOG_TITLE.search(primary_title))
    endpoint_catalog = captured_catalog_endpoint(normalized)
    combined_school_catalog = bool(
        re.fullmatch(r"(?:programmes?|programs?|degrees?|courses?|(?:programmes?|programs?)[-_]of[-_]study)", last_segment, re.I)
        and re.search(
            r"(?:\b(?:programmes?|programs?|degrees?|courses?)\b.{0,80}\b(?:graduate|postgraduate|master)\b|"
            r"\b(?:graduate|postgraduate|master)\b.{0,80}\b(?:programmes?|programs?|degrees?|courses?)\b)",
            title,
            re.I,
        )
    )
    dedicated_catalog_root = not path_segments and title_catalog
    title_confirms_catalog = (title_catalog or combined_school_catalog) and not CAPTURED_ORGANIZATION_NOISE.search(primary_title)
    program_link_count = int(record.get("programLinks") or 0) + int(record.get("_derivedProgramLinks") or 0)
    is_catalog = (
        (
            title_confirms_catalog
            and (
                endpoint_catalog
                or dedicated_catalog_root
                or str(record.get("kind") or "").casefold() in {"category", "catalog"}
                or program_link_count > 0
            )
        )
        or (
            (endpoint_catalog or dedicated_catalog_root)
            and not CAPTURED_ORGANIZATION_NOISE.search(title)
            and program_link_count > 0
        )
    ) and not title_noise and not last_segment_noise

    if CAPTURED_BACHELOR_LEVEL.search(title):
        return False, "wrong-level", normalized, 0
    if WRONG_LEVEL.search(surface) and not (is_catalog and not WRONG_LEVEL.search(title)):
        return False, "wrong-level", normalized, 0
    if NON_MASTER_QUALIFICATION.search(surface):
        explicit_master_catalog = bool(
            is_catalog
            and re.search(r"\b(?:master(?:'?s)?|postgraduate)\b", primary_title, re.I)
            and re.search(r"\b(?:programmes?|programs?|degrees?|courses?|catalog(?:ue)?)\b", primary_title, re.I)
        )
        if not explicit_master_catalog:
            return False, "non-master-qualification", normalized, 0
    if not path_segments and not is_catalog:
        return False, "root-url", normalized, 0
    if is_catalog and CAPTURED_NON_SCOPE_CATALOG.search(surface) and not CS_ENGINEERING_URL.search(surface):
        return False, "captured-non-scope-catalog", normalized, 0
    if is_catalog and not captured_catalog_is_central(normalized, domains) and not CS_ENGINEERING_URL.search(surface):
        return False, "captured-noncentral-catalog", normalized, 0
    if is_catalog and CAPTURED_MASTER_LEVEL.search(surface):
        scope_bonus = 20 if CS_ENGINEERING_URL.search(surface) else 0
        return True, "accepted-captured-catalog", normalized, 300 + scope_bonus
    if title_noise or last_segment_noise:
        return False, "captured-non-program-page", normalized, 0
    if DOCTORAL_LEVEL.search(title):
        return False, "wrong-level", normalized, 0
    if (
        CAPTURED_MASTER_LEVEL.search(surface)
        and CS_ENGINEERING_URL.search(surface)
        and not (
            CAPTURED_NON_ENGINEERING_SCIENCE.search(surface)
            and not re.search(r"\bengineering\b", surface, re.I)
        )
    ):
        return True, "accepted-captured-scope-program", normalized, 220
    return False, "captured-not-catalog-or-scope-program", normalized, 0


def captured_manifest_urls(
    roots: Iterable[Path],
    valid_ids: set[str],
    missing_ids: set[str],
    ror_trusted: Mapping[str, set[str]],
    aliases: Mapping[str, str] | None = None,
    max_urls_per_school: int = 3,
) -> tuple[Dict[str, set[str]], list[dict], Counter]:
    """Select the highest-quality fetched pages for schools still missing."""
    aliases = aliases if aliases is not None else raw_target_to_canonical()
    selected: Dict[tuple[str, str], dict] = {}
    rejected: Counter = Counter()
    for root in roots:
        if not root.exists():
            continue
        for manifest_path in sorted(root.glob("*/manifest.json")):
            manifest = load(manifest_path, {}) or {}
            raw_id = str(manifest.get("universityId") or "")
            cid = aliases.get(raw_id, raw_id)
            if cid not in valid_ids or cid not in missing_ids:
                continue
            candidates = (manifest.get("discovery") or {}).get("programCandidates") or {}
            source_program_counts = Counter(
                normalize_url(candidate.get("sourceUrl"))
                for candidate in candidates.values()
                if isinstance(candidate, dict) and candidate.get("sourceUrl")
            )
            surfaces = []
            surfaces.extend((manifest.get("pages") or {}).items())
            surfaces.extend(((manifest.get("discovery") or {}).get("visited") or {}).items())
            for url, record in surfaces:
                if not isinstance(record, dict):
                    rejected["captured-invalid-record"] += 1
                    continue
                candidate = candidates.get(url) if isinstance(candidates.get(url), dict) else {}
                policy_record = dict(record)
                policy_record["_derivedProgramLinks"] = source_program_counts.get(normalize_url(url), 0)
                ok, reason, normalized, score = accept_captured_manifest_url(
                    cid, str(url), policy_record, candidate, ror_trusted
                )
                if not ok:
                    rejected[reason] += 1
                    continue
                try:
                    source = str(manifest_path.relative_to(ROOT))
                except ValueError:
                    source = str(manifest_path)
                row = {
                    "canonicalId": cid,
                    "url": normalized,
                    "reason": reason,
                    "score": score,
                    "title": captured_record_title(record),
                    "kind": record.get("kind"),
                    "source": source,
                }
                key = (cid, normalized)
                current = selected.get(key)
                if current is None or (score, -len(normalized)) > (current["score"], -len(current["url"])):
                    selected[key] = row

    owners: Dict[str, set[str]] = defaultdict(set)
    for row in selected.values():
        owners[captured_url_fingerprint(row["url"])].add(row["canonicalId"])
    collided = {fingerprint for fingerprint, canonical_ids in owners.items() if len(canonical_ids) > 1}

    grouped: Dict[str, list[dict]] = defaultdict(list)
    for row in selected.values():
        if captured_url_fingerprint(row["url"]) in collided:
            rejected["captured-cross-institution-url-collision"] += 1
            continue
        grouped[row["canonicalId"]].append(row)
    assignments: Dict[str, set[str]] = defaultdict(set)
    accepted = []
    for cid, rows in grouped.items():
        rows.sort(key=lambda row: (
            -row["score"],
            0 if urlparse(row["url"]).scheme == "https" else 1,
            len(row["url"]),
            row["url"],
        ))
        kept = []
        catalog_titles = set()
        url_fingerprints = set()
        for row in rows:
            url_fingerprint = captured_url_fingerprint(row["url"])
            if url_fingerprint in url_fingerprints:
                continue
            url_fingerprints.add(url_fingerprint)
            if row["reason"] == "accepted-captured-catalog" and row.get("title"):
                title_key = re.sub(r"\s+", " ", row["title"]).strip().casefold()
                if title_key in catalog_titles:
                    continue
                catalog_titles.add(title_key)
            kept.append(row)
            if len(kept) >= max_urls_per_school:
                break
        for row in kept:
            assignments[cid].add(row["url"])
            accepted.append(row)
    accepted.sort(key=lambda row: (row["canonicalId"], -row["score"], row["url"]))
    return assignments, accepted, rejected


def ranking_ids(scope_entity: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for selection in scope_entity.get("rankingScope", {}).get("selections") or []:
        source = selection.get("source")
        index = selection.get("rowIndex")
        if source not in {"qs", "the", "arwu", "usnews"} or not isinstance(index, int):
            continue
        rows = load(ROOT / "frontend" / "public" / "data" / "rankings" / f"{source}.json", []) or []
        if 0 <= index < len(rows):
            identifier = rows[index].get("universityId")
            if identifier and identifier not in result:
                result.append(identifier)
    return result


def build() -> tuple[dict, dict]:
    scope = load(SCOPE, {}) or {}
    entities = [e for e in scope.get("entities") or [] if e.get("rankingScope", {}).get("eligible")]
    valid_ids = {str(e.get("canonicalId")) for e in entities if e.get("canonicalId")}
    trusted = trusted_domains_by_id()
    ror_trusted = ror_domains_by_id()
    assignments = review_urls(load(REVIEW_PATH, {}) or {}, valid_ids, trusted)
    rejected = Counter()
    accepted_rows = []
    for path in RESULT_PATHS:
        for row in load(path, []) or []:
            if not isinstance(row, dict) or row.get("canonicalId") not in valid_ids:
                continue
            for item in row.get("urls") or []:
                ok, reason, url = accept_crawl_url(row, item, trusted)
                if ok:
                    assignments[str(row["canonicalId"])].add(url)
                    accepted_rows.append({"canonicalId": row["canonicalId"], "url": url, "type": item.get("type"), "source": str(path.relative_to(ROOT))})
                else:
                    rejected[reason] += 1

    missing_ids = valid_ids - {cid for cid, urls in assignments.items() if urls}
    captured_assignments, accepted_captured_rows, rejected_captured = captured_manifest_urls(
        CAPTURED_RAW_ROOTS,
        valid_ids,
        missing_ids,
        ror_trusted,
    )
    for cid, urls in captured_assignments.items():
        assignments[cid].update(urls)

    missing_ids = valid_ids - {cid for cid, urls in assignments.items() if urls}
    application_assignments, accepted_application_rows, rejected_application = application_audit_urls(
        load(APPLICATION_AUDIT, {}) or {}, valid_ids, missing_ids, ror_trusted
    )
    for cid, urls in application_assignments.items():
        assignments[cid].update(urls)

    records = []
    for entity in entities:
        cid = str(entity["canonicalId"])
        urls = sorted(assignments.get(cid, set()))
        records.append({
            "canonicalId": cid,
            "name": entity.get("name"),
            "country": entity.get("country"),
            "rankingSources": sorted(set(entity.get("rankingSources") or [])),
            "selections": entity.get("rankingScope", {}).get("selections") or [],
            "coverageStatus": "covered" if urls else "missing",
            "urlCount": len(urls),
            "urls": urls,
            "rankingUniversityIds": ranking_ids(entity),
        })
    records.sort(key=lambda row: (min((s.get("rowIndex", 9999) for s in row["selections"]), default=9999), row.get("country") or "", row.get("name") or "", row["canonicalId"]))
    covered = sum(row["coverageStatus"] == "covered" for row in records)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "rankingSources": ["qs", "the", "arwu", "usnews"],
            "rankingRowLimit": 350,
            "selectionBasis": "first-350-rows-per-source",
            "mainlandChinaInstitutionsExcluded": True,
            "hongKongAndMacauIncluded": True,
            "coverageDefinition": "At least one specific official programme or programme-catalog URL passed the local URL quality filter.",
            "requirementsComplete": False,
        },
        "summary": {
            "schools": len(records),
            "coveredSchools": covered,
            "missingSchools": len(records) - covered,
            "coveragePercent": round(100 * covered / len(records), 1) if records else 0.0,
            "recordsInFile": len(records),
            "officialUrlAssignments": sum(row["urlCount"] for row in records),
            "uniqueOfficialUrls": len({url for row in records for url in row["urls"]}),
        },
        "schools": records,
    }
    quality = {
        "schemaVersion": 1,
        "generatedAt": payload["generatedAt"],
        "policy": {
            "crawlEvidenceIsDiscoveryOnly": True,
            "trustedDomainSources": ["captured-manifest.officialDomains", "ROR identity with name and country match"],
            "capturedManifestDomainSource": "ROR identity with name and country match only",
            "capturedManifestRequiresFetchedPage": True,
            "capturedManifestOnlyFillsMissingSchools": True,
            "applicationAuditDomainSource": "ROR identity with name and country match only",
            "applicationAuditOnlyFillsMissingSchools": True,
            "rejectedUrlsRemainAuditable": True,
        },
        "summary": {
            "crawlResults": sum(len(load(path, []) or []) for path in RESULT_PATHS),
            "acceptedCrawlUrls": len(accepted_rows),
            "acceptedCrawlSchools": len({row["canonicalId"] for row in accepted_rows}),
            "rejectedCrawlUrls": sum(rejected.values()),
            "rejectionReasons": dict(sorted(rejected.items())),
            "acceptedCapturedManifestUrls": len(accepted_captured_rows),
            "acceptedCapturedManifestSchools": len({row["canonicalId"] for row in accepted_captured_rows}),
            "rejectedCapturedManifestObservations": sum(rejected_captured.values()),
            "capturedManifestRejectionReasons": dict(sorted(rejected_captured.items())),
            "acceptedApplicationAuditUrls": len(accepted_application_rows),
            "acceptedApplicationAuditSchools": len({row["canonicalId"] for row in accepted_application_rows}),
            "rejectedApplicationAuditUrls": sum(rejected_application.values()),
            "applicationAuditRejectionReasons": dict(sorted(rejected_application.items())),
        },
        "accepted": accepted_rows,
        "acceptedCapturedManifest": accepted_captured_rows,
        "acceptedApplicationAudit": accepted_application_rows,
        "trustedDomainsByCanonicalId": {cid: sorted(values) for cid, values in sorted(trusted.items()) if cid in valid_ids},
        "rorDomainsByCanonicalId": {cid: sorted(values) for cid, values in sorted(ror_trusted.items()) if cid in valid_ids},
    }
    return payload, quality


def main() -> None:
    payload, quality = build()
    FRONTEND_COVERAGE.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_COVERAGE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QUALITY_REPORT.write_text(json.dumps(quality, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(json.dumps(quality["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
