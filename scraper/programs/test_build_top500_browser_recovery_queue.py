from scraper.programs.build_top500_browser_recovery_queue import build


def test():
    homepage = [{
        "universityId": "u_test", "name": "Test", "indexUrl": "https://example.edu/",
        "officialDomains": ["example.edu"], "provenance": {"officialHomepageRaw": {"rawFile": "home.body"}},
    }]
    coverage = {"universities": [{
        "universityId": "u_test", "name": "Test", "manifestFile": "manifest.json",
        "blockedUrls": [{"url": "https://example.edu/master", "kind": "program", "record": {"statusCode": 403}}],
    }]}
    output = build(homepage, coverage)
    assert output["summary"]["tasks"] == 2
    assert output["summary"]["kindCounts"] == {"official-homepage": 1, "program": 1}
    print("[browser-recovery-queue-test] passed")


if __name__ == "__main__":
    test()
