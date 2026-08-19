"""Audit application-evidence coverage in the immutable raw crawl corpus.

The audit is deliberately read-only with respect to manifests and captured raw
files.  It inspects captured page bodies, links evidence pages back to program
pages through ``sourceUrl``, and aggregates university aliases under their
canonical id.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "scraper" / "playwright" / "_programs_full_raw"
DEFAULT_ALIASES = ROOT / "frontend" / "public" / "data" / "university_aliases.json"
DEFAULT_OUTPUT = ROOT / "scraper" / "playwright" / "_raw_application_evidence_audit.json"

CATEGORIES = ("requirements", "applicationWindow", "documents", "language")
TRACKING_QUERY = re.compile(r"^(?:utm_.+|fbclid|gclid|mc_cid|mc_eid|ref|source)$", re.I)

# These patterns intentionally require admission-oriented phrases rather than
# isolated words such as "English" or "date", which occur on most university pages.
SIGNAL_PATTERNS = {
    "requirements": re.compile(
        r"\b(?:admission|entry|academic|eligibility|application)\s+requirements?\b|"
        r"\b(?:admission|entry)\s+criteria\b|\bprerequisites?\b|\beligib(?:le|ility)\b|"
        r"\b(?:minimum|required)\s+(?:gpa|grade|degree|credits?)\b|"
        r"\b(?:requirements?|conditions?)\s+(?:for|of)\s+admission\b",
        re.I,
    ),
    "applicationWindow": re.compile(
        r"\bapplication\s+(?:period|window|round|timeline|dates?|opens?|closes?)\b|"
        r"\b(?:admission|application)\s+deadlines?\b|\bdeadline\s+(?:for|to)\s+appl(?:y|ication)\b|"
        r"\bapplications?\s+(?:open|close|start|end)\b|\b(?:fall|spring|autumn|winter)\s+intake\b",
        re.I,
    ),
    "deadline": re.compile(
        r"\b(?:admission|application|submission)\s+deadlines?\b|\bapplication\s+closes?\b|"
        r"\bdeadline\s+(?:for|to)\s+(?:appl(?:y|ication)|submit|submission)\b|"
        r"\b(?:submit|apply)\s+(?:before|by|no later than)\b",
        re.I,
    ),
    "documents": re.compile(
        r"\b(?:required|supporting|application)\s+documents?\b|\bdocument(?:s|ation)\s+(?:required|needed)\b|"
        r"\b(?:upload|submit|provide)\s+(?:the\s+following\s+)?documents?\b|"
        r"\b(?:curriculum vitae|motivation letter|statement of purpose|academic transcript|"
        r"recommendation letters?|letters? of recommendation)\b",
        re.I,
    ),
    "language": re.compile(
        r"\b(?:english|language)\s+(?:language\s+)?(?:requirements?|proficiency|certificate|test|score)\b|"
        r"\bproof of (?:english|language)\b|\b(?:ielts|toefl|cambridge english)\b|"
        r"\b(?:minimum|required)\s+(?:ielts|toefl)\s+score\b",
        re.I,
    ),
}


BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body\s*>", re.I | re.S)
IGNORED_HTML_RE = re.compile(r"<(script|style|noscript|svg|template)\b[^>]*>.*?</\1\s*>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")


def load_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return fallback


def url_key(value: Any) -> str:
    try:
        parts = urlsplit(str(value or ""))
        if not parts.scheme or not parts.netloc:
            return ""
        query = urlencode([(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
                           if not TRACKING_QUERY.match(key)])
        path = parts.path if parts.path == "/" else parts.path.rstrip("/")
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))
    except (TypeError, ValueError):
        return ""


def canonical_id(university_id: str, aliases: dict[str, str]) -> str:
    current = university_id
    seen: set[str] = set()
    while current not in seen and aliases.get(current, current) != current:
        seen.add(current)
        current = aliases[current]
    return current


def extract_json_text(payload: Any) -> str:
    if isinstance(payload, dict):
        raw = payload.get("raw")
        if isinstance(raw, dict):
            selected = [raw.get("documentTitle"), raw.get("mainText"), raw.get("bodyText"), raw.get("headings")]
            return extract_json_text(selected)
        return " ".join(extract_json_text(value) for value in payload.values())
    if isinstance(payload, list):
        return " ".join(extract_json_text(value) for value in payload)
    return payload if isinstance(payload, str) else ""


def read_raw_text(university_dir: Path, page: dict[str, Any]) -> str:
    raw_value = page.get("file") or page.get("rawFile")
    if page.get("status") != "captured" or not raw_value:
        return ""
    raw_path = Path(str(raw_value))
    if not raw_path.is_absolute():
        raw_path = university_dir / raw_path
    try:
        data = gzip.decompress(raw_path.read_bytes()) if raw_path.suffix == ".gz" else raw_path.read_bytes()
    except (FileNotFoundError, OSError, EOFError):
        return ""
    decoded = data.decode("utf-8", errors="replace")
    if raw_path.name.endswith(".json.gz") or raw_path.suffix == ".json":
        try:
            return " ".join(extract_json_text(json.loads(decoded)).split())
        except json.JSONDecodeError:
            return decoded
    body = BODY_RE.search(decoded)
    visible = body.group(1) if body else decoded
    visible = IGNORED_HTML_RE.sub(" ", visible)
    return " ".join(unescape(TAG_RE.sub(" ", visible)).split())


def detect_signals(text: str) -> set[str]:
    return {name for name, pattern in SIGNAL_PATTERNS.items() if pattern.search(text or "")}


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def build_audit(corpus: Path, aliases_path: Path, sample_limit: int = 10) -> dict[str, Any]:
    alias_payload = load_json(aliases_path, {}) or {}
    aliases = alias_payload.get("canonicalById", alias_payload) if isinstance(alias_payload, dict) else {}
    groups: dict[str, dict[str, Any]] = {}
    unreadable_manifests: list[str] = []

    for university_dir in sorted(path for path in corpus.iterdir() if path.is_dir() and path.name != "_quarantine"):
        manifest_path = university_dir / "manifest.json"
        try:
            manifest = load_json(manifest_path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            unreadable_manifests.append(str(manifest_path))
            continue
        if not isinstance(manifest, dict):
            continue
        uid = str(manifest.get("universityId") or university_dir.name)
        cid = canonical_id(uid, aliases)
        group = groups.setdefault(cid, {
            "canonicalId": cid, "universityName": "", "country": "", "aliasIds": set(),
            "programs": {}, "evidence": [], "pageRecords": {},
        })
        group["aliasIds"].add(uid)
        if uid == cid or not group["universityName"]:
            group["universityName"] = manifest.get("universityName") or uid
            group["country"] = manifest.get("country") or group["country"]

        pages = manifest.get("pages") or {}
        candidates = (manifest.get("discovery") or {}).get("programCandidates") or {}
        program_urls = {url_key(url) for url in candidates if url_key(url)}
        program_urls.update(url_key(url) for url, page in pages.items()
                            if isinstance(page, dict) and page.get("kind") == "program" and url_key(url))
        for program_url in program_urls:
            page = pages.get(program_url) or next(
                (record for url, record in pages.items() if url_key(url) == program_url), {}
            )
            entry = group["programs"].setdefault(program_url, {
                "url": program_url, "aliasIds": set(), "ownSignals": set(), "sources": defaultdict(list),
            })
            entry["aliasIds"].add(uid)
            if isinstance(page, dict):
                entry["ownSignals"].update(detect_signals(read_raw_text(university_dir, page)))

        for raw_url, page in pages.items():
            if not isinstance(page, dict):
                continue
            normalized = url_key(raw_url)
            if normalized:
                group["pageRecords"][normalized] = page
            if page.get("kind") != "evidence" or page.get("status") != "captured" or not page.get("file"):
                continue
            signals = detect_signals(read_raw_text(university_dir, page))
            if signals:
                group["evidence"].append({
                    "url": normalized or raw_url,
                    "sourceUrl": url_key(page.get("sourceUrl")),
                    "signals": signals,
                })

    universities: list[dict[str, Any]] = []
    for cid in sorted(groups):
        group = groups[cid]
        programs = group["programs"]
        program_urls = set(programs)

        for program in programs.values():
            for signal in program["ownSignals"]:
                program["sources"][signal].append({
                    "url": program["url"], "relation": "programPage", "inferredShared": False,
                })

        shared_evidence: list[dict[str, Any]] = []
        for evidence in group["evidence"]:
            source = evidence["sourceUrl"]
            seen: set[str] = set()
            while source and source not in program_urls and source not in seen:
                seen.add(source)
                parent = group["pageRecords"].get(source)
                source = url_key(parent.get("sourceUrl")) if isinstance(parent, dict) else ""
            if source in program_urls:
                for signal in evidence["signals"]:
                    programs[source]["sources"][signal].append({
                        "url": evidence["url"], "relation": "programEvidence", "inferredShared": False,
                    })
            else:
                shared_evidence.append(evidence)

        for evidence in shared_evidence:
            for program in programs.values():
                for signal in evidence["signals"]:
                    program["sources"][signal].append({
                        "url": evidence["url"], "relation": "sharedEvidence", "inferredShared": True,
                    })

        program_rows = []
        for program in sorted(programs.values(), key=lambda item: item["url"]):
            coverage = {}
            for category in CATEGORIES:
                sources = program["sources"].get(category, [])
                coverage[category] = {"covered": bool(sources), "sources": sources}
            deadline_sources = program["sources"].get("deadline", [])
            program_rows.append({
                "url": program["url"],
                "aliasIds": sorted(program["aliasIds"]),
                "ownSignals": sorted(program["ownSignals"]),
                "coverage": coverage,
                "deadline": {"covered": bool(deadline_sources), "sources": deadline_sources},
            })

        total = len(program_rows)
        coverage_summary = {}
        uncovered_samples = {}
        for category in CATEGORIES:
            covered = sum(row["coverage"][category]["covered"] for row in program_rows)
            coverage_summary[category] = {"coveredCount": covered, "coverageRate": _rate(covered, total)}
            uncovered_samples[category] = [row["url"] for row in program_rows
                                           if not row["coverage"][category]["covered"]][:sample_limit]
        deadline_covered = sum(row["deadline"]["covered"] for row in program_rows)
        universities.append({
            "canonicalId": cid,
            "universityName": group["universityName"],
            "country": group["country"],
            "aliasIds": sorted(group["aliasIds"]),
            "programCount": total,
            "coverage": coverage_summary,
            "uncoveredProgramSamples": uncovered_samples,
            "deadlineGap": {
                "coveredCount": deadline_covered,
                "coverageRate": _rate(deadline_covered, total),
                "uncoveredCount": total - deadline_covered,
                "samplePrograms": [row["url"] for row in program_rows if not row["deadline"]["covered"]][:sample_limit],
            },
            "programs": program_rows,
        })

    total_programs = sum(row["programCount"] for row in universities)
    summary_coverage = {}
    for category in CATEGORIES:
        covered = sum(row["coverage"][category]["coveredCount"] for row in universities)
        summary_coverage[category] = {"coveredCount": covered, "coverageRate": _rate(covered, total_programs)}
    deadline_covered = sum(row["deadlineGap"]["coveredCount"] for row in universities)
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "corpus": str(corpus.resolve()),
        "aliases": str(aliases_path.resolve()),
        "method": {
            "categories": list(CATEGORIES),
            "programEvidenceAssociation": "sourceUrl chain resolves to a program URL",
            "sharedEvidencePolicy": "unresolved school-level evidence applies to every canonical-university program",
            "sharedEvidenceMarker": "inferredShared=true",
        },
        "summary": {
            "canonicalUniversityCount": len(universities),
            "programCount": total_programs,
            "coverage": summary_coverage,
            "deadlineGap": {
                "coveredCount": deadline_covered,
                "coverageRate": _rate(deadline_covered, total_programs),
                "uncoveredCount": total_programs - deadline_covered,
            },
            "unreadableManifestCount": len(unreadable_manifests),
            "unreadableManifests": unreadable_manifests,
        },
        "universities": universities,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--aliases", type=Path, default=DEFAULT_ALIASES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    audit = build_audit(args.corpus, args.aliases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**audit["summary"], "output": str(args.output.resolve())}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
