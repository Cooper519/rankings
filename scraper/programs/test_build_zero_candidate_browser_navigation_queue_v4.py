import hashlib
import json
import tempfile
from pathlib import Path

from scraper.programs.build_zero_candidate_browser_navigation_queue_v4 import (
    build_queue,
    deterministic_shard,
)


def make_target(
    root,
    university_id="u_valid",
    status="no-candidates",
    verification="verified",
    index_url="https://www.example.edu/",
    domains=None,
    body=b'<html><link href="/wp-content/site.css"></html>',
    corrupt_hash=False,
):
    directory = root / university_id
    directory.mkdir(parents=True, exist_ok=True)
    raw_file = directory / "homepage.body"
    raw_file.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    manifest_digest = "0" * 64 if corrupt_hash else digest
    manifest_file = directory / "homepage.manifest.json"
    manifest = {
        "schemaVersion": 1,
        "kind": "homepage",
        "requestedUrl": index_url,
        "finalUrl": index_url,
        "status": 200,
        "headers": {"Server": "cloudflare", "CF-Ray": "test"},
        "bytes": len(body),
        "sha256": manifest_digest,
        "capturedAt": "2026-08-14T00:00:00+00:00",
        "rawFile": str(raw_file.resolve()),
    }
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    return {
        "universityId": university_id,
        "name": "Valid University",
        "country": "Testland",
        "region": "Test Region",
        "officialDomains": ["example.edu"] if domains is None else domains,
        "indexUrl": index_url,
        "officialVerificationStatus": verification,
        "provenance": {
            "officialHomepageRaw": {
                "rawFile": str(raw_file.resolve()),
                "manifestFile": str(manifest_file.resolve()),
                "sha256": digest,
            }
        },
        "catalogDiscovery": {
            "status": status,
            "method": "existing-official-homepage-visible-anchors",
            "networkRequested": False,
            "candidates": [],
        },
    }


def test_queue_filters_and_workflow():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        valid = make_target(root)
        already_found = make_target(
            root, university_id="u_found", status="candidates-found"
        )
        unverified = make_target(
            root, university_id="u_unverified", verification="review"
        )
        wrong_domain = make_target(
            root,
            university_id="u_wrong_domain",
            index_url="https://outside.example.org/",
        )
        corrupt = make_target(root, university_id="u_corrupt", corrupt_hash=True)
        incomplete_domains = make_target(
            root, university_id="u_no_domains", domains=[]
        )

        queue = build_queue(
            [valid, already_found, unverified, wrong_domain, corrupt, incomplete_domains],
            shard_count=7,
            generated_at="2026-08-14T00:00:00+00:00",
        )

        assert queue["summary"]["eligibleTasks"] == 1
        assert queue["summary"]["excludedRows"] == 5
        assert queue["summary"]["exclusionCounts"] == {
            "homepage-raw-hash-verification-failed": 1,
            "not-no-candidates": 1,
            "not-verified": 1,
            "official-domains-incomplete": 1,
            "recorded-homepage-not-official": 1,
        }
        item = queue["items"][0]
        assert item["universityId"] == "u_valid"
        assert item["url"] == valid["indexUrl"]
        assert item["platform"] == "wordpress"
        assert item["edgePlatform"] == "cloudflare"
        assert item["shard"] == deterministic_shard(
            "example.edu", "wordpress", "Testland", 7
        )
        assert item["partitionKey"] == "example.edu|wordpress|Testland"
        assert item["captchaPolicy"] == {
            "detectBeforeEveryAction": True,
            "onDetection": "stop",
            "resultStatus": "blocked",
            "bypassAllowed": False,
            "manualSolveAllowed": False,
            "preserveRenderedEvidence": True,
        }
        assert item["workflow"]["steps"][2]["action"] == (
            "use-visible-site-search-if-present"
        )
        assert queue["policy"]["networkAccessUsedByBuilder"] is False
        assert queue["policy"]["guessedUrlsAllowed"] is False
        assert queue["policy"]["searchEndpointConstructionAllowed"] is False

        serialized = json.dumps(queue, ensure_ascii=True).casefold()
        assert "/search" not in serialized
        assert "search endpoint" in serialized


def test_queue_is_deterministic_and_grouped():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first = make_target(
            root,
            university_id="u_zed",
            index_url="https://z.example.edu/",
            domains=["example.edu"],
            body=b"<html>plain</html>",
        )
        second = make_target(
            root,
            university_id="u_alpha",
            index_url="https://a.example.edu/",
            domains=["example.edu"],
            body=b"<html>__NEXT_DATA__</html>",
        )
        generated_at = "2026-08-14T00:00:00+00:00"
        left = build_queue([first, second], 5, generated_at)
        right = build_queue([second, first], 5, generated_at)
        assert left == right
        assert [item["host"] for item in left["items"]] == [
            "a.example.edu",
            "z.example.edu",
        ]
        assert [item["queuePosition"] for item in left["items"]] == [0, 1]
        assert left["shardStrategy"]["groupingPriority"] == [
            "host",
            "platform",
            "country",
        ]


def test_invalid_shard_count():
    try:
        build_queue([], shard_count=0)
    except ValueError as error:
        assert "shard_count" in str(error)
    else:
        raise AssertionError("zero shard count must fail")


def test():
    test_queue_filters_and_workflow()
    test_queue_is_deterministic_and_grouped()
    test_invalid_shard_count()
    print("[zero-candidate-browser-navigation-queue-v4-test] passed")


if __name__ == "__main__":
    test()
