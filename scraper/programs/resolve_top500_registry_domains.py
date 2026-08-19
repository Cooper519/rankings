"""Resolve Top 500 gap entities against the ROR organization registry.

ROR is used only as an identity and domain discovery hint.  A ROR match is
never treated as official programme evidence and never mutates crawl targets
or raw programme manifests.  Every API response is preserved before a scored
match is emitted so this discovery stage remains auditable and resumable.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "scraper" / "playwright" / "top500_official_discovery_queue_v2.json"
DEFAULT_OUTPUT = ROOT / "scraper" / "playwright" / "top500_registry_domain_hints.json"
DEFAULT_RAW = ROOT / "scraper" / "raw" / "registry" / "ror"
ROR_ENDPOINT = "https://api.ror.org/v2/organizations"

COUNTRY_ALIASES = {
    "czech republic": "czechia",
    "hong kong sar": "hong kong",
    "korea": "south korea",
    "republic of korea": "south korea",
    "russian federation": "russia",
    "taiwan, province of china": "taiwan",
    "turkiye": "turkey",
    "united states of america": "united states",
}
NAME_STOP_WORDS = {
    "and", "at", "college", "de", "for", "institute", "of", "school",
    "the", "universidad", "universita", "universitat", "universite",
    "universiteit", "university",
}
PROTECTED_NAME_QUALIFIERS = {
    "branch", "campus", "college", "faculty", "hospital", "institute",
    "medical", "metropolitan", "school", "system",
}
TOKEN_TRANSLATIONS = {
    "autonoma": "autonomous", "catolica": "catholic", "cattolica": "catholic",
    "catholique": "catholic", "nacional": "national", "nationale": "national",
    "politecnico": "polytechnic", "polytechnique": "polytechnic",
    "tecnica": "technical", "technische": "technical", "technique": "technical",
    "firenze": "florence", "koeln": "cologne", "koln": "cologne",
    "lisboa": "lisbon", "milano": "milan", "muenchen": "munich",
    "munchen": "munich", "napoli": "naples", "padova": "padua",
    "praha": "prague", "roma": "rome", "sevilla": "seville",
    "torino": "turin", "wien": "vienna",
}


@dataclass
class HttpCapture:
    requested_url: str
    final_url: str
    status: int
    headers: Dict[str, str]
    body: bytes


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def queue_items(payload: Any) -> List[dict]:
    if isinstance(payload, list):
        return payload
    for key in ("items", "queue", "targets", "gaps", "crawlTargetDraft", "entities"):
        if isinstance(payload, dict) and isinstance(payload.get(key), list):
            return payload[key]
    raise ValueError("input must be an array or contain an items/queue/targets/gaps array")


def ascii_text(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).casefold()


def normalized_name(value: str) -> str:
    # Parenthetical text is identity-bearing unless a query transformation has
    # explicitly established that it is only a short acronym or country tail.
    text = ascii_text(value or "").replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def semantic_tokens(value: str) -> Set[str]:
    return {
        TOKEN_TRANSLATIONS.get(token, token)
        for token in normalized_name(value).split()
        if len(token) > 1 and token not in NAME_STOP_WORDS
    }


def normalized_country(value: str) -> str:
    key = " ".join(ascii_text(value).replace("’", "'").split())
    return COUNTRY_ALIASES.get(key, key)


def display_name(organization: dict) -> str:
    names = organization.get("names") or []
    for item in names:
        if "ror_display" in (item.get("types") or []):
            return str(item.get("value") or "")
    return str(names[0].get("value") or "") if names else ""


def organization_names(organization: dict) -> List[str]:
    names = [str(item.get("value") or "").strip() for item in organization.get("names") or []]
    return [name for name in names if name]


def organization_country(organization: dict) -> str:
    locations = organization.get("locations") or []
    if not locations:
        return ""
    details = locations[0].get("geonames_details") or {}
    return str(details.get("country_name") or "")


def host_of(value: str) -> str:
    try:
        host = urlsplit(value).hostname.lower()
        return host[4:] if host.startswith("www.") else host
    except (AttributeError, ValueError):
        return ""


def registry_domains(organization: dict) -> List[str]:
    domains = {
        normalized[4:] if normalized.startswith("www.") else normalized
        for value in organization.get("domains") or [] if value
        for normalized in [str(value).casefold()]
    }
    links = organization.get("links") or []
    for link in links:
        value = link.get("value") if isinstance(link, dict) else link
        host = host_of(str(value or ""))
        if host and not host.endswith("wikipedia.org"):
            domains.add(host)
    return sorted(domain for domain in domains if domain)


def match_names(target: dict) -> List[str]:
    values = target.get("_registryMatchNames")
    if not isinstance(values, list):
        values = []
        country = str(target.get("country") or "")
        for record in source_name_records(target):
            values.append(record["name"])
            values.extend(
                transformed["name"]
                for transformed in safe_query_transforms(record["name"], country)
            )
    return unique_names(str(value or "") for value in values)


def score_organization(target: dict, organization: dict) -> dict:
    target_names = match_names(target)
    target_country = normalized_country(str(target.get("country") or ""))
    candidate_country = normalized_country(organization_country(organization))
    names = organization_names(organization)
    target_normalized = [normalized_name(name) for name in target_names]
    target_tokens = [semantic_tokens(name) for name in target_names]
    exact_name = any(
        candidate_normalized == expected
        for name in names
        for candidate_normalized in [normalized_name(name)]
        for expected in target_normalized
    )
    translated_exact = any(
        candidate_tokens == expected and bool(expected)
        for name in names
        for candidate_tokens in [semantic_tokens(name)]
        for expected in target_tokens
    )
    sequence = max((
        SequenceMatcher(None, expected, normalized_name(name)).ratio()
        for name in names for expected in target_normalized
    ), default=0.0)
    jaccard = max((
        len(expected & semantic_tokens(name)) / len(expected | semantic_tokens(name))
        for name in names for expected in target_tokens if expected | semantic_tokens(name)
    ), default=0.0)
    country_match = bool(target_country and candidate_country and target_country == candidate_country)
    domains = registry_domains(organization)

    score = 0.0
    score += 0.52 if exact_name else 0.38 if translated_exact else 0.0
    score += 0.22 * sequence
    score += 0.16 * jaccard
    score += 0.08 if country_match else -0.35
    score += 0.02 if domains else 0.0
    confidence = "high" if country_match and (exact_name or translated_exact) and score >= 0.88 else "review"
    return {
        "score": round(score, 4),
        "confidence": confidence,
        "exactName": exact_name,
        "translatedTokenExact": translated_exact,
        "sequenceSimilarity": round(sequence, 4),
        "tokenJaccard": round(jaccard, 4),
        "countryMatch": country_match,
        "candidateCountry": organization_country(organization),
        "registryDomains": domains,
    }


def select_match(target: dict, payload: dict) -> Tuple[Optional[dict], List[dict]]:
    scored = []
    for organization in payload.get("items") or []:
        scoring = score_organization(target, organization)
        scored.append({
            "rorId": organization.get("id"),
            "name": display_name(organization),
            **scoring,
        })
    scored.sort(key=lambda item: (-item["score"], item["name"], item.get("rorId") or ""))
    selected = scored[0] if scored and scored[0]["confidence"] == "high" else None
    return selected, scored


def query_url(name: str) -> str:
    return f'{ROR_ENDPOINT}?query={quote(chr(34) + name + chr(34))}'


def unique_names(values: Any) -> List[str]:
    result = []
    seen = set()
    for value in values:
        name = " ".join(str(value or "").split()).strip()
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            result.append(name)
    return result


def source_name_records(target: dict) -> List[dict]:
    records = []
    primary = target.get("name") or target.get("universityName")
    if primary:
        records.append({"name": str(primary), "source": "target.name"})
    for index, value in enumerate(target.get("sourceNames") or []):
        if isinstance(value, str) and value.strip():
            records.append({"name": value, "source": "sourceNames[%d]" % index})
    for index, appearance in enumerate(target.get("rankingAppearances") or []):
        if not isinstance(appearance, dict):
            continue
        value = appearance.get("name")
        if isinstance(value, str) and value.strip():
            source = str(appearance.get("source") or "unknown")
            records.append({
                "name": value,
                "source": "rankingAppearances[%d].name" % index,
                "rankingSource": source,
            })
    unique = []
    seen = set()
    for record in records:
        key = " ".join(record["name"].split()).casefold()
        if key and key not in seen:
            seen.add(key)
            unique.append(record)
    return unique


def short_parenthetical_abbreviation(value: str) -> bool:
    compact = re.sub(r"[^A-Za-z0-9]", "", value or "")
    words = re.findall(r"[A-Za-z0-9]+", value or "")
    return bool(
        2 <= len(compact) <= 12
        and len(words) <= 3
        and any(char.isalpha() for char in compact)
        and compact.upper() == compact
        and not (set(word.casefold() for word in words) & PROTECTED_NAME_QUALIFIERS)
    )


def safe_query_transforms(name: str, country: str) -> List[dict]:
    variants = []

    without_abbreviation = re.sub(
        r"\s*\(([^()]*)\)\s*",
        lambda match: " " if short_parenthetical_abbreviation(match.group(1)) else match.group(0),
        name,
    )
    without_abbreviation = " ".join(without_abbreviation.split())
    if without_abbreviation.casefold() != name.casefold():
        variants.append({
            "name": without_abbreviation,
            "transformations": ["remove-short-parenthetical-abbreviation"],
        })

    if "|" in name:
        before_pipe = " ".join(name.split("|", 1)[0].split()).strip(" ,;-/")
        if before_pipe and before_pipe.casefold() != name.casefold():
            variants.append({
                "name": before_pipe,
                "transformations": ["remove-local-name-after-pipe"],
            })

    country_text = " ".join(str(country or "").split())
    if country_text:
        escaped = re.escape(country_text)
        suffix_patterns = [
            r"\s+(?:-|–|—)\s*" + escaped + r"\s*$",
            r",\s*" + escaped + r"\s*$",
            r"\s*\(\s*" + escaped + r"\s*\)\s*$",
        ]
        for pattern in suffix_patterns:
            without_suffix = " ".join(re.sub(pattern, "", name, flags=re.IGNORECASE).split())
            if without_suffix and without_suffix.casefold() != name.casefold():
                variants.append({
                    "name": without_suffix,
                    "transformations": ["remove-ranking-country-suffix"],
                })

    return variants


def query_variants(target: dict) -> List[dict]:
    country = str(target.get("country") or "")
    variants = []
    seen = set()
    for source in source_name_records(target):
        candidates = [{"name": " ".join(source["name"].split()), "transformations": []}]
        candidates.extend(safe_query_transforms(candidates[0]["name"], country))
        for candidate in candidates:
            key = candidate["name"].casefold()
            if not candidate["name"] or key in seen:
                continue
            seen.add(key)
            variants.append({
                **candidate,
                "source": source["source"],
                "sourceName": source["name"],
                **({"rankingSource": source["rankingSource"]} if source.get("rankingSource") else {}),
                "queryUrl": query_url(candidate["name"]),
            })
    return variants


def query_urls(name: str) -> List[str]:
    """Backward-compatible URL helper for one target-name source."""
    return [item["queryUrl"] for item in query_variants({"name": name})]


def fetch_json(url: str, timeout: float) -> Tuple[HttpCapture, dict]:
    request = Request(url, headers={"User-Agent": "RankingSelect/1.0 (official-domain discovery)"})
    with urlopen(request, timeout=timeout) as response:
        capture = HttpCapture(
            requested_url=url,
            final_url=response.geturl(),
            status=int(response.status),
            headers={str(key): str(value) for key, value in response.headers.items()},
            body=response.read(),
        )
    return capture, json.loads(capture.body.decode("utf-8"))


def raw_file_for(raw_root: Path, university_id: str, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "_", university_id)
    return raw_root / safe_id / f"query_sha256={digest}.json.gz"


def manifest_file_for(raw_file: Path) -> Path:
    name = raw_file.name
    stem = name[:-8] if name.endswith(".json.gz") else name
    return raw_file.with_name(stem + ".manifest.json")


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def write_capture(raw_file: Path, capture: HttpCapture) -> dict:
    digest = hashlib.sha256(capture.body).hexdigest()
    manifest_file = manifest_file_for(raw_file)
    atomic_write_bytes(raw_file, gzip.compress(capture.body, mtime=0))
    manifest = {
        "schemaVersion": 1,
        "provider": "ROR",
        "kind": "organization-query",
        "requestedUrl": capture.requested_url,
        "finalUrl": capture.final_url,
        "status": capture.status,
        "headers": capture.headers,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "bytes": len(capture.body),
        "sha256": digest,
        "rawFile": str(raw_file.resolve()),
        "contentEncoding": "gzip",
    }
    atomic_write_json(manifest_file, manifest)
    return {**manifest, "manifestFile": str(manifest_file.resolve())}


def write_error_manifest(raw_file: Path, requested_url: str, error: Exception) -> Path:
    base = manifest_file_for(raw_file)
    manifest_file = base.with_name(base.name.replace(".manifest.json", ".error.manifest.json"))
    atomic_write_json(manifest_file, {
        "schemaVersion": 1,
        "provider": "ROR",
        "kind": "organization-query-error",
        "requestedUrl": requested_url,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "errorType": type(error).__name__,
        "error": str(error),
        "rawFile": None,
    })
    return manifest_file


def selected_organization(payload: dict, selected: Optional[dict]) -> Optional[dict]:
    if not selected:
        return None
    selected_id = selected.get("rorId")
    return next(
        (organization for organization in payload.get("items") or [] if organization.get("id") == selected_id),
        None,
    )


def resolve_query(
    target: dict,
    raw_root: Path,
    timeout: float,
    variant: dict,
    match_names_for_query: List[str],
) -> Tuple[dict, dict]:
    url = variant["queryUrl"]
    university_id = str(target.get("canonicalId") or target.get("universityId") or target.get("id") or "")
    raw_file = raw_file_for(raw_root, university_id, url)
    manifest_file = manifest_file_for(raw_file)
    if raw_file.exists() and manifest_file.exists():
        raw = gzip.decompress(raw_file.read_bytes())
        payload = json.loads(raw.decode("utf-8"))
        manifest = load_json(manifest_file)
        if hashlib.sha256(raw).hexdigest() != manifest.get("sha256"):
            raise ValueError(f"cached ROR response hash mismatch: {raw_file}")
        capture_status = "cached"
    else:
        try:
            capture, payload = fetch_json(url, timeout)
        except Exception as error:
            error_manifest = write_error_manifest(raw_file, url, error)
            setattr(error, "raw_error_manifest", str(error_manifest.resolve()))
            raise
        raw = capture.body
        write_capture(raw_file, capture)
        capture_status = "captured"
    scoring_target = {**target, "_registryMatchNames": match_names_for_query}
    selected, candidates = select_match(scoring_target, payload)
    return {
        "queryName": variant["name"],
        "querySource": variant["source"],
        "sourceName": variant["sourceName"],
        "transformations": variant["transformations"],
        **({"rankingSource": variant["rankingSource"]} if variant.get("rankingSource") else {}),
        "queryUrl": url,
        "rawFile": str(raw_file.resolve()),
        "rawManifestFile": str(manifest_file.resolve()),
        "rawSha256": hashlib.sha256(raw).hexdigest(),
        "captureStatus": capture_status,
        "resultCount": payload.get("number_of_results"),
        "selected": selected,
        "candidates": candidates[:10],
    }, payload


def resolve_item(target: dict, raw_root: Path, timeout: float) -> dict:
    variants = query_variants(target)
    attempts: List[dict] = []
    payload: dict = {}
    selected: Optional[dict] = None
    candidates: List[dict] = []
    eligible_match_names = unique_names(record["name"] for record in source_name_records(target))
    for variant in variants:
        try:
            attempt_match_names = unique_names(eligible_match_names + [variant["name"]])
            attempt, attempt_payload = resolve_query(
                target, raw_root, timeout, variant, attempt_match_names
            )
        except Exception as error:
            attempts.append({
                "queryName": variant["name"],
                "querySource": variant["source"],
                "sourceName": variant["sourceName"],
                "transformations": variant["transformations"],
                **({"rankingSource": variant["rankingSource"]} if variant.get("rankingSource") else {}),
                "queryUrl": variant["queryUrl"],
                "captureStatus": "error",
                "error": f"{type(error).__name__}: {error}",
                "rawErrorManifest": getattr(error, "raw_error_manifest", None),
            })
            continue
        attempts.append(attempt)
        payload = attempt_payload
        selected = attempt["selected"]
        candidates = attempt["candidates"]
        if selected:
            break
    if not attempts:
        raise ValueError("no ROR query variants generated")
    successful_attempts = [attempt for attempt in attempts if attempt.get("captureStatus") != "error"]
    if not successful_attempts:
        error = RuntimeError("all ROR query attempts failed")
        setattr(error, "raw_error_manifest", attempts[-1].get("rawErrorManifest"))
        raise error
    chosen = next(
        (attempt for attempt in successful_attempts if attempt.get("selected")),
        successful_attempts[-1],
    )
    organization = selected_organization(payload, selected)
    return {
        **target,
        "rorOrganization": organization,
        "registryResolution": {
            "provider": "ROR",
            "queryUrl": chosen["queryUrl"],
            "queryName": chosen["queryName"],
            "querySource": chosen["querySource"],
            "sourceName": chosen["sourceName"],
            "transformations": chosen["transformations"],
            "rawFile": chosen["rawFile"],
            "rawManifestFile": chosen["rawManifestFile"],
            "rawSha256": chosen["rawSha256"],
            "captureStatus": chosen["captureStatus"],
            "resultCount": chosen.get("resultCount"),
            "selected": selected,
            "candidates": candidates,
            "attempts": attempts,
        },
        "registryDomainHints": selected.get("registryDomains", []) if selected else [],
        "verificationStatus": "registry-domain-hint" if selected else "registry-review-required",
    }


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_output(source: Path, items: List[dict], errors: List[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceQueue": str(source.resolve()),
        "policy": {
            "provider": "Research Organization Registry",
            "registryMatchIsOfficialEvidence": False,
            "registryDomainIsOfficialVerification": False,
            "crawlTargetModified": False,
            "rawProgramManifestModified": False,
        },
        "summary": {
            "processed": len(items),
            "highConfidenceRegistryMatches": sum(bool(item.get("registryDomainHints")) for item in items),
            "reviewRequired": sum(not item.get("registryDomainHints") for item in items),
            "errors": len(errors),
        },
        "items": items,
        "errors": errors,
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--country", action="append", default=[])
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--wait", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    if args.worker_count < 1 or not 0 <= args.worker_index < args.worker_count:
        raise SystemExit("worker index must be within worker count")
    source_items = queue_items(load_json(args.input))
    countries = {normalized_country(country) for country in args.country}
    selected = [
        item for index, item in enumerate(source_items)
        if index % args.worker_count == args.worker_index
        and (not countries or normalized_country(str(item.get("country") or "")) in countries)
    ]
    if args.limit is not None:
        selected = selected[:args.limit]

    resolved: List[dict] = []
    errors: List[dict] = []
    for index, target in enumerate(selected, 1):
        try:
            item = resolve_item(target, args.raw, args.timeout)
            resolved.append(item)
            print(f"[ror] {index}/{len(selected)} {item.get('canonicalId') or item.get('universityId')} {item['verificationStatus']}")
        except Exception as error:  # Preserve failures as retryable discovery records.
            errors.append({
                "canonicalId": target.get("canonicalId") or target.get("universityId"),
                "name": target.get("name"),
                "country": target.get("country"),
                "error": f"{type(error).__name__}: {error}",
                "rawErrorManifest": getattr(error, "raw_error_manifest", None),
            })
        if index < len(selected) and args.wait > 0:
            time.sleep(args.wait)
    output = build_output(args.input, resolved, errors)
    atomic_write_json(args.output, output)
    print(json.dumps({**output["summary"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
