"""Discover master's catalogue entry points from existing official homepage raw.

This is an offline, raw-first discovery pass.  It never requests a URL and it
never invents a path: every emitted candidate must come from a literal href on
an already captured official HTML page.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[2]
PW = ROOT / "scraper" / "playwright"
DEFAULT_COVERAGE = PW / "top500_goal_entity_coverage_v3.json"
DEFAULT_TARGETS = PW / "top500_all_verified_static_crawl_targets_v3.json"
DEFAULT_RAW_ROOT = PW / "_top500_programs_raw"
DEFAULT_OUTPUT = PW / "top500_verified_zero_catalog_discovery_batch_v3.json"

TARGET_CATEGORY = "verified-zero-candidates"
MINIMUM_SCORE = 6
MAX_NAVIGATION_LABEL_LENGTH = 240
TRACKING_QUERY = re.compile(r"^(?:utm_.+|fbclid|gclid|mc_cid|mc_eid|ref|source)=", re.I)
ASSET_PATH = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z|jpe?g|png|gif|svg|webp|ico|"
    r"mp[34]|avi|mov|css|js|xml)(?:$|[?#])",
    re.I,
)

# Matching is performed on NFKD, accent-folded text.  Keep phrases explicit so
# each score remains inspectable in the emitted evidence.
SIGNALS = (
    ("master-level", 6, re.compile(
        r"\b(?:master(?:s| degree| programme| program| course| study| studies)?|"
        r"msc|m sc|m a|meng|m eng|llm|magister|maestria|maestrias|mestrado|"
        r"mestrados|masterstudium|masterstudiengang|masterstudiengange|"
        r"masterprogramme|masterprogram|masterprogrammer|masterutbildningar|"
        r"masteropleiding|masteropleidingen|maisteriohjelma|maisteriohjelmat|"
        r"studia magisterskie|yuksek lisans)\b|\u7855\u58eb|\u7814\u7a76\u751f",
        re.I,
    )),
    ("postgraduate-level", 5, re.compile(
        r"\b(?:postgraduate|post graduate|postgrado|postgrados|posgrado|posgrados|"
        r"pos graduacao|laurea magistrale|lauree magistrali|second cycle|"
        r"deuxieme cycle|cycle master|lisansustu)\b",
        re.I,
    )),
    ("graduate-level", 3, re.compile(r"\bgraduate(?: studies| study| education)?\b", re.I)),
    ("catalogue", 3, re.compile(
        r"\b(?:catalog|catalogue|all programmes|all programs|programme finder|"
        r"program finder|degree finder|course finder|find a programme|"
        r"find a program|explore programmes|explore programs|study options|"
        r"studienangebot|oferta academica|oferta formativa|"
        r"catalogue des formations)\b",
        re.I,
    )),
    ("programme-list", 3, re.compile(
        r"\b(?:programmes|programs|degrees|courses|formations|studiengange|"
        r"studiengaenge|study programmes|study programs|corsi di laurea|"
        r"programas|cursos|opleidingen)\b",
        re.I,
    )),
    ("study-area", 1, re.compile(r"\b(?:study|studies|education|academic)\b", re.I)),
)

NEGATIVE_SIGNALS = (
    ("event-or-news", -12, re.compile(
        r"\b(?:news|events?|webinars?|open days?|open house|information session|"
        r"press|stories|blog)\b",
        re.I,
    )),
    ("non-degree-content", -10, re.compile(
        r"\b(?:research projects?|publications?|staff|people|alumni|jobs?|"
        r"vacancies|library|contact|about us|privacy|cookies?|login|sign in|"
        r"current students?|student information|information (?:for )?.* students|"
        r"academic calendars?|calendario academico|cronograma|schedules?)\b",
        re.I,
    )),
    ("admissions-only", -6, re.compile(
        r"\b(?:admissions?|application|apply|entry requirements?|eligibility|"
        r"deadlines?|tuition|fees|scholarships?|how to apply)\b",
        re.I,
    )),
    ("wrong-level", -8, re.compile(
        r"\b(?:bachelor|undergraduate|doctoral|doctorate|phd|continuing education|"
        r"doctorado|doctorados|especialidad|especialidades|especializacion|"
        r"postitulo|postitulos|pre master|foundation|executive education|"
        r"short courses?|summer schools?)\b",
        re.I,
    )),
)

REJECT_PATH = re.compile(
    r"/(?:news|events?|webinars?|research|publications?|people|staff|jobs?|"
    r"vacanc(?:y|ies)|press|blog|privacy|cookies?|login|contact|about|alumni|"
    r"admissions?|apply|application|how-to-apply|requirements?|fees?|scholarships?|"
    r"calendars?|calendario[^/]*|schedules?)(?:/|$)",
    re.I,
)
GENERIC_DIRECTORY_SEGMENT = re.compile(
    r"^(?:masters?|graduate|postgraduate|programmes?|programs?|degrees?|courses?|"
    r"catalog(?:ue)?|study|studies|education|formations?|maestrias?|mestrados?|"
    r"posgrados?|postgrados?|masterstudiengange|masterstudiengaenge|"
    r"masteropleidingen|lauree magistrali|oferta academica|oferta formativa)$",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%d" % os.getpid())
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"\s+", " ", value.replace("\u2019", "'").replace("-", " ")).strip().casefold()


def normalized_host(value: str) -> str:
    try:
        host = (urlsplit(value).hostname or value).casefold().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def is_official_url(url: str, official_domains: Iterable[str]) -> bool:
    host = normalized_host(url)
    for value in official_domains:
        domain = normalized_host(str(value))
        if domain and (host == domain or host.endswith("." + domain)):
            return True
    return False


def normalize_anchor_url(href: str, source_url: str) -> str:
    try:
        joined = urljoin(source_url, href.strip())
        parts = urlsplit(joined)
    except (AttributeError, TypeError, ValueError):
        return ""
    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return ""
    if ASSET_PATH.search(parts.path):
        return ""
    query_parts = [part for part in parts.query.split("&") if part and not TRACKING_QUERY.match(part)]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), path, "&".join(query_parts), ""))


class VisibleAnchorParser(HTMLParser):
    """Collect labelled anchors while ignoring explicitly hidden DOM branches."""

    VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self.anchors: List[Dict[str, str]] = []
        self._hidden_stack: List[Tuple[str, bool]] = []
        self._hidden_depth = 0
        self._anchor: Optional[Dict[str, Any]] = None

    @staticmethod
    def _is_hidden(attributes: Dict[str, str]) -> bool:
        style = (attributes.get("style") or "").replace(" ", "").casefold()
        return (
            "hidden" in attributes
            or (attributes.get("aria-hidden") or "").casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        )

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value or "" for key, value in attrs}
        hidden = self._is_hidden(attributes)
        if tag not in self.VOID_ELEMENTS:
            self._hidden_stack.append((tag, hidden))
            if hidden:
                self._hidden_depth += 1
        if tag == "a" and self._hidden_depth == 0 and attributes.get("href"):
            self._anchor = {
                "href": attributes["href"],
                "title": attributes.get("title", ""),
                "ariaLabel": attributes.get("aria-label", ""),
                "textParts": [],
            }

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._anchor is not None and self._hidden_depth == 0:
            self._anchor["textParts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a" and self._anchor is not None:
            text = re.sub(r"\s+", " ", " ".join(self._anchor.pop("textParts"))).strip()
            label = " ".join(value for value in (
                text, self._anchor.get("title", ""), self._anchor.get("ariaLabel", ""),
            ) if value).strip()
            if label:
                self._anchor["text"] = text
                self.anchors.append(self._anchor)
            self._anchor = None
        matching_index = next(
            (index for index in range(len(self._hidden_stack) - 1, -1, -1)
             if self._hidden_stack[index][0] == tag),
            None,
        )
        if matching_index is not None:
            closing = self._hidden_stack[matching_index:]
            del self._hidden_stack[matching_index:]
            self._hidden_depth -= sum(1 for _tag, hidden in closing if hidden)


def directory_path_signal(url: str) -> bool:
    try:
        segments = [fold(unquote(part)) for part in urlsplit(url).path.split("/") if part]
    except ValueError:
        return False
    return bool(segments and GENERIC_DIRECTORY_SEGMENT.match(segments[-1]))


def score_catalog_link(url: str, anchor: Dict[str, str]) -> Dict[str, Any]:
    label = " ".join(value for value in (
        anchor.get("text", ""), anchor.get("title", ""), anchor.get("ariaLabel", ""),
    ) if value)
    try:
        path_text = unquote(urlsplit(url).path)
    except ValueError:
        path_text = ""
    label_text = fold(label)
    evidence_text = fold(label + " " + path_text)
    signals = []
    negatives = []
    score = 0
    level_signal = False
    directory_signal = False
    for name, points, pattern in SIGNALS:
        match = pattern.search(evidence_text)
        if not match:
            continue
        entry = {"signal": name, "score": points, "match": match.group(0)}
        signals.append(entry)
        score += points
        if name in {"master-level", "postgraduate-level", "graduate-level"}:
            level_signal = True
        # A plural/category word buried in a detail URL (for example
        # /programs/data-science) does not make that detail page a directory.
        if name in {"catalogue", "programme-list"} and pattern.search(label_text):
            directory_signal = True
    path_directory = directory_path_signal(url)
    if path_directory:
        signals.append({"signal": "generic-directory-path", "score": 2, "match": urlsplit(url).path})
        score += 2
        directory_signal = True
    for name, points, pattern in NEGATIVE_SIGNALS:
        match = pattern.search(evidence_text)
        if match:
            negatives.append({"signal": name, "score": points, "match": match.group(0)})
            score += points
    hard_reject = bool(REJECT_PATH.search(urlsplit(url).path))
    label_too_long = len(label) > MAX_NAVIGATION_LABEL_LENGTH
    accepted = (
        level_signal and directory_signal and score >= MINIMUM_SCORE
        and not hard_reject and not label_too_long
    )
    return {
        "accepted": accepted,
        "score": score,
        "matchedSignals": signals,
        "negativeSignals": negatives,
        "reason": (
            "accepted" if accepted else
            "anchor-label-too-long" if label_too_long else
            "rejected-path" if hard_reject else
            "missing-degree-level-signal" if not level_signal else
            "missing-directory-signal" if not directory_signal else
            "below-score-threshold"
        ),
    }


def decode_html(data: bytes, content_type: str) -> str:
    match = re.search(r"charset\s*=\s*['\"]?([^;'\"\s]+)", content_type or "", re.I)
    encodings = [match.group(1)] if match else []
    encodings.extend(["utf-8", "cp1252", "latin-1"])
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    return data.decode("utf-8", errors="replace")


def read_raw(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.casefold() == ".gz" or data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


def _content_type(raw: Dict[str, Any]) -> str:
    if raw.get("contentType"):
        return str(raw["contentType"])
    headers = raw.get("headers") or {}
    for key, value in headers.items():
        if str(key).casefold() == "content-type":
            return str(value)
    return "text/html"


def homepage_sources(entity: Dict[str, Any], target: Dict[str, Any], raw_root: Path) -> List[Dict[str, Any]]:
    sources = []
    official_raw = (target.get("provenance") or {}).get("officialHomepageRaw") or {}
    if official_raw.get("rawFile"):
        sources.append({
            "pageUrl": official_raw.get("finalUrl") or official_raw.get("requestedUrl") or target.get("indexUrl"),
            "rawFile": official_raw.get("rawFile"),
            "rawManifestFile": official_raw.get("manifestFile"),
            "sha256": official_raw.get("sha256"),
            "contentType": _content_type(official_raw),
            "captureMethod": "official-verification-homepage-raw",
        })

    manifest_value = ((entity.get("newRaw") or {}).get("manifestFile") or
                      str(raw_root / str(target.get("universityId")) / "manifest.json"))
    manifest_path = Path(manifest_value)
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        index_url = str(target.get("indexUrl") or "")
        for visited_url, record in ((manifest.get("discovery") or {}).get("visited") or {}).items():
            if record.get("status") != "captured" or record.get("protocolProbe"):
                continue
            if "html" not in str(record.get("contentType") or "").casefold():
                continue
            if record.get("depth") != 0 and visited_url.rstrip("/") != index_url.rstrip("/"):
                continue
            if not record.get("file"):
                continue
            sources.append({
                "pageUrl": record.get("responseUrl") or visited_url,
                "rawFile": str(manifest_path.parent / str(record["file"])),
                "rawManifestFile": str(manifest_path),
                "sha256": record.get("sha256"),
                "contentType": record.get("contentType") or "text/html",
                "captureMethod": record.get("captureMethod") or "static-http",
            })

    unique = []
    seen = set()
    for source in sources:
        key = (str(Path(str(source.get("rawFile"))).resolve()), source.get("sha256"))
        if key not in seen:
            seen.add(key)
            unique.append(source)
    return unique


def discover_source(source: Dict[str, Any], official_domains: List[str]) -> Dict[str, Any]:
    evidence = dict(source)
    evidence["status"] = "unread"
    evidence["anchorsInspected"] = 0
    evidence["acceptedCandidates"] = 0
    page_url = str(source.get("pageUrl") or "")
    raw_file = Path(str(source.get("rawFile") or ""))
    if not is_official_url(page_url, official_domains):
        evidence["status"] = "rejected-non-official-source-page"
        return {"source": evidence, "candidates": []}
    if not raw_file.is_file():
        evidence["status"] = "missing-raw"
        return {"source": evidence, "candidates": []}
    data = read_raw(raw_file)
    digest = hashlib.sha256(data).hexdigest()
    evidence["computedSha256"] = digest
    if source.get("sha256") and digest.casefold() != str(source["sha256"]).casefold():
        evidence["status"] = "sha256-mismatch"
        return {"source": evidence, "candidates": []}
    parser = VisibleAnchorParser()
    parser.feed(decode_html(data, str(source.get("contentType") or "")))
    candidates = []
    evidence["anchorsInspected"] = len(parser.anchors)
    for anchor in parser.anchors:
        url = normalize_anchor_url(anchor["href"], page_url)
        if not url or not is_official_url(url, official_domains):
            continue
        scoring = score_catalog_link(url, anchor)
        if not scoring["accepted"]:
            continue
        candidates.append({
            "url": url,
            "href": anchor["href"],
            "anchorText": anchor.get("text", ""),
            "title": anchor.get("title", ""),
            "ariaLabel": anchor.get("ariaLabel", ""),
            "score": scoring["score"],
            "matchedSignals": scoring["matchedSignals"],
            "negativeSignals": scoring["negativeSignals"],
            "sourcePageUrl": page_url,
            "sourceRawFile": str(raw_file.resolve()),
            "sourceRawManifestFile": source.get("rawManifestFile"),
            "sourceRawSha256": digest,
        })
    evidence["status"] = "inspected"
    evidence["acceptedCandidates"] = len(candidates)
    return {"source": evidence, "candidates": candidates}


def payload_items(payload: Any, key: str) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    raise ValueError("JSON payload must be an array or contain %s/items" % key)


def build_discovery_batch(
    coverage_payload: Any,
    targets_payload: Any,
    raw_root: Path,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    entities = [
        item for item in payload_items(coverage_payload, "entities")
        if item.get("category") == TARGET_CATEGORY
    ]
    targets = payload_items(targets_payload, "targets")
    target_by_id = {str(item.get("universityId") or ""): item for item in targets}
    missing = [item["canonicalId"] for item in entities if item.get("canonicalId") not in target_by_id]
    if missing:
        raise ValueError("coverage entities missing verified targets: %s" % ", ".join(missing))

    batch = []
    discovered_targets = 0
    total_candidates = 0
    source_statuses: Dict[str, int] = {}
    for entity in entities:
        identifier = str(entity["canonicalId"])
        target = dict(target_by_id[identifier])
        if target.get("officialVerificationStatus") != "verified":
            raise ValueError("zero-candidate target is not verified: %s" % identifier)
        official_domains = [str(value) for value in target.get("officialDomains") or [] if value]
        if not official_domains:
            raise ValueError("verified target has no official domain: %s" % identifier)

        source_results = [
            discover_source(source, official_domains)
            for source in homepage_sources(entity, target, raw_root)
        ]
        candidates_by_url: Dict[str, Dict[str, Any]] = {}
        for result in source_results:
            status = result["source"]["status"]
            source_statuses[status] = source_statuses.get(status, 0) + 1
            for candidate in result["candidates"]:
                current = candidates_by_url.get(candidate["url"])
                if current is None or candidate["score"] > current["score"]:
                    candidates_by_url[candidate["url"]] = candidate
        candidates = sorted(candidates_by_url.values(), key=lambda item: (-item["score"], item["url"]))
        existing_pages = [str(value) for value in target.get("catalogPages") or []]
        target["catalogPages"] = list(dict.fromkeys(existing_pages + [item["url"] for item in candidates]))
        target["catalogDiscovery"] = {
            "schemaVersion": 1,
            "method": "existing-official-homepage-visible-anchors",
            "networkRequested": False,
            "guessedUrlsAllowed": False,
            "officialSubdomainsAllowed": True,
            "officialParentDomainsAllowed": False,
            "minimumScore": MINIMUM_SCORE,
            "status": "candidates-found" if candidates else "no-candidates",
            "sources": [result["source"] for result in source_results],
            "candidates": candidates,
        }
        if candidates:
            discovered_targets += 1
            total_candidates += len(candidates)
        batch.append(target)

    summary = {
        "generatedAt": utc_now(),
        "coverageCategory": TARGET_CATEGORY,
        "selectedTargets": len(batch),
        "targetsWithCandidates": discovered_targets,
        "targetsWithoutCandidates": len(batch) - discovered_targets,
        "catalogCandidates": total_candidates,
        "sourceStatuses": source_statuses,
    }
    return batch, summary


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    batch, summary = build_discovery_batch(
        load_json(args.coverage), load_json(args.targets), args.raw_root,
    )
    write_json_atomic(args.output, batch)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
