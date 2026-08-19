import hashlib
import json
import tempfile
from pathlib import Path

from scraper.programs.build_engineering_zero_candidate_browser_queue_v4 import (
    build_queue,
    extract_engineering_signals,
)


def make_item(root, university_id="u_valid", body=None, url=None):
    body = body or (
        b"<html><head><title>Engineering University</title></head>"
        b"<body><nav>Graduate programs</nav>"
        b"<h1>Faculty of Engineering</h1>"
        b"<script>School of Engineering should not count</script>"
        b"<a href='/engineering'>Mechanical Engineering</a></body></html>"
    )
    url = url or "https://www.example.edu/"
    directory = root / university_id
    directory.mkdir(parents=True, exist_ok=True)
    raw_file = directory / "homepage.body"
    raw_file.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    return {
        "taskId": "zero-catalog-browser-navigation:" + university_id,
        "universityId": university_id,
        "name": "Valid University",
        "country": "Testland",
        "url": url,
        "kind": "program-catalog-navigation",
        "status": "pending",
        "sourceRaw": {
            "rawFile": str(raw_file.resolve()),
            "manifestFile": str((directory / "homepage.manifest.json").resolve()),
            "sha256": digest,
            "bytes": len(body),
        },
    }


def make_coverage(university_id="u_valid", category="verified-zero-candidates"):
    return {
        "schemaVersion": 1,
        "entities": [{
            "canonicalId": university_id,
            "name": "Valid University",
            "country": "Testland",
            "rankingSources": ["qs", "the"],
            "category": category,
            "officialVerificationStatus": "verified",
            "officialReasonCodes": [],
        }],
    }


def write_manifest(item):
    source = item["sourceRaw"]
    manifest = {
        "kind": "homepage",
        "sha256": source["sha256"],
        "bytes": source["bytes"],
        "rawFile": source["rawFile"],
        "status": 200,
        "finalUrl": item["url"],
    }
    Path(source["manifestFile"]).write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def test_signal_extraction_ignores_non_visible_script():
    result = extract_engineering_signals(
        b"<body><h1>Electrical Engineering</h1>"
        b"<script>Mechanical Engineering</script></body>"
    )
    assert result["level"] == "strong"
    assert "electrical/electronic engineering" in result["matchedLabels"]
    assert "mechanical engineering" not in result["matchedLabels"]
    assert result["visibleTextBlockCount"] == 1

    title_only = extract_engineering_signals(
        b"<html><head><title>Engineering</title></head><body>Welcome</body></html>"
    )
    assert title_only["level"] == "none"


def test_queue_preserves_source_and_sorts_by_engineering_signal():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        strong = make_item(root, "u_strong", url="https://z.example.edu/")
        weak = make_item(
            root,
            "u_weak",
            body=b"<html><body><a href='/study'>Technology</a></body></html>",
            url="https://a.example.edu/",
        )
        write_manifest(strong)
        write_manifest(weak)
        queue = {
            "schemaVersion": 1,
            "items": [strong, weak],
            "policy": {"guessedUrlsAllowed": False},
        }
        result = build_queue(
            queue,
            {
                "entities": [
                    make_coverage("u_strong")["entities"][0],
                    make_coverage("u_weak")["entities"][0],
                ]
            },
            generated_at="2026-08-14T00:00:00+00:00",
        )
        assert result["summary"]["eligibleTasks"] == 2
        assert result["items"][0]["universityId"] == "u_strong"
        assert result["items"][0]["sourceQueueItem"] == strong
        assert result["items"][0]["recordedIndexUrl"] == "https://z.example.edu/"
        assert result["items"][0]["prioritySteps"][0]["action"] == (
            "inspect-visible-navigation-for-engineering-catalog"
        )
        assert result["items"][0]["captchaPolicy"]["onDetection"] == "stop"
        assert result["policy"]["networkAccessUsedByBuilder"] is False
        assert result["policy"]["recordedIndexUrlOnly"] is True


def test_queue_requires_coverage_and_raw_integrity():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        valid = make_item(root)
        write_manifest(valid)
        invalid_coverage = make_coverage(
            "u_valid", category="new-program-raw"
        )["entities"][0]
        missing = make_item(root, "u_missing")
        write_manifest(missing)
        result = build_queue(
            {"items": [valid, missing]},
            {"entities": [invalid_coverage]},
            generated_at="2026-08-14T00:00:00+00:00",
        )
        assert result["summary"]["eligibleTasks"] == 0
        assert result["summary"]["exclusionCounts"] == {
            "coverage-entity-missing": 1,
            "coverage-not-verified-zero-candidates": 1,
        }


def test():
    test_signal_extraction_ignores_non_visible_script()
    test_queue_preserves_source_and_sorts_by_engineering_signal()
    test_queue_requires_coverage_and_raw_integrity()
    print("[engineering-zero-candidate-browser-queue-v4-test] passed")


if __name__ == "__main__":
    test()
