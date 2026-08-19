"""Capture the latest published ARWU ranking as an auditable raw batch.

Default-year basis
------------------
As of 2026-08-13, the latest edition published in ARWU's official ranking
archive is the 2025 edition.  The 2026 edition was not yet published on that
date.  The dated edition and archive are available at:

* https://www.shanghairanking.com/rankings/arwu/2025
* https://www.shanghairanking.com/rankings/arwu

This module deliberately does not write ``frontend/public/data``.  One fetch
creates an immutable-style raw batch under::

    scraper/raw/rankings/arwu/year=2025/
      captured-at=YYYYMMDDTHHMMSSffffffZ_sha256=<12 hex>/
        api-response.body
        manifest.json
        top500.normalized.json

``api-response.body`` contains the response bytes exactly as returned by the
shared fetcher, including transport compression when present.  The manifest
records the content encoding needed to interpret those bytes.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:  # Support both ``python -m scraper...`` and execution from scraper/.
    from ..utils import fetch, slug
except ImportError:  # pragma: no cover - exercised by the legacy entry point
    from utils import fetch, slug


SOURCE = "arwu"
DEFAULT_YEAR = 2025
DEFAULT_YEAR_AS_OF = "2026-08-13"
OFFICIAL_ARCHIVE_URL = "https://www.shanghairanking.com/rankings/arwu"
OFFICIAL_EDITION_URL = (
    "https://www.shanghairanking.com/rankings/arwu/{year}"
)
API = "https://www.shanghairanking.com/api/pub/v1/arwu/rank?version={year}"
RAW_ROOT = Path(__file__).resolve().parents[1] / "raw" / "rankings" / SOURCE
TOP_N = 500

_RANK_PATTERN = re.compile(
    r"^\s*=?\s*(?P<lower>\d+)"
    r"(?:\s*[-\u2012\u2013\u2014]\s*(?P<upper>\d+))?\s*$"
)


def parse_rank(value: Any) -> tuple[str, int, int]:
    """Return the source display value and inclusive numeric rank bounds."""
    display = str(value).strip()
    match = _RANK_PATTERN.match(display)
    if not match:
        raise ValueError(f"unsupported ARWU ranking value: {display!r}")
    lower = int(match.group("lower"))
    upper = int(match.group("upper") or lower)
    if lower < 1 or upper < lower:
        raise ValueError(f"invalid ARWU ranking interval: {display!r}")
    return display, lower, upper


def normalize_rows(payload: dict[str, Any], year: int, limit: int = TOP_N) -> list[dict[str, Any]]:
    """Normalize API rows while retaining the source's interval ranking."""
    rows = payload.get("data", {}).get("rankings", [])
    if not isinstance(rows, list):
        raise ValueError("ARWU response data.rankings must be a list")

    items: list[dict[str, Any]] = []
    for source_index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        name = str(row.get("univNameEn") or "").strip()
        if not name:
            continue
        try:
            rank_display, rank_lower, rank_upper = parse_rank(row.get("ranking", ""))
        except ValueError as error:
            print(f"  skip row {source_index}: {error}")
            continue

        score = row.get("score")
        try:
            score = float(score) if score not in (None, "") else None
        except (TypeError, ValueError):
            score = None

        items.append({
            # Compatibility field: consumers that only understand an integer
            # continue to receive the lower bound. New consumers must use the
            # explicit display/lower/upper fields.
            "rank": rank_lower,
            "rankDisplay": rank_display,
            "rankLower": rank_lower,
            "rankUpper": rank_upper,
            "universityId": slug(name),
            "name": name,
            "country": str(row.get("region") or ""),
            "score": score,
            "year": year,
            "sourceIndex": source_index,
        })

    items.sort(key=lambda item: (item["rankLower"], item["rankUpper"], item["sourceIndex"]))
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


def scrape(
    output_dir: Path | None = None,
    *,
    year: int = DEFAULT_YEAR,
    raw_root: Path = RAW_ROOT,
    fetcher: Callable[[str], Any] = fetch,
    clock: Callable[[], datetime] = _utc_now,
) -> Path:
    """Fetch and archive ARWU, returning the newly written batch directory.

    ``output_dir`` is accepted for compatibility with ``scraper/main.py`` but
    is intentionally ignored so this raw capture can never overwrite the
    frontend's formal ranking JSON.
    """
    del output_dir
    url = API.format(year=year)
    captured_at = clock()
    print(f"[ARWU] capture {url}")
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
    response_path = batch_dir / "api-response.body"
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
            "archiveUrl": OFFICIAL_ARCHIVE_URL,
            "editionUrl": OFFICIAL_EDITION_URL.format(year=year),
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
        "derived": {"status": "pending", "file": normalized_path.name},
    }
    _write_json(manifest_path, manifest)

    if not 200 <= status < 300:
        manifest["derived"] = {
            "status": "error",
            "file": normalized_path.name,
            "error": f"HTTP {status}",
        }
        _write_json(manifest_path, manifest)
        raise RuntimeError(f"ARWU API returned HTTP {status}; raw batch saved at {batch_dir}")

    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("ARWU response root must be an object")
        items = normalize_rows(payload, year)
        _write_json(normalized_path, items)
    except Exception as error:
        manifest["derived"] = {
            "status": "error",
            "file": normalized_path.name,
            "error": f"{type(error).__name__}: {error}",
        }
        _write_json(manifest_path, manifest)
        raise

    manifest["derived"] = {
        "status": "complete",
        "file": normalized_path.name,
        "recordCount": len(items),
    }
    _write_json(manifest_path, manifest)
    print(f"  raw batch -> {batch_dir} ({len(items)} records)")
    return batch_dir
