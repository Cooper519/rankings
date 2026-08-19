"""Build an offline engineering-priority queue for zero-candidate schools.

The builder reads the existing browser-navigation queue and the entity coverage
audit. It verifies each recorded homepage raw body, extracts engineering
signals from visible HTML text, and sorts only by signal priority, country,
recorded index URL, and university id. It never creates URLs or performs
network requests.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE_INPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top500_zero_candidate_browser_navigation_queue_v4.json"
)
COVERAGE_INPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top500_goal_entity_coverage_v5.json"
)
OUTPUT = (
    ROOT
    / "scraper"
    / "playwright"
    / "top500_engineering_zero_candidate_browser_queue_v4.json"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WHITESPACE_RE = re.compile(r"\s+")

# Ordered from the most specific institutional signals to broader discipline
# terms. A phrase is counted once per visible text block.
ENGINEERING_PATTERNS = (
    ("school/faculty/college of engineering", 12, re.compile(
        r"\b(?:school|faculty|college|institute|department)\s+of\s+engineering\b",
        re.IGNORECASE,
    )),
    ("engineering and technology", 11, re.compile(
        r"\bengineering\s+(?:and|&)\s+technology\b", re.IGNORECASE
    )),
    ("engineering", 8, re.compile(r"\bengineering\b", re.IGNORECASE)),
    ("civil engineering", 7, re.compile(
        r"\bcivil\s+engineering\b", re.IGNORECASE
    )),
    ("mechanical engineering", 7, re.compile(
        r"\bmechanical\s+engineering\b", re.IGNORECASE
    )),
    ("electrical/electronic engineering", 7, re.compile(
        r"\b(?:electrical|electronic|electronics)\s+engineering\b",
        re.IGNORECASE,
    )),
    ("chemical engineering", 7, re.compile(
        r"\bchemical\s+engineering\b", re.IGNORECASE
    )),
    ("computer/software engineering", 7, re.compile(
        r"\b(?:computer|software)\s+engineering\b", re.IGNORECASE
    )),
    ("biomedical engineering", 7, re.compile(
        r"\bbiomedical\s+engineering\b", re.IGNORECASE
    )),
    ("aerospace engineering", 7, re.compile(
        r"\baerospace\s+engineering\b", re.IGNORECASE
    )),
    ("environmental engineering", 7, re.compile(
        r"\benvironmental\s+engineering\b", re.IGNORECASE
    )),
    ("industrial engineering", 7, re.compile(
        r"\bindustrial\s+engineering\b", re.IGNORECASE
    )),
    ("materials engineering", 7, re.compile(
        r"\bmaterials?\s+engineering\b", re.IGNORECASE
    )),
    ("energy engineering", 7, re.compile(
        r"\benergy\s+engineering\b", re.IGNORECASE
    )),
    ("robotics/mechatronics", 5, re.compile(
        r"\b(?:robotics|mechatronics)\b", re.IGNORECASE
    )),
    ("technology", 2, re.compile(r"\btechnolog(?:y|ies)\b", re.IGNORECASE)),
    ("institute of technology", 5, re.compile(
        r"\binstitute\s+of\s+technology\b", re.IGNORECASE
    )),
)

SKIP_TAGS = {
    "head",
    "title",
    "script",
    "style",
    "noscript",
    "template",
    "svg",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


class VisibleTextParser(HTMLParser):
    """Collect text nodes outside non-visible HTML containers."""

    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self._skip_depth = 0
        self.blocks: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.casefold() in SKIP_TAGS:
            self._skip_depth += 1

    def handle_startendtag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = WHITESPACE_RE.sub(" ", html.unescape(data)).strip()
            if text:
                self.blocks.append(text)


def visible_text_blocks(body: bytes) -> List[str]:
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))
    parser.close()
    return parser.blocks


def clipped_context(text: str, start: int, end: int, limit: int = 180) -> str:
    left = max(0, start - 70)
    right = min(len(text), end + 110)
    snippet = WHITESPACE_RE.sub(" ", text[left:right]).strip()
    if left:
        snippet = "..." + snippet
    if right < len(text):
        snippet += "..."
    return snippet[:limit]


def extract_engineering_signals(body: bytes) -> Dict[str, Any]:
    blocks = visible_text_blocks(body)
    matches: List[Dict[str, Any]] = []
    matched_labels = set()
    score = 0
    for block_index, block in enumerate(blocks):
        for label, weight, pattern in ENGINEERING_PATTERNS:
            match = pattern.search(block)
            if not match:
                continue
            matched_labels.add(label)
            score += weight
            matches.append({
                "label": label,
                "text": match.group(0),
                "blockIndex": block_index,
                "context": clipped_context(block, match.start(), match.end()),
                "weight": weight,
            })

    # A homepage with no exact discipline phrase is still useful when it
    # visibly exposes engineering/technology navigation terminology.
    if score >= 12:
        level = "strong"
    elif score >= 5:
        level = "moderate"
    elif score:
        level = "weak"
    else:
        level = "none"
    return {
        "level": level,
        "score": score,
        "matchedLabels": sorted(matched_labels),
        "matches": matches,
        "visibleTextBlockCount": len(blocks),
        "evidenceType": "offline-homepage-raw-visible-text",
    }


def verify_raw(item: Dict[str, Any]) -> bytes:
    source_raw = item.get("sourceRaw") or {}
    raw_file_value = source_raw.get("rawFile")
    expected = source_raw.get("sha256")
    if not isinstance(raw_file_value, str) or not raw_file_value:
        raise ValueError("source raw file is missing")
    if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
        raise ValueError("source raw sha256 is invalid")
    body = Path(raw_file_value).resolve().read_bytes()
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError("source raw SHA-256 mismatch")
    recorded_bytes = source_raw.get("bytes")
    if isinstance(recorded_bytes, bool) or (
        recorded_bytes is not None
        and (not isinstance(recorded_bytes, int) or recorded_bytes != len(body))
    ):
        raise ValueError("source raw byte count mismatch")
    return body


def coverage_map(payload: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("entities"), list):
        raise ValueError("coverage payload must contain an entities array")
    result: Dict[str, Dict[str, Any]] = {}
    for entity in payload["entities"]:
        if not isinstance(entity, dict):
            continue
        canonical_id = entity.get("canonicalId")
        if isinstance(canonical_id, str) and canonical_id:
            if canonical_id in result:
                raise ValueError("duplicate coverage canonicalId: " + canonical_id)
            result[canonical_id] = entity
    return result


def priority_steps(signals: Dict[str, Any]) -> List[Dict[str, Any]]:
    labels = signals.get("matchedLabels") or []
    engineering_first = bool(labels)
    return [
        {
            "order": 1,
            "action": "inspect-visible-navigation-for-engineering-catalog",
            "visibleTextSignals": labels or [
                "Engineering",
                "Technology",
                "Graduate",
                "Postgraduate",
                "Master",
                "Programs",
            ],
            "priority": "first" if engineering_first else "first-available",
            "constraints": [
                "Use only links or controls present in the rendered DOM.",
                "Record the DOM-provided href before following a link.",
                "Do not derive a URL from a label, domain, or URL pattern.",
            ],
        },
        {
            "order": 2,
            "action": "expand-visible-menus-and-inspect-engineering-links",
            "priority": "second",
            "constraints": [
                "Click only visible menu controls.",
                "Prefer engineering faculty, school, department, and technology links.",
                "Keep navigation on the approved official domain.",
            ],
        },
        {
            "order": 3,
            "action": "use-visible-site-search-if-present",
            "queries": [
                "engineering masters",
                "engineering postgraduate programs",
                "engineering graduate degrees",
            ],
            "priority": "third",
            "constraints": [
                "Use only a search control visible in the rendered DOM.",
                "Submit through the visible form or control.",
                "Do not infer or construct a search endpoint.",
            ],
        },
        {
            "order": 4,
            "action": "capture-discovered-engineering-evidence",
            "priority": "fourth",
            "constraints": [
                "Preserve rendered DOM and manifest before extracting links.",
                "Accept only DOM-provided URLs on approved official domains.",
                "Record source page, anchor text, href, final URL, and hash.",
            ],
        },
    ]


def build_queue(
    queue_payload: Any,
    coverage_payload: Any,
    generated_at: Optional[str] = None,
    source_queue_file: str = str(QUEUE_INPUT),
    source_coverage_file: str = str(COVERAGE_INPUT),
) -> Dict[str, Any]:
    if not isinstance(queue_payload, dict) or not isinstance(queue_payload.get("items"), list):
        raise ValueError("browser queue payload must contain an items array")
    coverage = coverage_map(coverage_payload)
    items: List[Dict[str, Any]] = []
    exclusions = Counter()
    for source_item in queue_payload["items"]:
        if not isinstance(source_item, dict):
            exclusions["invalid-queue-item"] += 1
            continue
        university_id = source_item.get("universityId")
        entity = coverage.get(university_id)
        if not isinstance(university_id, str) or not university_id:
            exclusions["university-id-missing"] += 1
            continue
        if entity is None:
            exclusions["coverage-entity-missing"] += 1
            continue
        if entity.get("category") != "verified-zero-candidates":
            exclusions["coverage-not-verified-zero-candidates"] += 1
            continue
        if entity.get("officialVerificationStatus") != "verified":
            exclusions["coverage-not-verified"] += 1
            continue
        index_url = source_item.get("url")
        if not isinstance(index_url, str) or not index_url:
            exclusions["recorded-index-url-missing"] += 1
            continue
        try:
            body = verify_raw(source_item)
        except (OSError, UnicodeError, ValueError):
            exclusions["source-raw-hash-verification-failed"] += 1
            continue
        signals = extract_engineering_signals(body)
        items.append({
            "taskId": "engineering-zero-catalog-browser-navigation:" + university_id,
            "universityId": university_id,
            "name": source_item.get("name"),
            "country": source_item.get("country") or entity.get("country") or "",
            "recordedIndexUrl": index_url,
            "engineeringVisibleTextSignals": signals,
            "prioritySteps": priority_steps(signals),
            "sourceQueueItem": copy.deepcopy(source_item),
            "coverageEntity": {
                "canonicalId": entity.get("canonicalId"),
                "name": entity.get("name"),
                "country": entity.get("country"),
                "rankingSources": copy.deepcopy(entity.get("rankingSources") or []),
                "category": entity.get("category"),
                "officialVerificationStatus": entity.get("officialVerificationStatus"),
                "officialReasonCodes": copy.deepcopy(entity.get("officialReasonCodes") or []),
            },
            "status": "pending",
            "captchaPolicy": {
                "detectBeforeEveryAction": True,
                "onDetection": "stop",
                "resultStatus": "blocked",
                "bypassAllowed": False,
                "manualSolveAllowed": False,
                "preserveRenderedEvidence": True,
            },
        })

    items.sort(key=lambda item: (
        -int(item["engineeringVisibleTextSignals"]["score"]),
        str(item.get("country") or "").casefold(),
        item["recordedIndexUrl"].casefold(),
        item["universityId"],
    ))
    for position, item in enumerate(items):
        item["priorityPosition"] = position

    level_counts = Counter(
        item["engineeringVisibleTextSignals"]["level"] for item in items
    )
    country_counts = Counter(item["country"] for item in items)
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at or utc_now(),
        "sourceQueueFile": source_queue_file,
        "sourceCoverageFile": source_coverage_file,
        "policy": {
            "networkAccessUsedByBuilder": False,
            "browserExecutionPerformedByBuilder": False,
            "sourceQueueItemPreserved": True,
            "coverageVerifiedZeroCandidatesRequired": True,
            "homepageRawHashVerificationRequired": True,
            "engineeringSignalsSource": "homepage-raw-visible-text-only",
            "sortFields": [
                "engineeringVisibleTextSignals.score:desc",
                "country:asc",
                "recordedIndexUrl:asc",
                "universityId:asc",
            ],
            "recordedIndexUrlOnly": True,
            "guessedUrlsAllowed": False,
            "searchEndpointConstructionAllowed": False,
            "visibleDomElementsOnly": True,
            "captchaAction": "stop",
            "captchaBypassAllowed": False,
        },
        "summary": {
            "sourceQueueRows": len(queue_payload["items"]),
            "eligibleTasks": len(items),
            "excludedRows": sum(exclusions.values()),
            "exclusionCounts": dict(sorted(exclusions.items())),
            "engineeringSignalLevelCounts": dict(sorted(level_counts.items())),
            "countryCounts": dict(sorted(country_counts.items())),
            "statusCounts": {"pending": len(items)},
        },
        "items": items,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-input", type=Path, default=QUEUE_INPUT)
    parser.add_argument("--coverage-input", type=Path, default=COVERAGE_INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    result = build_queue(
        load_json(args.queue_input),
        load_json(args.coverage_input),
        source_queue_file=str(args.queue_input.resolve()),
        source_coverage_file=str(args.coverage_input.resolve()),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
