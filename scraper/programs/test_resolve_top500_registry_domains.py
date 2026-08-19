import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scraper.programs.resolve_top500_registry_domains import (
    HttpCapture,
    manifest_file_for,
    normalized_country,
    query_variants,
    query_urls,
    registry_domains,
    resolve_item,
    score_organization,
    select_match,
)


def organization(name, country, domains=None, aliases=None, links=None, ror_id="https://ror.org/abc"):
    names = [{"value": name, "types": ["ror_display"]}]
    names.extend({"value": alias, "types": ["alias"]} for alias in aliases or [])
    return {
        "id": ror_id,
        "names": names,
        "locations": [{"geonames_details": {"country_name": country}}],
        "domains": domains or [],
        "links": links or [],
    }


def test_exact_same_country_match_is_high_confidence():
    target = {"name": "Massachusetts Institute of Technology (MIT)", "country": "United States"}
    item = organization("Massachusetts Institute of Technology", "United States of America", ["mit.edu"])
    score = score_organization(target, item)
    assert score["confidence"] == "high"
    assert score["countryMatch"] is True
    assert score["registryDomains"] == ["mit.edu"]


def test_cross_country_exact_name_is_never_selected():
    target = {"name": "Alpha University", "country": "Canada"}
    wrong = organization("Alpha University", "United States", ["alpha.edu"])
    selected, candidates = select_match(target, {"items": [wrong]})
    assert selected is None
    assert candidates[0]["confidence"] == "review"


def test_alias_translation_and_link_domain_are_supported():
    target = {"name": "University of Buenos Aires", "country": "Argentina"}
    item = organization(
        "Universidad de Buenos Aires",
        "Argentina",
        aliases=["University of Buenos Aires"],
        links=[{"type": "website", "value": "https://www.uba.ar/"}, {"type": "wikipedia", "value": "https://en.wikipedia.org/wiki/X"}],
    )
    selected, _ = select_match(target, {"items": [item]})
    assert selected is not None
    assert selected["registryDomains"] == ["uba.ar"]


def test_country_aliases_are_normalized():
    assert normalized_country("United States of America") == "united states"
    assert normalized_country("Türkiye") == "turkey"


def test_parenthetical_acronym_gets_a_second_auditable_query():
    urls = query_urls("Universidad Nacional de La Plata (UNLP)")
    assert len(urls) == 2
    assert "UNLP" in urls[0]
    assert "UNLP" not in urls[1]


def test_queries_use_only_attributed_ranking_name_sources():
    target = {
        "name": "Example University (EU)",
        "country": "France",
        "sourceNames": ["Université Exemple | Example University"],
        "rankingAppearances": [
            {"source": "qs", "name": "Example University - France"},
            {"source": "the", "name": "Example University"},
        ],
        "queries": [{"query": "untrusted search-engine string"}],
    }
    variants = query_variants(target)
    assert [item["name"] for item in variants] == [
        "Example University (EU)",
        "Example University",
        "Université Exemple | Example University",
        "Université Exemple",
        "Example University - France",
    ]
    assert variants[1]["transformations"] == ["remove-short-parenthetical-abbreviation"]
    assert variants[3]["transformations"] == ["remove-local-name-after-pipe"]
    assert variants[4]["source"] == "rankingAppearances[0].name"
    assert all("untrusted" not in item["queryUrl"] for item in variants)


def test_identity_bearing_parentheses_are_never_removed():
    variants = query_variants({
        "name": "University of California (San Francisco Campus)",
        "country": "United States",
    })
    assert [item["name"] for item in variants] == [
        "University of California (San Francisco Campus)"
    ]


def test_only_same_country_ranking_suffix_is_removed():
    target = {"name": "Northeastern University - China", "country": "China"}
    assert [item["name"] for item in query_variants(target)] == [
        "Northeastern University - China",
        "Northeastern University",
    ]
    protected = {"name": "Northeastern University - China", "country": "United States"}
    assert len(query_variants(protected)) == 1


def test_transformed_query_does_not_lower_selection_threshold():
    target = {
        "name": "University of Colorado System",
        "country": "United States",
        "rankingAppearances": [{"source": "qs", "name": "University of Colorado System"}],
    }
    campus = organization("University of Colorado Boulder", "United States", ["colorado.edu"])
    selected, candidates = select_match(target, {"items": [campus]})
    assert selected is None
    assert candidates[0]["confidence"] == "review"


def test_successor_name_is_not_invented_or_cross_selected():
    target = {"name": "Adelaide University", "country": "Australia"}
    predecessor = organization("University of Adelaide", "Australia", ["adelaide.edu.au"])
    selected, _ = select_match(target, {"items": [predecessor]})
    assert selected is None


def test_resolve_item_preserves_raw_manifest_and_full_selected_organization():
    target = {"canonicalId": "u_uba", "name": "University of Buenos Aires", "country": "Argentina"}
    selected = organization(
        "Universidad de Buenos Aires",
        "Argentina",
        domains=["uba.ar"],
        aliases=["University of Buenos Aires"],
        links=[{"type": "website", "value": "https://www.uba.ar/"}],
        ror_id="https://ror.org/01b4m3y30",
    )
    body = json.dumps({"number_of_results": 1, "items": [selected]}).encode("utf-8")
    capture = HttpCapture(
        requested_url="https://api.ror.org/v2/organizations?query=test",
        final_url="https://api.ror.org/v2/organizations?query=test",
        status=200,
        headers={"Content-Type": "application/json"},
        body=body,
    )
    with TemporaryDirectory() as directory, patch(
        "scraper.programs.resolve_top500_registry_domains.fetch_json",
        return_value=(capture, json.loads(body)),
    ) as fetch:
        raw_root = Path(directory)
        first = resolve_item(target, raw_root, 1)
        assert first["rorOrganization"]["id"] == selected["id"]
        raw_file = Path(first["registryResolution"]["rawFile"])
        manifest_file = manifest_file_for(raw_file)
        assert gzip.decompress(raw_file.read_bytes()) == body
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert manifest["status"] == 200
        assert manifest["sha256"] == first["registryResolution"]["rawSha256"]
        assert manifest["requestedUrl"]

        second = resolve_item(target, raw_root, 1)
        assert second["registryResolution"]["captureStatus"] == "cached"
        assert fetch.call_count == 1


def test_each_unsuccessful_query_variant_has_independent_raw_and_manifest():
    target = {
        "canonicalId": "u_example",
        "name": "Example University (EU)",
        "country": "France",
        "rankingAppearances": [{"source": "qs", "name": "Université Exemple"}],
    }
    no_match = organization("Different Institute", "France", ["different.fr"])
    body = json.dumps({"number_of_results": 1, "items": [no_match]}).encode("utf-8")

    def fake_fetch(url, timeout):
        capture = HttpCapture(url, url, 200, {"Content-Type": "application/json"}, body)
        return capture, json.loads(body)

    with TemporaryDirectory() as directory, patch(
        "scraper.programs.resolve_top500_registry_domains.fetch_json",
        side_effect=fake_fetch,
    ) as fetch:
        item = resolve_item(target, Path(directory), 1)
        attempts = item["registryResolution"]["attempts"]
        assert fetch.call_count == 3
        assert item["verificationStatus"] == "registry-review-required"
        assert len({attempt["rawFile"] for attempt in attempts}) == 3
        assert all(Path(attempt["rawFile"]).exists() for attempt in attempts)
        assert all(Path(attempt["rawManifestFile"]).exists() for attempt in attempts)
        assert attempts[1]["transformations"] == ["remove-short-parenthetical-abbreviation"]
        assert attempts[2]["querySource"] == "rankingAppearances[0].name"


if __name__ == "__main__":
    test_exact_same_country_match_is_high_confidence()
    test_cross_country_exact_name_is_never_selected()
    test_alias_translation_and_link_domain_are_supported()
    test_country_aliases_are_normalized()
    test_parenthetical_acronym_gets_a_second_auditable_query()
    test_queries_use_only_attributed_ranking_name_sources()
    test_identity_bearing_parentheses_are_never_removed()
    test_only_same_country_ranking_suffix_is_removed()
    test_transformed_query_does_not_lower_selection_threshold()
    test_successor_name_is_not_invented_or_cross_selected()
    test_resolve_item_preserves_raw_manifest_and_full_selected_organization()
    test_each_unsuccessful_query_variant_has_independent_raw_and_manifest()
    print("[registry-domain-resolver-test] passed")
