"""Build a read-only identity triage for unresolved official websites.

The report does not change verification status or relax any verification
threshold. It explains which evidence path should be attempted next.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VERIFICATIONS = [
    ROOT / "scraper" / "playwright" / "top500_official_website_verification_v3.json",
    ROOT / "scraper" / "playwright" / "top500_official_website_verification_recovered15_v3.json",
]
DEFAULT_RELATIONSHIPS = ROOT / "scraper" / "programs" / "top500_institution_relationships.json"
DEFAULT_JSON = ROOT / "scraper" / "playwright" / "top500_official_identity_triage_v3.json"
DEFAULT_MARKDOWN = ROOT / "scraper" / "playwright" / "top500_official_identity_triage_v3.md"

CATEGORY_ORDER = [
    "auto-recoverable",
    "relationship-rule-required",
    "ror-missing",
    "true-rejection",
    "blocked",
]
NON_MERGING_RELATION_TYPES = {"successorOf", "systemCampus"}

CATEGORY_LABELS = {
    "auto-recoverable": "Auto-recoverable evidence gap",
    "relationship-rule-required": "Institution relationship rule required",
    "ror-missing": "ROR match missing",
    "true-rejection": "True identity rejection",
    "blocked": "Capture or rendering blocked",
}

CATEGORY_NEXT_STEPS = {
    "auto-recoverable": (
        "Capture the indicated multilingual, acronym/brand, or official redirect evidence and rerun the unchanged verifier."
    ),
    "relationship-rule-required": (
        "Resolve institution grain with a reviewed sameInstitution, formerName, successorOf, systemCampus, or distinctInstitution rule before retrying identity verification."
    ),
    "ror-missing": (
        "Review the saved ROR candidates and query variants; require a high-confidence same-country ROR identity plus intact raw and manifest evidence."
    ),
    "true-rejection": (
        "Reject the selected ROR organization for this target and restart ROR discovery without reusing the rejected child or different institution."
    ),
    "blocked": (
        "Use browser-rendered capture or an official alternate-language/homepage route; stop for CAPTCHA and retain the current review status until both identity checks pass."
    ),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def input_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "results", "queue", "targets"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError("verification input must contain an item array")


def merged_verification_items(payloads: Iterable[Any]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for payload in payloads:
        for item in input_items(payload):
            identifier = str(item.get("canonicalId") or item.get("universityId") or "")
            if not identifier:
                raise ValueError("verification item is missing canonicalId/universityId")
            if identifier not in merged:
                order.append(identifier)
            merged[identifier] = item
    return [merged[identifier] for identifier in order]


def normalized(value: str) -> str:
    text = "".join(
        char for char in unicodedata.normalize("NFKD", value or "")
        if not unicodedata.combining(char)
    ).casefold().replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", text))


def canonical_slug(value: str) -> str:
    return "u_" + normalized(value).replace(" ", "_")


def host(value: str) -> str:
    try:
        parsed = urlsplit(value if "://" in (value or "") else "https://" + (value or ""))
        return (parsed.hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def base_host(value: str) -> str:
    return re.sub(r"^www\d*\.", "", host(value))


def verification_details(item: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    verification = item.get("verification") or {}
    return verification, list(verification.get("reasonCodes") or [])


def ror_names(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    organization = item.get("rorOrganization") or {}
    return [name for name in (organization.get("names") or []) if name.get("value")]


def direct_relationships(item: Dict[str, Any], relationships: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    identifiers = {str(item.get("canonicalId") or "")}
    identifiers.update(str(value) for value in (item.get("sourceUniversityIds") or []))
    return [
        relation for relation in relationships
        if identifiers.intersection(str(value) for value in (relation.get("memberIds") or []))
    ]


def selected_ror_name(item: Dict[str, Any]) -> str:
    selected = (item.get("registryResolution") or {}).get("selected") or {}
    return str(selected.get("name") or "")


def inferred_relationships(item: Dict[str, Any], relationships: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected_slug = canonical_slug(selected_ror_name(item)) if selected_ror_name(item) else ""
    return [
        relation for relation in relationships
        if selected_slug and selected_slug in set(relation.get("memberIds") or [])
    ]


def relationship_context(item: Dict[str, Any], relationships: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    seen = set()
    for relation in direct_relationships(item, relationships) + inferred_relationships(item, relationships):
        identifier = relation.get("id")
        if identifier not in seen:
            output.append(relation)
            seen.add(identifier)
    return output


def native_title_matches(item: Dict[str, Any]) -> List[str]:
    verification, _ = verification_details(item)
    live = (verification.get("evidence") or {}).get("liveOfficialPage") or {}
    title = str(live.get("title") or "").casefold()
    matches = []
    for name in ror_names(item):
        value = str(name.get("value") or "")
        if any(ord(char) > 127 for char in value) and value.casefold() in title:
            matches.append(value)
    return matches


def target_parenthetical(item: Dict[str, Any]) -> Optional[str]:
    match = re.search(r"\(([^()]*)\)\s*$", str(item.get("name") or ""))
    return match.group(1).strip() if match else None


def target_without_parenthetical(item: Dict[str, Any]) -> str:
    return re.sub(r"\s*\([^()]*\)\s*$", "", str(item.get("name") or "")).strip()


def target_without_any_parenthetical(item: Dict[str, Any]) -> str:
    return " ".join(re.sub(r"\s*\([^()]*\)\s*", " ", str(item.get("name") or "")).split())


def base_name_matches_ror(item: Dict[str, Any]) -> bool:
    base = normalized(target_without_parenthetical(item))
    if not base:
        return False
    values = [selected_ror_name(item)] + [str(name.get("value") or "") for name in ror_names(item)]
    return any(base == normalized(value) for value in values if value)


def parenthetical_is_audited_alias(item: Dict[str, Any]) -> bool:
    qualifier = target_parenthetical(item)
    if not qualifier or not base_name_matches_ror(item):
        return False
    qualifier_norm = normalized(re.sub(r"^aka\s+", "", qualifier, flags=re.I))
    aliases = [str(name.get("value") or "") for name in ror_names(item)]
    target_country = normalized(str(item.get("country") or ""))
    for alias in aliases:
        alias_norm = normalized(alias)
        if len(alias_norm) >= 3 and (qualifier_norm == alias_norm or alias_norm in qualifier_norm):
            return True
    compact = re.sub(r"[^A-Za-z0-9]", "", qualifier)
    if 2 <= len(compact) <= 12 and compact.upper() == compact:
        return True
    if target_country and qualifier_norm.endswith(target_country):
        prefix = qualifier_norm[:-len(target_country)].strip()
        return any(prefix == normalized(alias) for alias in aliases if prefix)
    return False


def target_acronym_in_title(item: Dict[str, Any]) -> Optional[str]:
    qualifier = target_parenthetical(item)
    if not qualifier:
        return None
    compact = re.sub(r"[^A-Za-z0-9]", "", qualifier)
    if not (2 <= len(compact) <= 12 and compact.upper() == compact):
        return None
    verification, _ = verification_details(item)
    title = str(((verification.get("evidence") or {}).get("liveOfficialPage") or {}).get("title") or "")
    return qualifier if normalized(qualifier) and normalized(qualifier) in normalized(title) else None


def relationship_rule_needed(
    item: Dict[str, Any], relationships: Sequence[Dict[str, Any]], reason_codes: Sequence[str]
) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    context = relationship_context(item, relationships)
    binding = [relation for relation in context if relation.get("type") in NON_MERGING_RELATION_TYPES]
    if binding:
        return True, context, "configured-non-merging-relationship"
    if "ror_name_not_matched" in reason_codes and target_parenthetical(item) and base_name_matches_ror(item):
        if not parenthetical_is_audited_alias(item):
            return True, context, "unreviewed-campus-system-or-name-qualifier"
    if (
        "ror_name_not_matched" in reason_codes
        and target_parenthetical(item) is None
        and re.search(r"\([^()]+\)", str(item.get("name") or ""))
    ):
        unqualified = normalized(target_without_any_parenthetical(item))
        values = [selected_ror_name(item)] + [str(name.get("value") or "") for name in ror_names(item)]
        if unqualified and any(unqualified == normalized(value) for value in values if value):
            return True, context, "unreviewed-campus-system-or-name-qualifier"
    return False, context, None


def auto_recovery_mode(item: Dict[str, Any], reason_codes: Sequence[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    verification, _ = verification_details(item)
    evidence = verification.get("evidence") or {}
    live = evidence.get("liveOfficialPage") or {}
    native_matches = native_title_matches(item)
    if "live_page_identity_mismatch" in reason_codes and native_matches:
        return "multilingual-title", {"matchedNativeNames": native_matches, "title": live.get("title")}
    if "live_page_identity_mismatch" in reason_codes and live.get("bodyMatches"):
        return "acronym-or-brand-title", {
            "title": live.get("title"),
            "bodyMatchedName": live.get("bodyMatchedName"),
        }
    acronym = target_acronym_in_title(item)
    if "live_page_identity_mismatch" in reason_codes and acronym:
        return "acronym-title", {"title": live.get("title"), "targetAcronym": acronym}
    if "ror_name_not_matched" in reason_codes and parenthetical_is_audited_alias(item):
        return "parenthetical-acronym-or-brand", {
            "targetQualifier": target_parenthetical(item),
            "rorSelectedName": selected_ror_name(item),
        }
    if "redirected_domain_not_in_ror_domains" in reason_codes:
        domain = evidence.get("domainConsistency") or {}
        candidate = str(domain.get("candidateUrl") or "")
        final = str(live.get("finalUrl") or "")
        same_host_family = bool(base_host(candidate) and base_host(candidate) == base_host(final))
        page_identity = bool(live.get("titleMatches") or live.get("bodyMatches"))
        status = live.get("status")
        if isinstance(status, int) and 200 <= status < 400 and (same_host_family or page_identity):
            return "official-domain-redirect", {
                "candidateHost": host(candidate),
                "finalHost": host(final),
                "sameHostFamily": same_host_family,
                "pageIdentitySignal": page_identity,
            }
    return None, {}


def classify(item: Dict[str, Any], relationships: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    verification, reason_codes = verification_details(item)
    status = str(item.get("verificationStatus") or verification.get("verificationStatus") or "")
    needs_rule, relations, relationship_signal = relationship_rule_needed(item, relationships, reason_codes)
    if needs_rule:
        category = "relationship-rule-required"
        mode = relationship_signal
        signals: Dict[str, Any] = {}
    elif "ror_match_missing" in reason_codes:
        category = "ror-missing"
        mode = "saved-ror-candidates-require-review"
        signals = {}
    else:
        auto_mode, signals = auto_recovery_mode(item, reason_codes)
        if auto_mode:
            category = "auto-recoverable"
            mode = auto_mode
        elif status == "rejected":
            category = "true-rejection"
            mode = "selected-ror-identity-conflicts-with-target"
        else:
            category = "blocked"
            mode = "http-error" if "live_page_http_error" in reason_codes else "static-page-identity-inconclusive"
    return {
        "category": category,
        "recoveryMode": mode,
        "signals": signals,
        "relationships": relations,
    }


def portable_path(value: Any) -> Optional[str]:
    if not value:
        return None
    path = Path(str(value))
    try:
        return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return str(path)


def digest_raw(path: Path) -> str:
    if path.suffix.casefold() == ".gz":
        with gzip.open(str(path), "rb") as source:
            body = source.read()
    else:
        body = path.read_bytes()
    return hashlib.sha256(body).hexdigest()


def ror_raw_evidence(item: Dict[str, Any]) -> Dict[str, Any]:
    resolution = item.get("registryResolution") or {}
    attempts = list(resolution.get("attempts") or [])
    if not attempts and (resolution.get("rawFile") or resolution.get("rawManifestFile")):
        attempts = [resolution]
    references = []
    for attempt in attempts:
        manifest_path = Path(str(attempt.get("rawManifestFile") or "")) if attempt.get("rawManifestFile") else None
        raw_path = Path(str(attempt.get("rawFile") or "")) if attempt.get("rawFile") else None
        manifest = None
        manifest_error = None
        if manifest_path and manifest_path.exists():
            try:
                manifest = load_json(manifest_path)
            except (OSError, ValueError) as error:
                manifest_error = "%s: %s" % (type(error).__name__, error)
        if manifest and not raw_path:
            raw_value = manifest.get("rawFile")
            raw_path = Path(str(raw_value)) if raw_value else None
        expected_hash = str(attempt.get("rawSha256") or (manifest or {}).get("sha256") or "")
        actual_hash = None
        hash_error = None
        if raw_path and raw_path.exists():
            try:
                actual_hash = digest_raw(raw_path)
            except (OSError, EOFError, gzip.BadGzipFile) as error:
                hash_error = "%s: %s" % (type(error).__name__, error)
        references.append({
            "queryUrl": attempt.get("queryUrl"),
            "queryName": attempt.get("queryName"),
            "captureStatus": attempt.get("captureStatus"),
            "resultCount": attempt.get("resultCount"),
            "rawFile": portable_path(raw_path),
            "manifestFile": portable_path(manifest_path),
            "rawPresent": bool(raw_path and raw_path.exists()),
            "manifestPresent": bool(manifest_path and manifest_path.exists()),
            "expectedSha256": expected_hash or None,
            "actualSha256": actual_hash,
            "hashVerified": bool(expected_hash and actual_hash and expected_hash == actual_hash),
            "manifestError": manifest_error,
            "hashError": hash_error,
        })
    return {
        "attemptCount": len(references),
        "rawPresent": sum(reference["rawPresent"] for reference in references),
        "manifestPresent": sum(reference["manifestPresent"] for reference in references),
        "hashVerified": sum(reference["hashVerified"] for reference in references),
        "hashFailures": sum(
            bool(reference["expectedSha256"] and reference["actualSha256"] and not reference["hashVerified"])
            for reference in references
        ),
        "references": references,
    }


def compact_relationship(relation: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": relation.get("id"),
        "type": relation.get("type"),
        "memberIds": relation.get("memberIds") or [],
        "canonicalId": relation.get("canonicalId"),
        "rationale": relation.get("rationale"),
    }


def build_report(
    verification_payloads: Iterable[Any], relationship_payload: Dict[str, Any], sample_size: int = 5
) -> Dict[str, Any]:
    relationships = list(relationship_payload.get("relationships") or [])
    merged = merged_verification_items(verification_payloads)
    unresolved = [item for item in merged if item.get("verificationStatus") in {"review", "rejected"}]
    rows = []
    for item in unresolved:
        result = classify(item, relationships)
        raw = ror_raw_evidence(item)
        verification, reason_codes = verification_details(item)
        live = (verification.get("evidence") or {}).get("liveOfficialPage") or {}
        row = {
            "canonicalId": item.get("canonicalId"),
            "name": item.get("name"),
            "country": item.get("country"),
            "rankingSources": item.get("rankingSources") or [],
            "sourceUniversityIds": item.get("sourceUniversityIds") or [],
            "originalVerificationStatus": item.get("verificationStatus"),
            "reasonCodes": reason_codes,
            "category": result["category"],
            "recoveryMode": result["recoveryMode"],
            "signals": result["signals"],
            "relationships": [compact_relationship(relation) for relation in result["relationships"]],
            "rorIdentity": {
                "rorId": ((verification.get("evidence") or {}).get("registryIdentity") or {}).get("rorId"),
                "selectedName": selected_ror_name(item) or None,
                "selectedDomains": ((item.get("registryResolution") or {}).get("selected") or {}).get("registryDomains") or [],
            },
            "livePage": {
                "requestedUrl": live.get("requestedUrl"),
                "finalUrl": live.get("finalUrl"),
                "httpStatus": live.get("status"),
                "title": live.get("title"),
                "titleMatches": live.get("titleMatches"),
                "bodyMatches": live.get("bodyMatches"),
            },
            "rorRawEvidence": raw,
            "nextStep": CATEGORY_NEXT_STEPS[result["category"]],
            "statusGuardrail": "no-status-change",
        }
        rows.append(row)
    rows.sort(key=lambda row: (CATEGORY_ORDER.index(row["category"]), str(row["country"]), str(row["name"])))

    category_counts = Counter(row["category"] for row in rows)
    status_counts = Counter(row["originalVerificationStatus"] for row in rows)
    reason_counts = Counter(code for row in rows for code in row["reasonCodes"])
    mode_counts = Counter(row["recoveryMode"] for row in rows)
    raw_summary = {
        "attempts": sum(row["rorRawEvidence"]["attemptCount"] for row in rows),
        "rawPresent": sum(row["rorRawEvidence"]["rawPresent"] for row in rows),
        "manifestPresent": sum(row["rorRawEvidence"]["manifestPresent"] for row in rows),
        "hashVerified": sum(row["rorRawEvidence"]["hashVerified"] for row in rows),
        "hashFailures": sum(row["rorRawEvidence"]["hashFailures"] for row in rows),
    }
    groups = []
    for category in CATEGORY_ORDER:
        members = [row for row in rows if row["category"] == category]
        groups.append({
            "category": category,
            "label": CATEGORY_LABELS[category],
            "count": len(members),
            "nextStep": CATEGORY_NEXT_STEPS[category],
            "samples": [
                {
                    "canonicalId": row["canonicalId"],
                    "name": row["name"],
                    "country": row["country"],
                    "recoveryMode": row["recoveryMode"],
                    "reasonCodes": row["reasonCodes"],
                }
                for row in members[:sample_size]
            ],
        })
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "statuses": ["review", "rejected"],
            "mergedInputPolicy": "later verification files override earlier files by canonicalId",
            "relationshipPolicy": relationship_payload.get("policy") or {},
        },
        "guardrails": {
            "readOnlyDiagnosis": True,
            "verificationStatusesChanged": False,
            "thresholdsChanged": False,
            "verifiedUpgradeProposed": False,
            "rorAloneCannotVerify": True,
        },
        "summary": {
            "entities": len(rows),
            "inputStatusCounts": dict(sorted(status_counts.items())),
            "categoryCounts": {category: category_counts.get(category, 0) for category in CATEGORY_ORDER},
            "recoveryModeCounts": dict(sorted(mode_counts.items())),
            "reasonCodeCounts": dict(sorted(reason_counts.items())),
            "rorRawEvidence": raw_summary,
        },
        "groups": groups,
        "items": rows,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Top 500 official identity triage v3",
        "",
        "Read-only diagnosis of merged `review` and `rejected` official website records. No entity is upgraded, no threshold is lowered, and ROR alone remains insufficient for verification.",
        "",
        "## Summary",
        "",
        "- Entities: %s (`review`: %s, `rejected`: %s)" % (
            summary["entities"],
            summary["inputStatusCounts"].get("review", 0),
            summary["inputStatusCounts"].get("rejected", 0),
        ),
        "- ROR raw closure: %s/%s hashes verified; %s hash failures" % (
            summary["rorRawEvidence"]["hashVerified"],
            summary["rorRawEvidence"]["attempts"],
            summary["rorRawEvidence"]["hashFailures"],
        ),
        "",
        "| Group | Count | Next step |",
        "| --- | ---: | --- |",
    ]
    for group in report["groups"]:
        lines.append("| %s | %s | %s |" % (group["label"], group["count"], group["nextStep"]))
    lines.extend(["", "## Samples", ""])
    for group in report["groups"]:
        lines.append("### %s (%s)" % (group["label"], group["count"]))
        if not group["samples"]:
            lines.append("- None")
        for sample in group["samples"]:
            lines.append(
                "- `%s` - %s (%s); `%s`; reasons: `%s`" % (
                    sample["canonicalId"], sample["name"], sample["country"],
                    sample["recoveryMode"], ", ".join(sample["reasonCodes"]),
                )
            )
        lines.append("")
    lines.extend([
        "## Guardrails",
        "",
        "- Preserve every `originalVerificationStatus` value.",
        "- Do not convert a multilingual/acronym/domain signal directly to `verified`; capture evidence and rerun the unchanged verifier.",
        "- Apply only reviewed relationship rules. `successorOf`, `systemCampus`, and `distinctInstitution` remain non-merging.",
        "- Stop for CAPTCHA or human-verification challenges.",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verification", type=Path, action="append")
    parser.add_argument("--relationships", type=Path, default=DEFAULT_RELATIONSHIPS)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--sample-size", type=int, default=5)
    args = parser.parse_args(argv)
    if args.sample_size < 0:
        parser.error("--sample-size must be non-negative")
    verification_paths = args.verification or DEFAULT_VERIFICATIONS
    report = build_report(
        [load_json(path) for path in verification_paths],
        load_json(args.relationships),
        args.sample_size,
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown_output.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
