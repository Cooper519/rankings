from __future__ import annotations

import json

from scraper.programs.build_top350_engineering_url_quality_review_v1 import (
    PRIORITY_QUEUE,
    URL_EXPORT,
    build_review,
    load_json,
    load_url_lines,
    obvious_non_program_finding,
    specific_url_lines,
)


def all_keys(value):
    found = set()
    if isinstance(value, dict):
        found.update(str(key).casefold() for key in value)
        for child in value.values():
            found.update(all_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(all_keys(child))
    return found


def fixture_item(url, canonical_id, name):
    return {
        "url": url,
        "sourceUrl": "https://example.edu/catalog",
        "canonicalId": canonical_id,
        "universityName": name,
        "top350Selections": [],
    }


def run() -> None:
    clean = "https://example.edu/programmes/master-computer-science"
    non_program = "https://example.edu/companies/engineering"
    malformed = "https://example.edu/programmes/robotics/&utm_source=story&utm_campaign=test"
    root_homepage = "https://example.edu/"
    radboud = "https://www.ru.nl/en/education/masters/artificial-intelligence"
    uab = "https://www.uab.cat/web/studies/graduate/university-master-s-degrees/by-areas-of-knowledge/engineering-and-technology-1.html"
    fixture = {
        "schemaVersion": 2,
        "generatedAt": "fixed",
        "items": [
            fixture_item(clean, "u_clean", "Clean University"),
            fixture_item(non_program, "u_clean", "Clean University"),
            fixture_item(malformed, "u_clean", "Clean University"),
            fixture_item(root_homepage, "u_clean", "Clean University"),
            fixture_item(radboud, "u_radboud_university", "Radboud University"),
            fixture_item(radboud, "u_radboud_university_nijmegen", "Radboud University Nijmegen"),
            fixture_item(uab, "u_autonomous_university_of_barcelona", "Autonomous University of Barcelona"),
            fixture_item(uab, "u_university_of_barcelona", "University of Barcelona"),
        ],
    }
    urls = [clean, non_program, malformed, root_homepage, radboud, uab]
    result = build_review(fixture, urls, input_metadata={"fixture": True})
    summary = result["summary"]
    assert summary["reviewedUniqueUrlCount"] == 6
    assert summary["statusCounts"] == {"pass": 1, "review": 5}
    assert summary["findingCategoryCounts"] == {
        "obvious-non-program-catalog": 2,
        "malformed-tracking-path": 1,
        "cross-canonical-duplicate": 2,
    }
    assert summary["crossCanonicalDuplicateGroupCount"] == 2
    assert summary["crossCanonicalDuplicateRecordExcess"] == 2
    assert summary["duplicateClassificationCounts"] == {
        "generic-directory-cross-institution-mapping-risk": 1,
        "same-institution-alias": 1,
    }
    by_url = {row["url"]: row for row in result["urlReviews"]}
    assert by_url[clean]["status"] == "pass"
    assert by_url[clean]["findings"] == []
    assert specific_url_lines(result) == [clean, malformed, radboud, uab]
    assert by_url[non_program]["findings"][0]["category"] == "obvious-non-program-catalog"
    assert by_url[root_homepage]["findings"][0]["subcategory"] == "generic-domain-root"
    assert by_url[malformed]["findings"][0]["suggestedUrl"] == (
        "https://example.edu/programmes/robotics"
    )
    assert by_url[uab]["findings"][0]["subcategory"] == (
        "generic-directory-cross-institution-mapping-risk"
    )
    assert obvious_non_program_finding(
        "https://example.edu/courses/undergraduate/computer-science"
    )["subcategory"] == "non-master-degree-level"
    assert obvious_non_program_finding(
        "https://example.edu/research/doctoral-school/doctoral-programme-energy"
    )["subcategory"] == "non-master-degree-level"
    again = build_review(
        {**fixture, "items": list(reversed(fixture["items"]))},
        list(reversed(urls)),
        input_metadata={"fixture": True},
    )
    assert json.dumps(result, ensure_ascii=False, sort_keys=True) == json.dumps(
        again, ensure_ascii=False, sort_keys=True
    )

    current = build_review(load_json(PRIORITY_QUEUE), load_url_lines(URL_EXPORT))
    current_summary = current["summary"]
    current_urls = load_url_lines(URL_EXPORT)
    reviewed_count = current_summary["reviewedUniqueUrlCount"]
    finding_counts = current_summary["findingCategoryCounts"]
    assert reviewed_count == len(current_urls) == len(set(current_urls))
    assert sum(current_summary["statusCounts"].values()) == reviewed_count
    assert finding_counts["malformed-tracking-path"] == 0
    assert len(specific_url_lines(current)) == (
        reviewed_count - finding_counts["obvious-non-program-catalog"]
    )
    assert current_summary["crossCanonicalDuplicateGroupCount"] == len(
        current["crossCanonicalDuplicateGroups"]
    )
    assert current_summary["crossCanonicalDuplicateRecordExcess"] >= (
        current_summary["crossCanonicalDuplicateGroupCount"]
    )
    output_keys = all_keys(current)
    for forbidden in ("requirements", "deadline", "material", "documents", "language", "rawpath"):
        assert forbidden not in output_keys
    print("[top350-engineering-url-quality-review-test] passed")


if __name__ == "__main__":
    run()
