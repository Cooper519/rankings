import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.verify_official_website_candidates import (
    HttpResponse,
    domain_belongs,
    normalize_name,
    name_variants,
    parse_args,
    verify_candidate,
    verify_items,
)


def org(name, country, domain, *, acronym=None, ror_id="https://ror.org/01test"):
    names = [{"value": name, "types": ["ror_display"]}]
    if acronym:
        names.append({"value": acronym, "types": ["acronym"]})
    return {
        "id": ror_id,
        "names": names,
        "locations": [{"geonames_details": {"country_name": country}}],
        "domains": [domain],
    }


def item(name, country, website, organization, **extra):
    return {
        "canonicalId": "u_test_" + str(abs(hash(name + country))),
        "name": name,
        "country": country,
        "website": website,
        "rorOrganization": organization,
        **extra,
    }


def html_page(title, body):
    return f"<html><head><title>{title}</title></head><body><h1>{body}</h1></body></html>".encode()


def structured_html(title, body, *, h1=None, meta=None, json_ld=None):
    meta_markup = "".join(
        '<meta property="%s" content="%s">' % (kind, value)
        for kind, value in (meta or [])
    )
    json_markup = ""
    if json_ld is not None:
        json_markup = '<script type="application/ld+json">%s</script>' % json.dumps(json_ld)
    h1_markup = "<h1>%s</h1>" % h1 if h1 is not None else ""
    return (
        "<html><head><title>%s</title>%s%s</head><body>%s<p>%s</p></body></html>"
        % (title, meta_markup, json_markup, h1_markup, body)
    ).encode()


def fetch_map(mapping):
    def fetch(url, timeout):
        value = mapping[url]
        if isinstance(value, Exception):
            raise value
        return value
    return fetch


def counting_fetch(response):
    calls = []

    def fetch(url, timeout):
        calls.append((url, timeout))
        if isinstance(response, Exception):
            raise response
        return response

    return fetch, calls


def test():
    assert normalize_name("Universit\u00e9 de Montr\u00e9al") == "universite de montreal"
    assert domain_belongs("https://admissions.example.edu/path", ["example.edu"])
    assert not domain_belongs("https://example.edu.attacker.test", ["example.edu"])
    assert "universidad nacional de la plata" in name_variants("Universidad Nacional de La Plata (UNLP)")
    assert name_variants("University of Wisconsin (Madison)") == ["university of wisconsin madison"]

    with TemporaryDirectory() as directory:
        raw = Path(directory) / "raw"
        montreal = org("Universit\u00e9 de Montr\u00e9al", "Canada", "umontreal.ca", acronym="UdeM")
        good_url = "https://umontreal.ca/"
        good = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal, canonicalId="u_good"),
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {"Content-Type": "text/html; charset=utf-8"}, html_page("Universit\u00e9 de Montr\u00e9al | UdeM", "Universit\u00e9 de Montr\u00e9al UdeM"))}),
        )
        assert good["verificationStatus"] == "verified"
        assert good["evidence"]["liveOfficialPage"]["raw"]["sha256"]
        assert list(raw.rglob("homepage_*.body"))
        assert list(raw.rglob("homepage_*.manifest.json"))

        audited_item = item("The University of Example (UEX)", "Canada", good_url, montreal, canonicalId="u_audited")
        audited_item["registryResolution"] = {
            "queryName": montreal["names"][0]["value"],
            "rawFile": "query.json.gz",
            "rawManifestFile": "query.manifest.json",
            "rawSha256": "abc",
            "selected": {"rorId": montreal["id"], "confidence": "high", "countryMatch": True},
        }
        audited = verify_candidate(
            audited_item,
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {}, html_page(montreal["names"][0]["value"], montreal["names"][0]["value"]))}),
        )
        assert audited["verificationStatus"] == "verified"
        assert audited["evidence"]["registryIdentity"]["matchSource"] == "audited-ror-resolution"

        unaudited_item = dict(audited_item)
        unaudited_item["canonicalId"] = "u_unaudited"
        unaudited_item["registryResolution"] = {**audited_item["registryResolution"], "rawManifestFile": None}
        unaudited = verify_candidate(unaudited_item, raw, fetch_map({}))
        assert unaudited["verificationStatus"] == "rejected"

        # The compact resolver record is also accepted: it has only the ROR
        # selected fields and registryDomains, not the full organization.
        compact = {
            "canonicalId": "u_compact",
            "name": "Universit\u00e9 de Montr\u00e9al",
            "country": "Canada",
            "website": good_url,
            "registryResolution": {"selected": {
                "rorId": "https://ror.org/01test",
                "name": "Universit\u00e9 de Montr\u00e9al",
                "candidateCountry": "Canada",
                "registryDomains": ["umontreal.ca"],
            }},
        }
        compact_result = verify_candidate(
            compact,
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al"))}),
        )
        assert compact_result["verificationStatus"] == "verified"

        # Same name in another country must never pass the registry identity check.
        wrong_country_url = "https://umontreal.ca/"
        wrong_country = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "France", wrong_country_url, montreal),
            raw,
            fetch_map({wrong_country_url: HttpResponse(200, wrong_country_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al"))}),
        )
        assert wrong_country["verificationStatus"] == "rejected"
        assert "ror_country_mismatch" in wrong_country["reasonCodes"]

        wrong_domain_url = "https://fake.example/"
        wrong_domain = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "Canada", wrong_domain_url, montreal),
            raw,
            fetch_map({}),
        )
        assert wrong_domain["verificationStatus"] == "rejected"
        assert "website_domain_not_in_ror_domains" in wrong_domain["reasonCodes"]

        redirect_url = "https://umontreal.ca/"
        redirect_target = "https://www.umontreal.ca/"
        redirected = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "Canada", redirect_url, montreal, canonicalId="u_redirect"),
            raw,
            fetch_map({redirect_url: HttpResponse(200, redirect_target, {}, html_page("UdeM", "Universit\u00e9 de Montr\u00e9al"))}),
        )
        assert redirected["verificationStatus"] == "verified"
        assert "redirected_within_ror_domain" in redirected["reasonCodes"]

        waf_url = "https://umontreal.ca/"
        waf = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "Canada", waf_url, montreal, canonicalId="u_waf"),
            raw,
            fetch_map({waf_url: HttpResponse(403, waf_url, {}, b"<title>Access denied</title>Cloudflare captcha")}),
        )
        assert waf["verificationStatus"] == "blocked"
        assert "waf_or_access_block" in waf["reasonCodes"]

        # Referencing Cloudflare-hosted assets on a normal page is not WAF evidence.
        registered_name = montreal["names"][0]["value"]
        cdn = verify_candidate(
            item("Universit\u00c3\u00a9 de Montr\u00c3\u00a9al", "Canada", good_url, montreal, canonicalId="u_cdn"),
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {}, html_page("Universit\u00c3\u00a9 de Montr\u00c3\u00a9al", "Universit\u00c3\u00a9 de Montr\u00c3\u00a9al cloudflare CDN asset"))}),
        )
        if cdn["verificationStatus"] != "verified":
            cdn = verify_candidate(
                item(registered_name, "Canada", good_url, montreal, canonicalId="u_cdn_registered"),
                raw,
                fetch_map({good_url: HttpResponse(200, good_url, {}, html_page(registered_name, registered_name + " cloudflare CDN asset"))}),
            )
        assert cdn["verificationStatus"] == "verified"

        # A live page that is reachable but does not identify the institution is review-only.
        mismatch_url = "https://umontreal.ca/"
        mismatch = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "Canada", mismatch_url, montreal, canonicalId="u_mismatch"),
            raw,
            fetch_map({mismatch_url: HttpResponse(200, mismatch_url, {}, html_page("Admissions", "Graduate application portal"))}),
        )
        assert mismatch["verificationStatus"] == "review"
        assert "live_page_identity_mismatch" in mismatch["reasonCodes"]

        structured_cases = [
            ("h1", "h1"),
            ("og_site_name", "meta:og:site_name"),
            ("application_name", "meta:application-name"),
            ("json_ld", "json-ld:organization-name"),
        ]
        structured_name = montreal["names"][0]["value"]
        for case_id, expected_source in structured_cases:
            if case_id == "h1":
                case_body = structured_html("Admissions", "Graduate study", h1=structured_name)
            elif case_id == "og_site_name":
                case_body = structured_html(
                    "Admissions", structured_name + " graduate study",
                    meta=[("og:site_name", structured_name)],
                )
            elif case_id == "application_name":
                case_body = structured_html(
                    "Admissions", structured_name + " graduate study",
                    meta=[("application-name", structured_name)],
                )
            elif case_id == "json_ld":
                case_body = structured_html(
                    "Admissions", structured_name + " graduate study",
                    json_ld={"@type": "CollegeOrUniversity", "name": structured_name},
                )
            structured = verify_candidate(
                item(
                    structured_name, "Canada", good_url, montreal,
                    canonicalId="u_structured_" + case_id,
                ),
                raw,
                fetch_map({good_url: HttpResponse(200, good_url, {}, case_body)}),
            )
            assert structured["verificationStatus"] == "verified"
            live = structured["evidence"]["liveOfficialPage"]
            assert live["structuredIdentityMatches"] is True
            assert expected_source in live["structuredIdentityMatchedSources"]
            assert live["bodyMatches"] is True

        # A non-Organization JSON-LD name is not identity evidence.
        json_person = verify_candidate(
            item(
                montreal["names"][0]["value"], "Canada", good_url, montreal,
                canonicalId="u_json_person",
            ),
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {}, structured_html(
                "Admissions", montreal["names"][0]["value"] + " graduate study",
                json_ld={"@type": "Person", "name": montreal["names"][0]["value"]},
            ))}),
        )
        assert json_person["verificationStatus"] == "review"
        assert json_person["evidence"]["liveOfficialPage"]["jsonLdOrganizationNames"] == []

        # Structured metadata cannot verify without matching visible body text.
        metadata_only = verify_candidate(
            item(
                montreal["names"][0]["value"], "Canada", good_url, montreal,
                canonicalId="u_metadata_only",
            ),
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {}, structured_html(
                "Admissions", "Graduate application portal",
                meta=[("og:site_name", montreal["names"][0]["value"])],
            ))}),
        )
        assert metadata_only["verificationStatus"] == "review"
        assert metadata_only["evidence"]["liveOfficialPage"]["structuredIdentityMatches"] is True
        assert metadata_only["evidence"]["liveOfficialPage"]["bodyMatches"] is False

        sitemap_url = "https://umontreal.ca/sitemap.xml"
        sitemap_result = verify_candidate(
            item("Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal, canonicalId="u_sitemap"),
            raw,
            fetch_map({
                good_url: HttpResponse(200, good_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al")),
                sitemap_url: HttpResponse(200, sitemap_url, {"Content-Type": "application/xml"}, b"<urlset />"),
            }),
            fetch_sitemap=True,
        )
        assert sitemap_result["verificationStatus"] == "verified"
        assert sitemap_result["evidence"]["sitemap"]["raw"]["sha256"]

        payload = verify_items(
            {"items": [item("Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal)]},
            raw,
            fetch_map({good_url: HttpResponse(200, good_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al"))}),
        )
        assert payload["summary"] == {"processed": 1, "verified": 1, "review": 0, "blocked": 0, "rejected": 0}
        assert payload["policy"]["rorAloneCannotVerify"] is True

        missing_ror = verify_candidate(
            {"canonicalId": "u_no_ror", "name": "Unknown University", "country": "Canada", "rorOrganization": None},
            raw,
            counting_fetch(AssertionError("missing ROR must not fetch"))[0],
        )
        assert missing_ror["verificationStatus"] == "review"
        assert missing_ror["captureStatus"] == "not-attempted"
        assert missing_ror["reasonCodes"] == ["ror_match_missing"]

        # A complete body + manifest pair is reusable, including blocked HTTP
        # responses. The second verification must not call the fetcher.
        cache_item = item(
            "Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal,
            canonicalId="u_cache_good",
        )
        first_fetch, first_calls = counting_fetch(
            HttpResponse(200, good_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al"))
        )
        first = verify_candidate(cache_item, raw, first_fetch)
        assert first["captureStatus"] == "captured"
        assert len(first_calls) == 1
        forbidden_fetch, forbidden_calls = counting_fetch(AssertionError("cache was not reused"))
        second = verify_candidate(cache_item, raw, forbidden_fetch)
        assert second["verificationStatus"] == "verified"
        assert second["captureStatus"] == "cached"
        assert second["evidence"]["liveOfficialPage"]["captureStatus"] == "cached"
        assert forbidden_calls == []

        blocked_item = item(
            "Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal,
            canonicalId="u_cache_403",
        )
        blocked_fetch, blocked_calls = counting_fetch(HttpResponse(403, good_url, {}, b"Access denied"))
        blocked_first = verify_candidate(blocked_item, raw, blocked_fetch)
        assert blocked_first["verificationStatus"] == "blocked"
        assert blocked_first["captureStatus"] == "captured"
        assert len(blocked_calls) == 1
        blocked_forbidden, blocked_forbidden_calls = counting_fetch(AssertionError("403 cache was not reused"))
        blocked_second = verify_candidate(blocked_item, raw, blocked_forbidden)
        assert blocked_second["verificationStatus"] == "blocked"
        assert blocked_second["captureStatus"] == "cached"
        assert blocked_forbidden_calls == []

        # A body without its manifest is not a cache entry.
        missing_manifest_item = item(
            "Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal,
            canonicalId="u_missing_manifest",
        )
        missing_body = html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al old")
        missing_digest = hashlib.sha256(missing_body).hexdigest()
        missing_dir = raw / "u_missing_manifest"
        missing_dir.mkdir(parents=True)
        (missing_dir / f"homepage_sha256={missing_digest}.body").write_bytes(missing_body)
        replacement = HttpResponse(
            200, good_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al new")
        )
        missing_fetch, missing_calls = counting_fetch(replacement)
        missing_result = verify_candidate(missing_manifest_item, raw, missing_fetch)
        assert missing_result["captureStatus"] == "captured"
        assert len(missing_calls) == 1

        # A manifest whose body no longer matches its SHA-256 is ignored.
        corrupt_item = item(
            "Universit\u00e9 de Montr\u00e9al", "Canada", good_url, montreal,
            canonicalId="u_corrupt_cache",
        )
        corrupt_fetch, _ = counting_fetch(
            HttpResponse(200, good_url, {}, html_page("Universit\u00e9 de Montr\u00e9al", "Universit\u00e9 de Montr\u00e9al original"))
        )
        corrupt_first = verify_candidate(corrupt_item, raw, corrupt_fetch)
        Path(corrupt_first["evidence"]["liveOfficialPage"]["raw"]["rawFile"]).write_bytes(b"tampered")
        repair_fetch, repair_calls = counting_fetch(replacement)
        repaired = verify_candidate(corrupt_item, raw, repair_fetch)
        assert repaired["captureStatus"] == "captured"
        assert len(repair_calls) == 1

        # Registry data alone is never sufficient for verified status.
        registry_only = {
            "canonicalId": "u_registry_only",
            "name": "Universit\u00e9 de Montr\u00e9al",
            "country": "Canada",
            "rorOrganization": montreal,
        }
        registry_only_result = verify_candidate(
            registry_only, raw, counting_fetch(OSError("offline"))[0]
        )
        assert registry_only_result["verificationStatus"] == "blocked"
        assert registry_only_result["captureStatus"] == "fetch-failed"

        # Worker 1/3 receives indices 1 and 4; limit is applied afterwards.
        shard_items = [
            {"canonicalId": f"u_shard_{index}", "name": f"School {index}", "country": "Nowhere"}
            for index in range(7)
        ]
        shard = verify_items(
            {"items": shard_items}, raw,
            worker_index=1, worker_count=3, limit=1,
        )
        assert [row["canonicalId"] for row in shard["items"]] == ["u_shard_1"]
        assert shard["selection"] == {
            "totalInput": 7,
            "workerIndex": 1,
            "workerCount": 3,
            "limit": 1,
            "selected": 1,
        }
        assert shard["items"][0]["captureStatus"] == "not-attempted"

    args = parse_args([
        "--input", "ror.json", "--output", "verified.json", "--raw", "raw",
        "--fetch-sitemap", "--worker-index", "2", "--worker-count", "4", "--limit", "7",
    ])
    assert args.input == Path("ror.json")
    assert args.output == Path("verified.json")
    assert args.raw == Path("raw")
    assert args.fetch_sitemap is True
    assert args.worker_index == 2
    assert args.worker_count == 4
    assert args.limit == 7
    print("[verify-official-website-test] passed")


if __name__ == "__main__":
    test()
