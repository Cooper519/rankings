"""Verify official website candidates produced by a future ROR discovery run.

ROR is an identity and domain registry signal, not proof that a website is an
official admissions source.  This module deliberately keeps the verification
stage separate from crawl targets and programme manifests.  It accepts the
compact records emitted by ``resolve_top500_registry_domains.py`` as well as
records containing the full ROR organization object.

The command writes only its own result JSON and a separate raw response corpus.
It can be used offline in tests by passing a fetcher to ``verify_items``.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "scraper" / "playwright" / "top500_registry_domain_hints.json"
DEFAULT_OUTPUT = ROOT / "scraper" / "playwright" / "top500_official_website_verification.json"
DEFAULT_RAW = ROOT / "scraper" / "raw" / "registry" / "ror_official_sites"

COUNTRY_ALIASES = {
    "czech republic": "czechia",
    "hong kong sar": "hong kong",
    "korea": "south korea",
    "republic of korea": "south korea",
    "russian federation": "russia",
    "taiwan, province of china": "taiwan",
    "turkiye": "turkey",
    "united states of america": "united states",
    "uk": "united kingdom",
    "u k": "united kingdom",
}
COUNTRY_CODES = {
    "us": "united states", "gb": "united kingdom", "uk": "united kingdom",
    "cn": "china", "ca": "canada", "au": "australia", "de": "germany",
    "fr": "france", "it": "italy", "es": "spain", "ch": "switzerland",
    "nl": "netherlands", "be": "belgium", "se": "sweden", "fi": "finland",
    "at": "austria", "pl": "poland", "cz": "czechia", "tr": "turkey",
    "pt": "portugal", "no": "norway", "dk": "denmark", "ie": "ireland",
    "jp": "japan", "kr": "south korea", "in": "india", "tw": "taiwan",
}
WAF_MARKERS = (
    "access denied", "cf-chl-", "cloudflare ray id", "captcha", "verify you are human",
    "just a moment", "request blocked", "temporarily unavailable", "security check",
    "web application firewall", "incapsula",
)
BLOCKED_STATUS = {401, 403, 406, 409, 423, 429, 451, 503}
IDENTITY_META_NAMES = {"og:site_name", "application-name"}
ORGANIZATION_TYPES = {
    "collegeoruniversity",
    "educationalorganization",
    "organization",
    "university",
}


@dataclass
class HttpResponse:
    status: int
    url: str
    headers: Dict[str, str]
    body: bytes


class _VisibleTextParser(HTMLParser):
    """Extract visible and structured identity text without BeautifulSoup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: List[str] = []
        self.body_parts: List[str] = []
        self.h1_values: List[str] = []
        self.meta_values: List[Dict[str, str]] = []
        self.json_ld_blocks: List[str] = []
        self._title_depth = 0
        self._h1_depth = 0
        self._h1_parts: List[str] = []
        self._json_ld_depth = 0
        self._json_ld_parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.casefold()
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        if tag == "title":
            self._title_depth += 1
        elif tag == "h1":
            if self._h1_depth == 0:
                self._h1_parts = []
            self._h1_depth += 1
        elif tag == "meta":
            key = (values.get("property") or values.get("name") or "").casefold()
            content = values.get("content", "").strip()
            if key in IDENTITY_META_NAMES and content:
                self.meta_values.append({"kind": key, "value": content})
        elif tag == "script" and "ld+json" in values.get("type", "").casefold():
            if self._json_ld_depth == 0:
                self._json_ld_parts = []
            self._json_ld_depth += 1
        if tag in {"script", "style", "noscript", "template", "svg"}:
            self._skip_depth += 1

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        elif tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
            if self._h1_depth == 0:
                value = " ".join(" ".join(self._h1_parts).split())
                if value:
                    self.h1_values.append(value)
        elif tag == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1
            if self._json_ld_depth == 0:
                value = "".join(self._json_ld_parts).strip()
                if value:
                    self.json_ld_blocks.append(value)
        if tag in {"script", "style", "noscript", "template", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._h1_depth:
            self._h1_parts.append(data)
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
        if not self._skip_depth:
            self.body_parts.append(data)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def input_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "results", "queue", "targets", "candidates"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("input must be an array or contain items/results/queue/targets/candidates")


def ascii_text(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).casefold()


def normalize_name(value: str) -> str:
    text = html.unescape(value or "")
    text = ascii_text(text).replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def normalize_live_identity(value: str) -> str:
    """Normalize live page identity while retaining non-Latin letters."""
    text = html.unescape(value or "")
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    ).casefold().replace("&", " and ")
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def name_variants(value: str) -> List[str]:
    variants = [normalize_name(value)]
    # Ranking labels commonly append a short acronym, e.g. "(UBA)". Do not
    # remove longer parenthetical qualifiers because they may distinguish a
    # campus or a legally separate institution.
    without_acronym = re.sub(r"\s*\(([A-Z0-9.&-]{2,10})\)\s*$", "", value or "").strip()
    normalized_without = normalize_name(without_acronym)
    if normalized_without and normalized_without not in variants:
        variants.append(normalized_without)
    return variants


def normalize_country(value: str) -> str:
    text = " ".join(ascii_text(value).replace("_", " ").split())
    if len(text) == 2 and text in COUNTRY_CODES:
        return COUNTRY_CODES[text]
    return COUNTRY_ALIASES.get(text, text)


def _host(value: str) -> str:
    try:
        candidate = value if "://" in value else f"https://{value}"
        hostname = urlsplit(candidate).hostname or ""
        hostname = hostname.rstrip(".").casefold()
        if hostname.startswith("www."):
            hostname = hostname[4:]
        try:
            return hostname.encode("idna").decode("ascii")
        except UnicodeError:
            return hostname
    except ValueError:
        return ""


def normalize_domain(value: str) -> str:
    domain = _host(value.strip()) if value else ""
    return domain[2:] if domain.startswith("*.") else domain


def domain_belongs(host_or_url: str, registry_domains: Iterable[str]) -> bool:
    host = _host(host_or_url)
    if not host:
        return False
    for value in registry_domains:
        domain = normalize_domain(str(value))
        if domain and (host == domain or host.endswith(f".{domain}")):
            return True
    return False


def _as_strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        for key in ("value", "name", "label", "text"):
            if isinstance(value.get(key), str) and value[key].strip():
                return [value[key].strip()]
        return []
    if isinstance(value, list):
        output: List[str] = []
        for item in value:
            output.extend(_as_strings(item))
        return output
    return []


def registry_organization(item: Dict[str, Any]) -> Dict[str, Any]:
    resolution = item.get("registryResolution")
    if not isinstance(resolution, dict):
        resolution = {}
    for key in ("rorOrganization", "registryOrganization", "organization", "ror"):
        value = item.get(key)
        if isinstance(value, dict):
            return value
    for key in ("organization", "rorOrganization", "selectedOrganization"):
        value = resolution.get(key)
        if isinstance(value, dict):
            return value
    selected = resolution.get("selected")
    if isinstance(selected, dict):
        return selected
    selected = item.get("selected")
    return selected if isinstance(selected, dict) else {}


def registry_names(organization: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    names = organization.get("names")
    if isinstance(names, list):
        for entry in names:
            if isinstance(entry, dict):
                values.extend(_as_strings(entry.get("value")))
                values.extend(_as_strings(entry.get("name")))
            else:
                values.extend(_as_strings(entry))
    for key in ("label", "name", "displayName", "rorDisplayName"):
        values.extend(_as_strings(organization.get(key)))
    for key in ("aliases", "alias", "acronyms", "acronym"):
        values.extend(_as_strings(organization.get(key)))
    # The resolver's compact selected record calls the ROR display name name.
    return list(dict.fromkeys(value for value in values if value))


def registry_country(organization: Dict[str, Any]) -> str:
    for key in ("country", "countryName", "candidateCountry"):
        values = _as_strings(organization.get(key))
        if values:
            return values[0]
    locations = organization.get("locations") or organization.get("addresses") or []
    if isinstance(locations, list):
        for location in locations:
            if not isinstance(location, dict):
                continue
            details = location.get("geonames_details") or location.get("geoNamesDetails") or {}
            for source in (details, location):
                if isinstance(source, dict):
                    for key in ("country_name", "countryName", "country"):
                        values = _as_strings(source.get(key))
                        if values:
                            return values[0]
    return ""


def registry_domains(organization: Dict[str, Any]) -> List[str]:
    values = list(_as_strings(organization.get("domains")))
    values.extend(_as_strings(organization.get("registryDomains")))
    for link in organization.get("links") or []:
        link_value = link.get("value") if isinstance(link, dict) else link
        host = _host(str(link_value or ""))
        if host and not host.endswith("wikipedia.org"):
            values.append(host)
    return list(dict.fromkeys(normalize_domain(value) for value in values if normalize_domain(value)))


def candidate_urls(item: Dict[str, Any], organization: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ("website", "websiteUrl", "officialWebsite", "officialUrl", "url", "homepage"):
        values.extend(_as_strings(item.get(key)))
    for key in ("websiteCandidates", "officialWebsiteCandidates", "discoveryCandidates"):
        entries = item.get(key) or []
        for entry in entries:
            if isinstance(entry, dict):
                values.extend(_as_strings(entry.get("href") or entry.get("url") or entry.get("website")))
            else:
                values.extend(_as_strings(entry))
    if not values:
        # ROR links are usable discovery candidates, but still require live
        # evidence below; they are never verified by registry data alone.
        for link in organization.get("links") or []:
            value = link.get("value") if isinstance(link, dict) else link
            if value and not _host(str(value)).endswith("wikipedia.org"):
                values.append(str(value))
    if not values:
        values = [f"https://{domain}" for domain in registry_domains(organization)]
    return list(dict.fromkeys(value.strip() for value in values if value and _host(value)))


def accepted_name_match(target_name: str, names: Iterable[str]) -> Tuple[bool, Optional[str]]:
    wanted = set(name_variants(target_name))
    for name in names:
        if wanted.intersection(name_variants(name)):
            return True, name
    return False, None


def audited_registry_match(item: Dict[str, Any], organization: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    resolution = item.get("registryResolution") or {}
    selected = resolution.get("selected") or {}
    organization_id = organization.get("id")
    selected_id = selected.get("rorId")
    raw_file = resolution.get("rawFile")
    raw_manifest = resolution.get("rawManifestFile")
    accepted = bool(
        selected.get("confidence") == "high"
        and selected.get("countryMatch") is True
        and organization_id
        and selected_id == organization_id
        and resolution.get("queryName")
        and raw_file
        and raw_manifest
        and resolution.get("rawSha256")
    )
    return accepted, str(resolution.get("queryName")) if accepted else None


def homepage_url(value: str) -> str:
    parts = urlsplit(value if "://" in value else f"https://{value}")
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("website URL must use http or https")
    return urlunsplit((parts.scheme, parts.netloc, "/", "", ""))


def fetch_url(url: str, timeout: float = 30.0) -> HttpResponse:
    request = Request(url, headers={"User-Agent": "RankingSelect/1.0 (official website verification)"})
    try:
        with urlopen(request, timeout=timeout) as response:
            headers = {str(key): str(value) for key, value in response.headers.items()}
            return HttpResponse(int(response.status), response.geturl(), headers, response.read())
    except HTTPError as error:
        headers = {str(key): str(value) for key, value in error.headers.items()}
        return HttpResponse(int(error.code), error.geturl(), headers, error.read())


def decode_body(response: HttpResponse) -> str:
    content_type = response.headers.get("Content-Type", response.headers.get("content-type", ""))
    match = re.search(r"charset=([\w.-]+)", content_type, re.I)
    encoding = match.group(1) if match else "utf-8"
    try:
        return response.body.decode(encoding, errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


def _json_ld_organization_names(value: Any) -> List[str]:
    output: List[str] = []
    if isinstance(value, list):
        for item in value:
            output.extend(_json_ld_organization_names(item))
        return output
    if not isinstance(value, dict):
        return output
    types = _as_strings(value.get("@type"))
    normalized_types = {normalize_name(item).replace(" ", "") for item in types}
    if normalized_types.intersection(ORGANIZATION_TYPES):
        for key in ("name", "legalName", "alternateName"):
            output.extend(_as_strings(value.get(key)))
    for key, nested in value.items():
        if key not in {"name", "legalName", "alternateName"}:
            output.extend(_json_ld_organization_names(nested))
    return output


def _parse_json_ld(blocks: Iterable[str]) -> Tuple[List[str], List[str]]:
    names: List[str] = []
    errors: List[str] = []
    for index, block in enumerate(blocks):
        try:
            names.extend(_json_ld_organization_names(json.loads(block)))
        except (TypeError, ValueError) as error:
            errors.append("block-%s: %s: %s" % (index, type(error).__name__, error))
    return list(dict.fromkeys(names)), errors


def _identity_candidate(source: str, value: str, accepted_names: Iterable[str]) -> Dict[str, Any]:
    normalized_value = normalize_live_identity(value)
    matched = next(
        (
            name for name in accepted_names
            if normalize_live_identity(name) and normalize_live_identity(name) in normalized_value
        ),
        None,
    )
    return {
        "source": source,
        "value": value,
        "matchesAcceptedName": bool(matched),
        "matchedName": matched,
    }


def page_identity(body: str, accepted_names: Iterable[str]) -> Dict[str, Any]:
    accepted = list(accepted_names)
    parser = _VisibleTextParser()
    try:
        parser.feed(body)
    except Exception:
        # The raw page is still useful even when malformed HTML defeats the parser.
        parser.title_parts = []
        parser.body_parts = [re.sub(r"<[^>]+>", " ", body)]
    title = " ".join(parser.title_parts).strip()
    visible = " ".join(parser.body_parts).strip()
    normalized_body = normalize_live_identity(visible)
    matched_body = next((name for name in accepted if normalize_live_identity(name) and normalize_live_identity(name) in normalized_body), None)
    json_ld_names, json_ld_errors = _parse_json_ld(parser.json_ld_blocks)
    candidates: List[Dict[str, Any]] = []
    if title:
        candidates.append(_identity_candidate("title", title, accepted))
    for value in parser.h1_values:
        candidates.append(_identity_candidate("h1", value, accepted))
    for entry in parser.meta_values:
        candidates.append(_identity_candidate("meta:" + entry["kind"], entry["value"], accepted))
    for value in json_ld_names:
        candidates.append(_identity_candidate("json-ld:organization-name", value, accepted))
    matching_candidates = [candidate for candidate in candidates if candidate["matchesAcceptedName"]]
    title_candidate = next((candidate for candidate in candidates if candidate["source"] == "title"), None)
    return {
        "title": title,
        "h1": parser.h1_values,
        "meta": parser.meta_values,
        "jsonLdOrganizationNames": json_ld_names,
        "jsonLdErrors": json_ld_errors,
        "identityCandidates": candidates,
        "structuredIdentityMatches": bool(matching_candidates),
        "structuredIdentityMatchedSources": list(dict.fromkeys(
            candidate["source"] for candidate in matching_candidates
        )),
        "titleMatches": bool(title_candidate and title_candidate["matchesAcceptedName"]),
        "titleMatchedName": title_candidate["matchedName"] if title_candidate else None,
        "bodyMatches": bool(matched_body),
        "bodyMatchedName": matched_body,
    }


def save_raw(
    raw_root: Path,
    item_id: str,
    kind: str,
    response: HttpResponse,
    requested_url: Optional[str] = None,
) -> Dict[str, Any]:
    digest = hashlib.sha256(response.body).hexdigest()
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", item_id or "unknown")
    directory = raw_root / safe_id
    directory.mkdir(parents=True, exist_ok=True)
    body_path = directory / f"{kind}_sha256={digest}.body"
    manifest_path = directory / f"{kind}_sha256={digest}.manifest.json"
    if not body_path.exists():
        body_path.write_bytes(response.body)
    manifest = {
        "schemaVersion": 1,
        "kind": kind,
        "requestedUrl": requested_url or response.url,
        "finalUrl": response.url,
        "status": response.status,
        "headers": response.headers,
        "bytes": len(response.body),
        "sha256": digest,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "rawFile": str(body_path.resolve()),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        **manifest,
        "manifestFile": str(manifest_path.resolve()),
        "captureStatus": "captured",
    }


def load_cached_raw(
    raw_root: Path,
    item_id: str,
    kind: str,
    requested_url: str,
) -> Optional[Tuple[HttpResponse, Dict[str, Any]]]:
    """Return a complete, hash-verified raw capture for the requested URL."""
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", item_id or "unknown")
    directory = raw_root / safe_id
    if not directory.is_dir():
        return None

    for manifest_path in sorted(directory.glob("%s_sha256=*.manifest.json" % kind)):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            if not isinstance(manifest, dict):
                continue
            digest = str(manifest.get("sha256") or "").casefold()
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                continue
            if manifest.get("kind") != kind or manifest.get("requestedUrl") != requested_url:
                continue
            if manifest_path.name != "%s_sha256=%s.manifest.json" % (kind, digest):
                continue

            body_path = directory / ("%s_sha256=%s.body" % (kind, digest))
            if not body_path.is_file():
                continue
            body = body_path.read_bytes()
            if hashlib.sha256(body).hexdigest() != digest:
                continue
            if manifest.get("bytes") != len(body):
                continue

            status = manifest.get("status")
            final_url = manifest.get("finalUrl")
            headers = manifest.get("headers")
            if isinstance(status, bool) or not isinstance(status, int):
                continue
            if not isinstance(final_url, str) or not final_url:
                continue
            if not isinstance(headers, dict):
                continue

            response = HttpResponse(
                status,
                final_url,
                {str(key): str(value) for key, value in headers.items()},
                body,
            )
            raw = {
                **manifest,
                "rawFile": str(body_path.resolve()),
                "manifestFile": str(manifest_path.resolve()),
                "captureStatus": "cached",
            }
            return response, raw
        except (OSError, UnicodeError, ValueError, TypeError):
            continue
    return None


def capture_raw(
    raw_root: Path,
    item_id: str,
    kind: str,
    requested_url: str,
    fetcher: Callable[[str, float], Any],
    timeout: float,
) -> Tuple[HttpResponse, Dict[str, Any]]:
    cached = load_cached_raw(raw_root, item_id, kind, requested_url)
    if cached is not None:
        return cached
    response = _response_from(fetcher(requested_url, timeout))
    return response, save_raw(raw_root, item_id, kind, response, requested_url)


def _response_from(value: Any) -> HttpResponse:
    if isinstance(value, HttpResponse):
        return value
    if isinstance(value, dict):
        body = value.get("body", b"")
        if isinstance(body, str):
            body = body.encode("utf-8")
        return HttpResponse(int(value.get("status", 200)), str(value.get("url", "")), dict(value.get("headers") or {}), body)
    raise TypeError("fetcher must return HttpResponse or a response mapping")


def verify_candidate(
    item: Dict[str, Any],
    raw_root: Path = DEFAULT_RAW,
    fetcher: Callable[[str, float], Any] = fetch_url,
    fetch_sitemap: bool = False,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    organization = registry_organization(item)
    target_name = str(item.get("name") or item.get("universityName") or "")
    target_country = normalize_country(str(item.get("country") or ""))
    if not organization:
        return {
            "verificationStatus": "review",
            "captureStatus": "not-attempted",
            "reasonCodes": ["ror_match_missing"],
            "reasons": ["ror_match_missing"],
            "evidence": {
                "registryIdentity": {
                    "targetName": target_name,
                    "targetCountry": target_country,
                    "rorCountry": "",
                    "countryMatch": False,
                    "rorNames": [],
                    "nameMatch": False,
                    "matchedName": None,
                    "rorId": None,
                },
                "domainConsistency": {},
                "liveOfficialPage": {},
            },
        }
    ror_country_raw = registry_country(organization)
    ror_country = normalize_country(ror_country_raw)
    names = registry_names(organization)
    domains = registry_domains(organization)
    identity_match, matched_name = accepted_name_match(target_name, names)
    resolver_match, resolver_matched_name = audited_registry_match(item, organization)
    if not identity_match and resolver_match:
        identity_match = True
        matched_name = resolver_matched_name
    country_match = bool(target_country and ror_country and target_country == ror_country)
    identity = {
        "targetName": target_name,
        "targetCountry": target_country,
        "rorCountry": ror_country_raw,
        "countryMatch": country_match,
        "rorNames": names,
        "nameMatch": identity_match,
        "matchedName": matched_name,
        "matchSource": "audited-ror-resolution" if resolver_match and matched_name == resolver_matched_name else "target-name",
        "rorId": organization.get("id") or (
            (item.get("registryResolution") or {}).get("selected") or {}
        ).get("rorId"),
    }
    result: Dict[str, Any] = {
        "verificationStatus": "review",
        "captureStatus": "not-attempted",
        "reasonCodes": [],
        "reasons": [],
        "evidence": {"registryIdentity": identity, "domainConsistency": {}, "liveOfficialPage": {}},
    }
    if not country_match:
        result["verificationStatus"] = "rejected"
        result["reasonCodes"].append("ror_country_mismatch")
    if not identity_match:
        result["verificationStatus"] = "rejected"
        result["reasonCodes"].append("ror_name_not_matched")
    if not domains:
        result["reasonCodes"].append("ror_domains_missing")
    urls = candidate_urls(item, organization)
    if not urls:
        result["reasonCodes"].append("website_url_missing")
    selected_url = urls[0] if urls else None
    if selected_url and domains:
        candidate_host = _host(selected_url)
        domain_match = domain_belongs(selected_url, domains)
        result["evidence"]["domainConsistency"] = {
            "candidateUrl": selected_url,
            "candidateHost": candidate_host,
            "rorDomains": domains,
            "domainMatch": domain_match,
        }
        if not domain_match:
            result["verificationStatus"] = "rejected"
            result["reasonCodes"].append("website_domain_not_in_ror_domains")
    elif selected_url:
        result["evidence"]["domainConsistency"] = {"candidateUrl": selected_url, "domainMatch": False, "rorDomains": domains}

    if result["verificationStatus"] == "rejected":
        result["reasons"] = list(result["reasonCodes"])
        return result
    if not selected_url:
        result["reasons"] = list(result["reasonCodes"])
        return result

    try:
        requested_homepage = homepage_url(selected_url)
        item_id = str(item.get("canonicalId") or item.get("universityId") or target_name)
        response, raw = capture_raw(
            raw_root,
            item_id,
            "homepage",
            requested_homepage,
            fetcher,
            timeout,
        )
        result["captureStatus"] = raw["captureStatus"]
        final_url = response.url or requested_homepage
        final_domain_match = domain_belongs(final_url, domains)
        body_text = decode_body(response)
        identity_page = page_identity(body_text, names)
        live = {
            "requestedUrl": requested_homepage,
            "finalUrl": final_url,
            "status": response.status,
            "captureStatus": raw["captureStatus"],
            "redirected": final_url.rstrip("/") != requested_homepage.rstrip("/"),
            "finalDomainMatch": final_domain_match,
            "raw": raw,
            **identity_page,
        }
        result["evidence"]["liveOfficialPage"] = live
        lower = body_text.casefold()
        if response.status in BLOCKED_STATUS or any(marker in lower for marker in WAF_MARKERS):
            result["verificationStatus"] = "blocked"
            result["reasonCodes"].append("waf_or_access_block")
        elif response.status < 200 or response.status >= 400:
            result["reasonCodes"].append("live_page_http_error")
        elif not final_domain_match:
            result["verificationStatus"] = "rejected"
            result["reasonCodes"].append("redirected_domain_not_in_ror_domains")
        elif not identity_page["structuredIdentityMatches"] or not identity_page["bodyMatches"]:
            result["reasonCodes"].append("live_page_identity_mismatch")
        elif identity_match and country_match and result["evidence"]["domainConsistency"].get("domainMatch"):
            result["verificationStatus"] = "verified"
            if live["redirected"]:
                result["reasonCodes"].append("redirected_within_ror_domain")

        if fetch_sitemap and response.status >= 200 and response.status < 400 and final_domain_match:
            sitemap_candidates = []
            for key in ("sitemapUrl", "sitemapURL", "officialSitemapUrl"):
                sitemap_candidates.extend(_as_strings(item.get(key)))
            if not sitemap_candidates:
                final_parts = urlsplit(final_url)
                sitemap_candidates = [urlunsplit((final_parts.scheme, final_parts.netloc, "/sitemap.xml", "", ""))]
            sitemap_url = sitemap_candidates[0]
            if domain_belongs(sitemap_url, domains):
                try:
                    sitemap_response, sitemap_raw = capture_raw(
                        raw_root,
                        item_id,
                        "sitemap",
                        sitemap_url,
                        fetcher,
                        timeout,
                    )
                    result["evidence"]["sitemap"] = {
                        "requestedUrl": sitemap_url,
                        "finalUrl": sitemap_response.url,
                        "status": sitemap_response.status,
                        "captureStatus": sitemap_raw["captureStatus"],
                        "finalDomainMatch": domain_belongs(sitemap_response.url, domains),
                        "raw": sitemap_raw,
                    }
                except (OSError, TimeoutError, ValueError) as error:
                    result["evidence"]["sitemap"] = {
                        "requestedUrl": sitemap_url,
                        "error": f"{type(error).__name__}: {error}",
                    }
            else:
                result["evidence"]["sitemap"] = {
                    "requestedUrl": sitemap_url,
                    "error": "sitemap_domain_not_in_ror_domains",
                }
    except (OSError, TimeoutError, ValueError) as error:
        result["verificationStatus"] = "blocked"
        result["captureStatus"] = "fetch-failed"
        result["reasonCodes"].append("live_page_fetch_failed")
        result["evidence"]["liveOfficialPage"] = {"error": f"{type(error).__name__}: {error}"}
    result["reasons"] = list(result["reasonCodes"])
    return result


def verify_items(
    payload: Any,
    raw_root: Path = DEFAULT_RAW,
    fetcher: Callable[[str, float], Any] = fetch_url,
    fetch_sitemap: bool = False,
    timeout: float = 30.0,
    worker_index: int = 0,
    worker_count: int = 1,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    if worker_count <= 0:
        raise ValueError("worker_count must be greater than zero")
    if worker_index < 0 or worker_index >= worker_count:
        raise ValueError("worker_index must be in [0, worker_count)")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")

    all_items = input_items(payload)
    selected_items = [item for index, item in enumerate(all_items) if index % worker_count == worker_index]
    if limit is not None:
        selected_items = selected_items[:limit]
    results = []
    for item in selected_items:
        verification = verify_candidate(item, raw_root, fetcher, fetch_sitemap, timeout)
        results.append({
            **item,
            "discoveryVerificationStatus": item.get("verificationStatus"),
            "discoveryCaptureStatus": item.get("captureStatus"),
            "captureStatus": verification["captureStatus"],
            "verificationStatus": verification["verificationStatus"],
            "verification": verification,
        })
    counts = {status: sum(row["verificationStatus"] == status for row in results) for status in ("verified", "review", "blocked", "rejected")}
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": {
            "rorIdentityRequired": True,
            "rorDomainConsistencyRequired": True,
            "liveOfficialPageRequired": True,
            "liveStructuredIdentityRequired": True,
            "liveVisibleBodyIdentityRequired": True,
            "rorAloneCannotVerify": True,
            "targetsModified": False,
            "manifestsModified": False,
            "sitemapOptional": bool(fetch_sitemap),
        },
        "summary": {"processed": len(results), **counts},
        "selection": {
            "totalInput": len(all_items),
            "workerIndex": worker_index,
            "workerCount": worker_count,
            "limit": limit,
            "selected": len(selected_items),
        },
        "items": results,
    }


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--fetch-sitemap", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--worker-index", type=_non_negative_int, default=0)
    parser.add_argument("--worker-count", type=_positive_int, default=1)
    parser.add_argument("--limit", type=_non_negative_int)
    args = parser.parse_args(argv)
    if args.worker_index >= args.worker_count:
        parser.error("--worker-index must be less than --worker-count")
    return args


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    output = verify_items(
        load_json(args.input),
        args.raw,
        fetch_sitemap=args.fetch_sitemap,
        timeout=args.timeout,
        worker_index=args.worker_index,
        worker_count=args.worker_count,
        limit=args.limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**output["summary"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
