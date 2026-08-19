"""Capture THE World University Rankings as an auditable raw batch.

Default-year basis
------------------
As of 2026-08-13, THE's official ``/latest/world-ranking`` URL resolves to
the 2026 World University Rankings.  THE also publishes the dated edition at:

* https://www.timeshighereducation.com/world-university-rankings/2026/world-ranking
* https://www.timeshighereducation.com/world-university-rankings/latest/world-ranking

Edition URLs are kept in an explicit registry.  A caller cannot accidentally
request an unverified URL merely by supplying an arbitrary year.

This module never writes ``frontend/public/data``.  Each fetch creates a new
raw batch under::

    scraper/raw/rankings/the/year=2026/
      captured-at=YYYYMMDDTHHMMSSffffffZ_sha256=<12 hex>/
        page-response.body
        next-data.json
        manifest.json
        top500.normalized.json

``page-response.body`` contains the exact bytes exposed by the shared fetcher.
The manifest records transport metadata, hashes, and all derived artifacts.
"""
from __future__ import annotations

import hashlib
import html as html_module
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:  # Support both ``python -m scraper...`` and execution from scraper/.
    from ..utils import fetch, slug
except ImportError:  # pragma: no cover - legacy entry point
    from utils import fetch, slug


SOURCE = "the"
DEFAULT_YEAR = 2026
DEFAULT_YEAR_AS_OF = "2026-08-13"
LATEST_URL = "https://www.timeshighereducation.com/world-university-rankings/latest/world-ranking"
OFFICIAL_EDITION_URLS = {
    2025: "https://www.timeshighereducation.com/world-university-rankings/2025/world-ranking",
    2026: "https://www.timeshighereducation.com/world-university-rankings/2026/world-ranking",
}
RAW_ROOT = Path(__file__).resolve().parents[1] / "raw" / "rankings" / SOURCE
TOP_N = 500

_NEXT_DATA_PATTERN = re.compile(
    r"<script\b[^>]*\bid=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)
_RANK_PATTERN = re.compile(
    r"^\s*=?\s*(?P<lower>\d+)"
    r"(?:\s*[-\u2012\u2013\u2014]\s*(?P<upper>\d+)|\s*(?P<plus>\+))?\s*$"
)


def edition_url(year: int) -> str:
    """Return a verified official edition URL."""
    try:
        return OFFICIAL_EDITION_URLS[int(year)]
    except (KeyError, TypeError, ValueError) as error:
        supported = ", ".join(str(value) for value in sorted(OFFICIAL_EDITION_URLS))
        raise ValueError(f"unsupported THE WUR year {year!r}; verified years: {supported}") from error


def parse_rank(value: Any) -> tuple[str, int, int | None, str]:
    """Return display text, lower/upper bounds, and interval semantics."""
    display = str(value).strip()
    match = _RANK_PATTERN.match(display)
    if not match:
        raise ValueError(f"unsupported THE ranking value: {display!r}")
    lower = int(match.group("lower"))
    upper_text = match.group("upper")
    upper = int(upper_text) if upper_text else (None if match.group("plus") else lower)
    if lower < 1 or (upper is not None and upper < lower):
        raise ValueError(f"invalid THE ranking interval: {display!r}")
    rank_type = "openEnded" if upper is None else ("exact" if lower == upper else "range")
    return display, lower, upper, rank_type


def extract_next_data(html_text: str) -> dict[str, Any]:
    """Extract and parse the page's embedded Next.js payload."""
    match = _NEXT_DATA_PATTERN.search(html_text)
    if not match:
        raise ValueError("THE page does not contain __NEXT_DATA__")
    payload = json.loads(html_module.unescape(match.group(1)))
    if not isinstance(payload, dict):
        raise ValueError("THE __NEXT_DATA__ root must be an object")
    return payload


def _find_rankings_data(obj: Any) -> list[dict[str, Any]]:
    """Locate the official ``rankingsData.data`` array recursively."""
    if isinstance(obj, dict):
        rankings = obj.get("rankingsData")
        if isinstance(rankings, dict) and isinstance(rankings.get("data"), list):
            return rankings["data"]
        for value in obj.values():
            found = _find_rankings_data(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_rankings_data(value)
            if found:
                return found
    return []


def normalize_rows(payload: dict[str, Any], year: int, limit: int = TOP_N) -> list[dict[str, Any]]:
    """Normalize rows without collapsing source rank intervals."""
    rows = _find_rankings_data(payload)
    if not rows:
        raise ValueError("THE __NEXT_DATA__ does not contain rankingsData.data")

    items: list[dict[str, Any]] = []
    skipped_rank_values: dict[str, int] = {}
    for source_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("title") or "").strip()
        if not name:
            continue
        try:
            rank_display, rank_lower, rank_upper, rank_type = parse_rank(row.get("rank", ""))
        except ValueError as error:
            value = str(row.get("rank", "")).strip() or "<empty>"
            skipped_rank_values[value] = skipped_rank_values.get(value, 0) + 1
            continue

        score = row.get("scores_overall")
        if score in (None, ""):
            score = row.get("overall")
        try:
            score = float(score) if score not in (None, "") else None
        except (TypeError, ValueError):
            score = None

        rank_order = row.get("rank_order")
        try:
            rank_order = int(rank_order)
        except (TypeError, ValueError):
            rank_order = source_index + 1

        items.append({
            # Backward-compatible integer field. Its explicit semantics are
            # the inclusive lower bound, never an asserted exact placement.
            "rank": rank_lower,
            "rankSemantics": "lowerBound",
            "rankDisplay": rank_display,
            "rankLower": rank_lower,
            "rankUpper": rank_upper,
            "rankType": rank_type,
            "universityId": slug(name),
            "name": name,
            "country": str(row.get("location") or row.get("country") or ""),
            "score": score,
            "year": year,
            "sourceRankOrder": rank_order,
            "sourceIndex": source_index,
        })

    if skipped_rank_values:
        summary = ", ".join(
            f"{value!r}={count}" for value, count in
            sorted(skipped_rank_values.items(), key=lambda item: (-item[1], item[0]))
        )
        print(f"  skipped non-ranking rows: {summary}")
    items.sort(key=lambda item: (item["sourceRankOrder"], item["sourceIndex"]))
    return items[:limit]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _capture_stamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _response_bytes(response: Any) -> bytes:
    body = getattr(response, "_raw", None)
    if not isinstance(body, bytes):
        raise TypeError("fetcher response must expose exact response bytes as _raw")
    return body


def _headers(response: Any) -> dict[str, str]:
    headers = getattr(response, "headers", {}) or {}
    return {str(key): str(value) for key, value in sorted(headers.items())}


def _header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == wanted), None)


def _write_json(path: Path, data: Any) -> None:
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _decoded_text(response: Any, body: bytes) -> str:
    text = getattr(response, "text", None)
    return text if isinstance(text, str) else body.decode("utf-8", "replace")


def scrape(
    output_dir: Path | None = None,
    *,
    year: int = DEFAULT_YEAR,
    raw_root: Path = RAW_ROOT,
    fetcher: Callable[[str], Any] = fetch,
    clock: Callable[[], datetime] = _utc_now,
) -> Path:
    """Fetch and archive one THE edition, returning its new batch directory.

    ``output_dir`` remains accepted for compatibility with ``scraper/main.py``
    but is intentionally ignored.  Publishing normalized data is a separate,
    reviewed operation.
    """
    del output_dir
    year = int(year)
    url = edition_url(year)
    captured_at = clock()
    print(f"[THE] capture {url}")
    response = fetcher(url)
    body = _response_bytes(response)
    digest = hashlib.sha256(body).hexdigest()
    headers = _headers(response)
    status = int(getattr(response, "status_code", 0))

    batch_dir = (
        Path(raw_root)
        / f"year={year}"
        / f"captured-at={_capture_stamp(captured_at)}_sha256={digest[:12]}"
    )
    batch_dir.mkdir(parents=True, exist_ok=False)
    response_path = batch_dir / "page-response.body"
    next_data_path = batch_dir / "next-data.json"
    manifest_path = batch_dir / "manifest.json"
    normalized_path = batch_dir / "top500.normalized.json"
    response_path.write_bytes(body)

    manifest: dict[str, Any] = {
        "schemaVersion": 1,
        "source": SOURCE,
        "sourceYear": year,
        "defaultYear": DEFAULT_YEAR,
        "defaultYearAsOf": DEFAULT_YEAR_AS_OF,
        "officialBasis": {
            "latestUrl": LATEST_URL,
            "editionUrl": url,
            "verifiedEditionUrls": {str(key): value for key, value in OFFICIAL_EDITION_URLS.items()},
        },
        "request": {"method": "GET", "url": url},
        "response": {
            "capturedAt": _iso_utc(captured_at),
            "httpStatus": status,
            "headers": headers,
            "contentType": _header(headers, "Content-Type"),
            "contentEncoding": _header(headers, "Content-Encoding"),
            "byteLength": len(body),
            "sha256": digest,
            "file": response_path.name,
        },
        "derived": {"status": "pending"},
    }
    _write_json(manifest_path, manifest)

    if not 200 <= status < 300:
        manifest["derived"] = {"status": "error", "error": f"HTTP {status}"}
        _write_json(manifest_path, manifest)
        raise RuntimeError(f"THE page returned HTTP {status}; raw batch saved at {batch_dir}")

    try:
        payload = extract_next_data(_decoded_text(response, body))
        next_data_bytes = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        next_data_path.write_bytes(next_data_bytes)
        items = normalize_rows(payload, year)
        _write_json(normalized_path, items)
    except Exception as error:
        manifest["derived"] = {
            "status": "error",
            "error": f"{type(error).__name__}: {error}",
        }
        _write_json(manifest_path, manifest)
        raise

    manifest["derived"] = {
        "status": "complete",
        "nextData": {
            "file": next_data_path.name,
            "byteLength": len(next_data_bytes),
            "sha256": hashlib.sha256(next_data_bytes).hexdigest(),
        },
        "normalized": {
            "file": normalized_path.name,
            "recordCount": len(items),
            "rankCompatibilitySemantics": "rank is rankLower, not necessarily an exact rank",
        },
    }
    _write_json(manifest_path, manifest)
    print(f"  raw batch -> {batch_dir} ({len(items)} records)")
    return batch_dir
