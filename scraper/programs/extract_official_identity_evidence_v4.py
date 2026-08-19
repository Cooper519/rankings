"""Extract offline identity evidence for auto-recoverable official sites.

This module is deliberately read-only with respect to verification results. It
validates saved homepage captures, extracts structured identity candidates, and
reports whether the evidence package is sufficient to rerun the unchanged
official-site verifier. It never makes a verification decision and never uses
the network.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRIAGE = ROOT / "scraper" / "playwright" / "top500_official_identity_triage_v3.json"
DEFAULT_VERIFICATIONS = [
    ROOT / "scraper" / "playwright" / "top500_official_website_verification_v3.json",
    ROOT / "scraper" / "playwright" / "top500_official_website_verification_recovered15_v3.json",
]
DEFAULT_RAW_ROOT = ROOT / "scraper" / "raw" / "official-discovery" / "official-sites"
DEFAULT_OUTPUT = ROOT / "scraper" / "playwright" / "top500_official_identity_evidence_supplement_v4.json"

IDENTITY_META_NAMES = {"og:site_name", "application-name"}
ORGANIZATION_TYPES = {
    "collegeoruniversity",
    "educationalorganization",
    "organization",
    "university",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def input_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "results", "queue", "targets", "candidates"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("input must contain an item array")


def merged_items(payloads: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for payload in payloads:
        for item in input_items(payload):
            identifier = str(item.get("canonicalId") or item.get("universityId") or "")
            if identifier:
                merged[identifier] = item
    return merged


def portable_path(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return str(path)


def resolve_path(value: Any, manifest_path: Optional[Path] = None) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    root_path = ROOT / path
    if root_path.exists() or manifest_path is None:
        return root_path
    return manifest_path.parent / path


def host(value: str) -> str:
    try:
        candidate = value if "://" in (value or "") else "https://" + (value or "")
        result = (urlsplit(candidate).hostname or "").casefold().rstrip(".")
        if result.startswith("www."):
            result = result[4:]
        try:
            return result.encode("idna").decode("ascii")
        except UnicodeError:
            return result
    except ValueError:
        return ""


def normalize_domain(value: str) -> str:
    return host(value)


def domain_belongs(value: str, official_domains: Iterable[str]) -> bool:
    candidate = host(value)
    if not candidate:
        return False
    for raw_domain in official_domains:
        domain = normalize_domain(str(raw_domain))
        if domain and (candidate == domain or candidate.endswith("." + domain)):
            return True
    return False


def normalize_identity(value: str) -> str:
    text = html.unescape(value or "")
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    ).casefold().replace("&", " and ")
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def compact_identity(value: str) -> str:
    return "".join(re.findall(r"[^\W_]+", normalize_identity(value), flags=re.UNICODE))


def identity_match(candidate: str, accepted_names: Iterable[str]) -> Optional[str]:
    normalized_candidate = normalize_identity(candidate)
    compact_candidate = compact_identity(candidate)
    if not normalized_candidate:
        return None
    for accepted in accepted_names:
        normalized_accepted = normalize_identity(accepted)
        compact_accepted = compact_identity(accepted)
        if not normalized_accepted:
            continue
        if normalized_candidate == normalized_accepted:
            return accepted
        if len(compact_accepted) >= 4 and normalized_accepted in normalized_candidate:
            return accepted
        if 2 <= len(compact_accepted) <= 12 and normalized_accepted in normalized_candidate.split():
            return accepted
        if 2 <= len(compact_accepted) <= 12 and compact_candidate == compact_accepted:
            return accepted
    return None


def strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        output: List[str] = []
        for item in value:
            output.extend(strings(item))
        return output
    if isinstance(value, dict):
        for key in ("value", "name", "label", "text"):
            if isinstance(value.get(key), str) and value[key].strip():
                return [value[key].strip()]
    return []


def registry_names(item: Dict[str, Any], triage_item: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    organization = item.get("rorOrganization") or {}
    for entry in organization.get("names") or []:
        if isinstance(entry, dict):
            values.extend(strings(entry.get("value")))
            values.extend(strings(entry.get("name")))
        else:
            values.extend(strings(entry))
    for key in ("name", "label", "displayName", "rorDisplayName"):
        values.extend(strings(organization.get(key)))
    selected = (item.get("registryResolution") or {}).get("selected") or {}
    values.extend(strings(selected.get("name")))
    values.extend(strings((triage_item.get("rorIdentity") or {}).get("selectedName")))
    return list(dict.fromkeys(value for value in values if value))


def official_domains(item: Dict[str, Any], triage_item: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    values.extend(strings((triage_item.get("rorIdentity") or {}).get("selectedDomains")))
    selected = (item.get("registryResolution") or {}).get("selected") or {}
    values.extend(strings(selected.get("registryDomains")))
    organization = item.get("rorOrganization") or {}
    values.extend(strings(organization.get("domains")))
    return list(dict.fromkeys(normalize_domain(value) for value in values if normalize_domain(value)))


class IdentityHTMLParser(HTMLParser):
    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self.title_parts: List[str] = []
        self.h1_values: List[str] = []
        self.meta_values: List[Dict[str, str]] = []
        self.alternate_links: List[Dict[str, str]] = []
        self.json_ld_blocks: List[str] = []
        self._title_depth = 0
        self._h1_depth = 0
        self._h1_parts: List[str] = []
        self._json_ld_depth = 0
        self._json_ld_parts: List[str] = []

    @staticmethod
    def _attrs(attrs: List[Tuple[str, Optional[str]]]) -> Dict[str, str]:
        return {str(key).casefold(): str(value or "") for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        lowered = tag.casefold()
        values = self._attrs(attrs)
        if lowered == "title":
            self._title_depth += 1
        elif lowered == "h1":
            if self._h1_depth == 0:
                self._h1_parts = []
            self._h1_depth += 1
        elif lowered == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content", "").strip()
            if key in IDENTITY_META_NAMES and content:
                self.meta_values.append({"kind": key, "value": content})
        elif lowered == "link":
            rel = set(values.get("rel", "").casefold().split())
            href = values.get("href", "").strip()
            language = values.get("hreflang", "").strip()
            if "alternate" in rel and href and language:
                self.alternate_links.append({"hreflang": language, "href": href})
        elif lowered == "script" and "ld+json" in values.get("type", "").casefold():
            if self._json_ld_depth == 0:
                self._json_ld_parts = []
            self._json_ld_depth += 1

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "title" and self._title_depth:
            self._title_depth -= 1
        elif lowered == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                value = " ".join(" ".join(self._h1_parts).split())
                if value:
                    self.h1_values.append(value)
        elif lowered == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1
            if self._json_ld_depth == 0:
                value = "".join(self._json_ld_parts).strip()
                if value:
                    self.json_ld_blocks.append(value)

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._h1_depth:
            self._h1_parts.append(data)
        if self._json_ld_depth:
            self._json_ld_parts.append(data)


def json_ld_organization_names(value: Any) -> List[str]:
    output: List[str] = []
    if isinstance(value, list):
        for item in value:
            output.extend(json_ld_organization_names(item))
        return output
    if not isinstance(value, dict):
        return output
    types = strings(value.get("@type"))
    normalized_types = {compact_identity(item) for item in types}
    if normalized_types.intersection(ORGANIZATION_TYPES):
        for key in ("name", "legalName", "alternateName"):
            output.extend(strings(value.get(key)))
    for key, nested in value.items():
        if key not in {"name", "legalName", "alternateName"}:
            output.extend(json_ld_organization_names(nested))
    return output


def parse_json_ld(blocks: Iterable[str]) -> Tuple[List[str], List[str]]:
    names: List[str] = []
    errors: List[str] = []
    for index, block in enumerate(blocks):
        try:
            names.extend(json_ld_organization_names(json.loads(block)))
        except (TypeError, ValueError) as error:
            errors.append("block-%s: %s: %s" % (index, type(error).__name__, error))
    return list(dict.fromkeys(names)), errors


def decode_body(body: bytes, headers: Dict[str, Any]) -> str:
    content_type = str(headers.get("Content-Type") or headers.get("content-type") or "")
    match = re.search(r"charset=([\w.-]+)", content_type, flags=re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "windows-1252"])
    for encoding in encodings:
        try:
            return body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", errors="replace")


def candidate_record(source: str, value: str, accepted_names: Iterable[str]) -> Dict[str, Any]:
    matched = identity_match(value, accepted_names)
    return {
        "source": source,
        "value": value,
        "normalized": normalize_identity(value),
        "matchesAcceptedName": bool(matched),
        "matchedAcceptedName": matched,
    }


def extract_page_evidence(
    body: bytes,
    headers: Dict[str, Any],
    base_url: str,
    accepted_names: List[str],
    domains: List[str],
) -> Dict[str, Any]:
    parser = IdentityHTMLParser()
    parser.feed(decode_body(body, headers))
    title = " ".join(" ".join(parser.title_parts).split())
    json_ld_names, json_ld_errors = parse_json_ld(parser.json_ld_blocks)
    candidates: List[Dict[str, Any]] = []
    if title:
        candidates.append(candidate_record("title", title, accepted_names))
    for value in parser.h1_values:
        candidates.append(candidate_record("h1", value, accepted_names))
    for entry in parser.meta_values:
        candidates.append(candidate_record("meta:" + entry["kind"], entry["value"], accepted_names))
    for value in json_ld_names:
        candidates.append(candidate_record("json-ld:organization-name", value, accepted_names))
    alternate_links = []
    for entry in parser.alternate_links:
        absolute = urljoin(base_url, entry["href"])
        alternate_links.append({
            "hreflang": entry["hreflang"],
            "href": absolute,
            "host": host(absolute),
            "officialDomainMatch": domain_belongs(absolute, domains),
        })
    return {
        "title": title or None,
        "h1": parser.h1_values,
        "meta": parser.meta_values,
        "jsonLdOrganizationNames": json_ld_names,
        "jsonLdErrors": json_ld_errors,
        "alternateLanguageLinks": alternate_links,
        "identityCandidates": candidates,
    }


def manifest_candidates(
    identifier: str,
    verification_item: Dict[str, Any],
    raw_root: Path,
) -> List[Path]:
    values: List[Path] = []
    verification = verification_item.get("verification") or {}
    live = ((verification.get("evidence") or {}).get("liveOfficialPage") or {})
    raw = live.get("raw") or {}
    referenced = resolve_path(raw.get("manifestFile"))
    if referenced is not None:
        values.append(referenced)
    directory = raw_root / re.sub(r"[^A-Za-z0-9_.-]+", "_", identifier or "unknown")
    if directory.is_dir():
        values.extend(sorted(directory.glob("homepage_sha256=*.manifest.json")))
    unique: List[Path] = []
    seen = set()
    for path in values:
        key = str(path.resolve())
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def validate_capture(manifest_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "manifestFile": portable_path(manifest_path),
        "rawFile": None,
        "manifestPresent": manifest_path.is_file(),
        "rawPresent": False,
        "expectedSha256": None,
        "actualSha256": None,
        "hashVerified": False,
        "bytesVerified": False,
        "valid": False,
        "errors": [],
        "manifest": None,
        "body": None,
    }
    if not manifest_path.is_file():
        result["errors"].append("manifest_missing")
        return result
    try:
        manifest = load_json(manifest_path)
    except (OSError, UnicodeError, ValueError) as error:
        result["errors"].append("manifest_unreadable:%s:%s" % (type(error).__name__, error))
        return result
    if not isinstance(manifest, dict):
        result["errors"].append("manifest_not_object")
        return result
    result["manifest"] = manifest
    expected = str(manifest.get("sha256") or "").casefold()
    result["expectedSha256"] = expected or None
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        result["errors"].append("manifest_sha256_invalid")
    raw_path = resolve_path(manifest.get("rawFile"), manifest_path)
    if raw_path is None and expected:
        raw_path = manifest_path.parent / ("homepage_sha256=%s.body" % expected)
    result["rawFile"] = portable_path(raw_path)
    result["rawPresent"] = bool(raw_path and raw_path.is_file())
    if not result["rawPresent"]:
        result["errors"].append("raw_missing")
        return result
    try:
        body = raw_path.read_bytes()
    except OSError as error:
        result["errors"].append("raw_unreadable:%s:%s" % (type(error).__name__, error))
        return result
    actual = hashlib.sha256(body).hexdigest()
    result["body"] = body
    result["actualSha256"] = actual
    result["hashVerified"] = bool(expected and expected == actual)
    if not result["hashVerified"]:
        result["errors"].append("raw_sha256_mismatch")
    expected_bytes = manifest.get("bytes")
    result["bytesVerified"] = isinstance(expected_bytes, int) and expected_bytes == len(body)
    if not result["bytesVerified"]:
        result["errors"].append("raw_bytes_mismatch")
    if manifest.get("kind") not in (None, "homepage"):
        result["errors"].append("manifest_kind_not_homepage")
    result["valid"] = not result["errors"]
    return result


def choose_capture(paths: Iterable[Path]) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    attempts: List[Dict[str, Any]] = []
    selected: Optional[Dict[str, Any]] = None
    for path in paths:
        checked = validate_capture(path)
        attempts.append(checked)
        if selected is None and checked["valid"]:
            selected = checked
    return selected, attempts


def public_capture(capture: Dict[str, Any]) -> Dict[str, Any]:
    manifest = capture.get("manifest") or {}
    return {
        "manifestFile": capture.get("manifestFile"),
        "rawFile": capture.get("rawFile"),
        "manifestPresent": capture.get("manifestPresent"),
        "rawPresent": capture.get("rawPresent"),
        "expectedSha256": capture.get("expectedSha256"),
        "actualSha256": capture.get("actualSha256"),
        "hashVerified": capture.get("hashVerified"),
        "bytesVerified": capture.get("bytesVerified"),
        "valid": capture.get("valid"),
        "errors": capture.get("errors") or [],
        "requestedUrl": manifest.get("requestedUrl"),
        "finalUrl": manifest.get("finalUrl"),
        "status": manifest.get("status"),
        "capturedAt": manifest.get("capturedAt"),
    }


def build_item(
    triage_item: Dict[str, Any],
    verification_item: Dict[str, Any],
    raw_root: Path,
) -> Dict[str, Any]:
    identifier = str(triage_item.get("canonicalId") or "")
    names = registry_names(verification_item, triage_item)
    domains = official_domains(verification_item, triage_item)
    selected, attempts = choose_capture(manifest_candidates(identifier, verification_item, raw_root))
    page_evidence: Dict[str, Any] = {
        "title": None,
        "h1": [],
        "meta": [],
        "jsonLdOrganizationNames": [],
        "jsonLdErrors": [],
        "alternateLanguageLinks": [],
        "identityCandidates": [],
    }
    domain_evidence: Dict[str, Any] = {
        "officialDomains": domains,
        "requestedHost": None,
        "finalHost": None,
        "requestedDomainMatch": False,
        "finalDomainMatch": False,
        "officialAlternateLinkCount": 0,
    }
    blockers: List[str] = []
    if selected is None:
        blockers.append("valid_homepage_raw_unavailable")
    else:
        manifest = selected["manifest"] or {}
        requested_url = str(manifest.get("requestedUrl") or "")
        final_url = str(manifest.get("finalUrl") or requested_url)
        page_evidence = extract_page_evidence(
            selected["body"], manifest.get("headers") or {}, final_url,
            names, domains,
        )
        domain_evidence.update({
            "requestedHost": host(requested_url),
            "finalHost": host(final_url),
            "requestedDomainMatch": domain_belongs(requested_url, domains),
            "finalDomainMatch": domain_belongs(final_url, domains),
            "officialAlternateLinkCount": sum(
                bool(link["officialDomainMatch"])
                for link in page_evidence["alternateLanguageLinks"]
            ),
        })
        status = manifest.get("status")
        if isinstance(status, bool) or not isinstance(status, int) or status < 200 or status >= 400:
            blockers.append("homepage_status_not_success")
        if not (
            domain_evidence["finalDomainMatch"]
            or domain_evidence["requestedDomainMatch"]
            or domain_evidence["officialAlternateLinkCount"]
        ):
            blockers.append("official_domain_evidence_missing")
        if not any(candidate["matchesAcceptedName"] for candidate in page_evidence["identityCandidates"]):
            blockers.append("matching_identity_candidate_missing")
    sufficient = not blockers
    return {
        "canonicalId": identifier,
        "name": triage_item.get("name"),
        "country": triage_item.get("country"),
        "rankingSources": triage_item.get("rankingSources") or [],
        "originalVerificationStatus": triage_item.get("originalVerificationStatus"),
        "reasonCodes": triage_item.get("reasonCodes") or [],
        "recoveryMode": triage_item.get("recoveryMode"),
        "acceptedIdentityNames": names,
        "homepageRaw": public_capture(selected) if selected else None,
        "captureAttempts": [public_capture(attempt) for attempt in attempts],
        "evidence": {
            "pageIdentity": page_evidence,
            "officialDomain": domain_evidence,
        },
        "rerunAssessment": {
            "sufficientForOriginalVerifierRerun": sufficient,
            "blockingReasons": blockers,
            "matchingCandidateCount": sum(
                bool(candidate["matchesAcceptedName"])
                for candidate in page_evidence["identityCandidates"]
            ),
            "verificationDecision": None,
            "note": "Candidate evidence only; rerun the unchanged verifier to decide status.",
        },
        "statusGuardrail": "no-status-change",
    }


def build_report(
    triage_payload: Any,
    verification_payloads: Iterable[Any],
    raw_root: Path = DEFAULT_RAW_ROOT,
) -> Dict[str, Any]:
    triage = [
        item for item in input_items(triage_payload)
        if item.get("category") == "auto-recoverable"
    ]
    verification_by_id = merged_items(verification_payloads)
    rows = []
    for item in triage:
        identifier = str(item.get("canonicalId") or "")
        rows.append(build_item(item, verification_by_id.get(identifier, {}), raw_root))
    rows.sort(key=lambda item: (str(item.get("country") or ""), str(item.get("name") or "")))
    sufficient_count = sum(
        bool(item["rerunAssessment"]["sufficientForOriginalVerifierRerun"])
        for item in rows
    )
    source_counts = Counter()
    for item in rows:
        for candidate in item["evidence"]["pageIdentity"]["identityCandidates"]:
            if candidate["matchesAcceptedName"]:
                source_counts[candidate["source"]] += 1
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "inputCategory": "auto-recoverable",
            "entities": len(rows),
            "networkAccess": False,
            "rawPolicy": "existing-official-homepage-raw-only",
            "evidenceChannels": [
                "title",
                "h1",
                "meta:og:site_name",
                "meta:application-name",
                "json-ld:organization-name",
                "alternate-language-link",
                "official-domain",
            ],
        },
        "guardrails": {
            "verificationStatusesChanged": False,
            "verifierChanged": False,
            "thresholdsChanged": False,
            "networkUsed": False,
            "verificationDecisionProduced": False,
            "rorAloneCannotVerify": True,
        },
        "summary": {
            "entities": len(rows),
            "validHomepageRaw": sum(bool(item["homepageRaw"]) for item in rows),
            "rawUnavailableOrInvalid": sum(not bool(item["homepageRaw"]) for item in rows),
            "sufficientForOriginalVerifierRerun": sufficient_count,
            "insufficientForOriginalVerifierRerun": len(rows) - sufficient_count,
            "matchingEvidenceSourceCounts": dict(sorted(source_counts.items())),
        },
        "items": rows,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triage", type=Path, default=DEFAULT_TRIAGE)
    parser.add_argument("--verification", type=Path, action="append")
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    verification_paths = args.verification or DEFAULT_VERIFICATIONS
    report = build_report(
        load_json(args.triage),
        [load_json(path) for path in verification_paths],
        args.raw_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
