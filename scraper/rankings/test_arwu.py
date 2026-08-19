"""Offline regression tests for the auditable ARWU capture."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from . import arwu


FIXTURE = {
    "code": 0,
    "msg": "success",
    "data": {
        "rankings": [
            {
                "ranking": "1",
                "univNameEn": "Alpha University",
                "region": "United States",
                "score": "100.0",
            },
            {
                "ranking": "101-150",
                "univNameEn": "Beta University",
                "region": "France",
                "score": "",
            },
            {
                "ranking": "201\u2013300",
                "univNameEn": "Universit\u00e4t Gamma",
                "region": "Germany",
                "score": None,
            },
        ]
    },
}
FIXTURE_BYTES = json.dumps(FIXTURE, ensure_ascii=False, indent=1).encode("utf-8")


class FixtureResponse:
    status_code = 200
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Encoding": "identity",
        "X-Fixture": "offline",
    }

    def __init__(self, body: bytes):
        self._raw = body

    def json(self):
        return json.loads(self._raw.decode("utf-8"))


def test_rank_intervals() -> None:
    assert arwu.parse_rank("=7") == ("=7", 7, 7)
    assert arwu.parse_rank("101-150") == ("101-150", 101, 150)
    assert arwu.parse_rank("201\u2013300") == ("201\u2013300", 201, 300)


def test_offline_capture() -> None:
    requested_urls: list[str] = []
    captured_at = datetime(2026, 8, 13, 6, 7, 8, 901234, tzinfo=timezone.utc)

    def fixture_fetcher(url: str) -> FixtureResponse:
        requested_urls.append(url)
        return FixtureResponse(FIXTURE_BYTES)

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        forbidden_frontend = root / "frontend" / "public" / "data"
        batch = arwu.scrape(
            forbidden_frontend,
            raw_root=root / "raw" / "rankings" / "arwu",
            fetcher=fixture_fetcher,
            clock=lambda: captured_at,
        )

        digest = hashlib.sha256(FIXTURE_BYTES).hexdigest()
        expected_url = arwu.API.format(year=2025)
        assert requested_urls == [expected_url]
        assert batch == (
            root
            / "raw"
            / "rankings"
            / "arwu"
            / "year=2025"
            / f"captured-at=20260813T060708901234Z_sha256={digest[:12]}"
        )
        assert (batch / "api-response.body").read_bytes() == FIXTURE_BYTES
        assert not forbidden_frontend.exists()

        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["sourceYear"] == arwu.DEFAULT_YEAR == 2025
        assert manifest["defaultYearAsOf"] == "2026-08-13"
        assert manifest["officialBasis"]["editionUrl"].endswith("/arwu/2025")
        assert manifest["request"] == {"method": "GET", "url": expected_url}
        assert manifest["response"]["capturedAt"] == "2026-08-13T06:07:08.901234Z"
        assert manifest["response"]["httpStatus"] == 200
        assert manifest["response"]["sha256"] == digest
        assert manifest["response"]["byteLength"] == len(FIXTURE_BYTES)
        assert manifest["response"]["contentEncoding"] == "identity"
        assert manifest["derived"]["status"] == "complete"
        assert manifest["derived"]["recordCount"] == 3

        records = json.loads((batch / "top500.normalized.json").read_text(encoding="utf-8"))
        assert records[0]["rank"] == records[0]["rankLower"] == records[0]["rankUpper"] == 1
        assert records[1]["rankDisplay"] == "101-150"
        assert records[1]["rank"] == records[1]["rankLower"] == 101
        assert records[1]["rankUpper"] == 150
        assert records[2]["rankDisplay"] == "201\u2013300"
        assert records[2]["rank"] == records[2]["rankLower"] == 201
        assert records[2]["rankUpper"] == 300


def test_http_error_still_archives_response() -> None:
    class ErrorResponse(FixtureResponse):
        status_code = 503

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        try:
            arwu.scrape(
                raw_root=root,
                fetcher=lambda _url: ErrorResponse(b'{"error":"maintenance"}'),
                clock=lambda: datetime(2026, 8, 13, tzinfo=timezone.utc),
            )
        except RuntimeError as error:
            assert "HTTP 503" in str(error)
        else:
            raise AssertionError("HTTP failure should raise RuntimeError")

        batch = next((root / "year=2025").iterdir())
        assert (batch / "api-response.body").read_bytes() == b'{"error":"maintenance"}'
        manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["response"]["httpStatus"] == 503
        assert manifest["derived"]["status"] == "error"
        assert not (batch / "top500.normalized.json").exists()


def main() -> None:
    test_rank_intervals()
    test_offline_capture()
    test_http_error_still_archives_response()
    print("[arwu-test] passed")


if __name__ == "__main__":
    main()
