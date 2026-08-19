"""Offline regression tests for the auditable THE WUR capture."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from . import the_rankings as the


FIXTURE_PAYLOAD = {
    "props": {
        "pageProps": {
            "ranking": {
                "rankingsData": {
                    "data": [
                        {
                            "rank": "1",
                            "rank_order": "1",
                            "name": "Alpha University",
                            "location": "United Kingdom",
                            "scores_overall": "98.7",
                        },
                        {
                            "rank": "201\u2013250",
                            "rank_order": "202",
                            "name": "Universit\u00e4t Beta",
                            "location": "Germany",
                            "scores_overall": "",
                        },
                        {
                            "rank": "1501+",
                            "rank_order": "1501",
                            "name": "Gamma Institute",
                            "location": "France",
                            "scores_overall": None,
                        },
                    ]
                }
            }
        }
    }
}
FIXTURE_HTML = (
    "<!doctype html><html><head></head><body>"
    '<script type="application/json" id="__NEXT_DATA__">'
    + json.dumps(FIXTURE_PAYLOAD, ensure_ascii=False, separators=(",", ":"))
    + "</script></body></html>"
)
FIXTURE_BYTES = FIXTURE_HTML.encode("utf-8")


class FixtureResponse:
    status_code = 200
    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Encoding": "identity",
        "X-Fixture": "offline",
    }

    def __init__(self, body: bytes):
        self._raw = body

    @property
    def text(self) -> str:
        return self._raw.decode("utf-8")


def test_verified_years_and_rank_intervals() -> None:
    assert the.DEFAULT_YEAR == 2026
    assert the.edition_url(2026).endswith("/2026/world-ranking")
    assert the.parse_rank("=7") == ("=7", 7, 7, "exact")
    assert the.parse_rank("201-250") == ("201-250", 201, 250, "range")
    assert the.parse_rank("201\u2013250") == ("201\u2013250", 201, 250, "range")
    assert the.parse_rank("1501+") == ("1501+", 1501, None, "openEnded")
    try:
        the.edition_url(2027)
    except ValueError as error:
        assert "verified years: 2025, 2026" in str(error)
    else:
        raise AssertionError("unverified editions must not use a guessed URL")


def test_extract_and_normalize_fixture() -> None:
    payload = the.extract_next_data(FIXTURE_HTML)
    records = the.normalize_rows(payload, 2026)
    assert len(records) == 3
    assert records[0]["rank"] == records[0]["rankLower"] == records[0]["rankUpper"] == 1
    assert records[0]["rankSemantics"] == "lowerBound"
    assert records[1]["rankDisplay"] == "201\u2013250"
    assert records[1]["rank"] == records[1]["rankLower"] == 201
    assert records[1]["rankUpper"] == 250
    assert records[1]["rankType"] == "range"
    assert records[2]["rankUpper"] is None
    assert records[2]["rankType"] == "openEnded"


def test_offline_capture() -> None:
    requested_urls: list[str] = []
    captured_at = datetime(2026, 8, 13, 6, 7, 8, 901234, tzinfo=timezone.utc)

    def fixture_fetcher(url: str) -> FixtureResponse:
        requested_urls.append(url)
        return FixtureResponse(FIXTURE_BYTES)

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        forbidden_frontend = root / "frontend" / "public" / "data"
        batch = the.scrape(
            forbidden_frontend,
            raw_root=root / "raw" / "rankings" / "the",
            fetcher=fixture_fetcher,
            clock=lambda: captured_at,
        )

        digest = hashlib.sha256(FIXTURE_BYTES).hexdigest()
        expected_url = the.OFFICIAL_EDITION_URLS[2026]
        assert requested_urls == [expected_url]
        assert batch == (
            root
            / "raw"
            / "rankings"
            / "the"
            / "year=2026"
            / f"captured-at=20260813T060708901234Z_sha256={digest[:12]}"
        )
        assert (batch / "page-response.body").read_bytes() == FIXTURE_BYTES
        assert not forbidden_frontend.exists()

        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["sourceYear"] == manifest["defaultYear"] == 2026
        assert manifest["defaultYearAsOf"] == "2026-08-13"
        assert manifest["officialBasis"]["latestUrl"] == the.LATEST_URL
        assert manifest["request"] == {"method": "GET", "url": expected_url}
        assert manifest["response"]["capturedAt"] == "2026-08-13T06:07:08.901234Z"
        assert manifest["response"]["httpStatus"] == 200
        assert manifest["response"]["sha256"] == digest
        assert manifest["response"]["byteLength"] == len(FIXTURE_BYTES)
        assert manifest["derived"]["status"] == "complete"
        assert manifest["derived"]["normalized"]["recordCount"] == 3
        next_data = (batch / "next-data.json").read_bytes()
        assert hashlib.sha256(next_data).hexdigest() == manifest["derived"]["nextData"]["sha256"]


def test_http_error_still_archives_response() -> None:
    class ErrorResponse(FixtureResponse):
        status_code = 503

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        try:
            the.scrape(
                raw_root=root,
                fetcher=lambda _url: ErrorResponse(b"maintenance"),
                clock=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
            )
        except RuntimeError as error:
            assert "HTTP 503" in str(error)
        else:
            raise AssertionError("HTTP failure should raise RuntimeError")

        batch = next((root / "year=2026").iterdir())
        assert (batch / "page-response.body").read_bytes() == b"maintenance"
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["derived"]["status"] == "error"
        assert not (batch / "next-data.json").exists()
        assert not (batch / "top500.normalized.json").exists()


def main() -> None:
    test_verified_years_and_rank_intervals()
    test_extract_and_normalize_fixture()
    test_offline_capture()
    test_http_error_still_archives_response()
    print("[the-rankings-test] passed")


if __name__ == "__main__":
    main()
