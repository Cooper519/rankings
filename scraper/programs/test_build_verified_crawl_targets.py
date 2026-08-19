from scraper.programs.build_verified_crawl_targets import build


def row(identifier, status, *, url="https://example.edu/", domains=None, reasons=None):
    return {
        "canonicalId": identifier,
        "name": identifier,
        "country": "Testland",
        "verificationStatus": status,
        "registryResolution": {"rawFile": "ror.json.gz", "rawManifestFile": "ror.manifest.json", "rawSha256": "abc"},
        "verification": {
            "reasonCodes": reasons or [],
            "evidence": {
                "registryIdentity": {"rorId": "https://ror.org/test"},
                "domainConsistency": {"candidateUrl": url, "rorDomains": domains or ["example.edu"]},
                "liveOfficialPage": {"finalUrl": url, "raw": {"rawFile": "home.body"}},
            },
        },
    }


def test():
    output = build({"items": [
        row("verified", "verified"),
        row("blocked", "blocked", reasons=["waf_or_access_block"]),
        row("review", "review", url="", domains=[], reasons=["ror_match_missing"]),
        row("rejected", "rejected", reasons=["ror_name_not_matched"]),
    ]})
    assert len(output["static"]) == 1
    assert len(output["browser"]) == 1
    assert len(output["review"]) == 2
    assert output["static"][0]["provenance"]["rorRawManifestFile"] == "ror.manifest.json"
    try:
        build({"items": [row("bad", "verified", url="https://attacker.test/", domains=["example.edu"])]})
    except ValueError as error:
        assert "domain-consistent" in str(error)
    else:
        raise AssertionError("verified cross-domain URL must fail")
    print("[build-verified-crawl-targets-test] passed")


if __name__ == "__main__":
    test()
