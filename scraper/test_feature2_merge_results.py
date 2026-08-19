"""Regression checks for conservative Feature 2 URL merging."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.feature2_merge_results import (
    accept_application_audit_url,
    accept_captured_manifest_url,
    accept_crawl_url,
    application_audit_urls,
    captured_manifest_urls,
    review_urls,
    ror_domains_by_id,
)


def main() -> None:
    trusted = {"u_good": {"example.edu"}}
    row = {"canonicalId": "u_good"}

    accepted, reason, _url = accept_crawl_url(
        row,
        {"type": "master-catalog", "url": "https://graduate.example.edu/study/masters/programs"},
        trusted,
    )
    assert accepted and reason == "accepted"

    rejected_cases = [
        ({"type": "master-catalog", "url": "https://other.edu/study/masters"}, "off-trusted-domain"),
        ({"type": "master-catalog", "url": "https://example.edu/undergraduate/programs"}, "wrong-level"),
        ({"type": "program-page", "url": "https://example.edu/study/doctoral-degree-program"}, "wrong-level"),
        ({"type": "program-page", "url": "https://example.edu/degrees/masters-and-doctoral-programs"}, "wrong-level"),
        ({"type": "program-page", "url": "https://example.edu/degrees/bachelors-and-masters"}, "wrong-level"),
        ({"type": "program-page", "url": "https://example.edu/programs?degrees=masters%2Cdoctoral"}, "wrong-level"),
        ({"type": "program-page", "url": "https://example.edu/study/programs"}, "not-graduate-level"),
        ({"type": "program-page", "url": "https://example.edu/research/support-program"}, "not-graduate-level"),
        ({"type": "admission-requirements", "url": "https://example.edu/admissions"}, "not-specific"),
        ({"type": "program-page", "url": "https://example.edu/graduate/programs/certificates/data-science"}, "non-master-qualification"),
        ({"type": "program-page", "url": "https://example.edu/study/graduate-diploma-data-science"}, "non-master-qualification"),
        ({"type": "program-page", "url": "https://example.edu/programs/data-science-certificate/graduate"}, "non-master-qualification"),
        ({"type": "program-page", "url": "https://example.edu/masters/data-science/masters-thesis"}, "generic-or-noise"),
        ({"type": "master-catalog", "url": "https://mastersportal.com/example"}, "aggregator"),
    ]
    for item, expected_reason in rejected_cases:
        accepted, reason, _url = accept_crawl_url(row, item, trusted)
        assert not accepted and reason == expected_reason, (item, reason)

    review = {
        "urlReviews": [
            {
                "url": "https://example.edu/study/masters",
                "findings": [],
                "canonicalRecords": [{"canonicalId": "u_good"}],
            },
            {
                "url": "https://other.edu/study/masters",
                "findings": [],
                "canonicalRecords": [{"canonicalId": "u_good"}],
            },
            {
                "url": "https://example.edu/study/masters/shared",
                "findings": [{"subcategory": "generic-directory-cross-institution-mapping-risk"}],
                "canonicalRecords": [{"canonicalId": "u_good"}],
            },
            {
                "url": "https://example.edu/graduate/programs/certificates/data-science",
                "findings": [],
                "canonicalRecords": [{"canonicalId": "u_good"}],
            },
        ]
    }
    assignments = review_urls(review, {"u_good"}, trusted)
    assert assignments == {"u_good": {"https://example.edu/study/masters"}}

    verification = {
        "items": [
            {
                "canonicalId": "u_good",
                "sourceUniversityIds": ["u_good_alias"],
                "rorOrganization": {
                    "domains": ["example.edu"],
                    "links": [{"type": "website", "value": "https://graduate.example.edu"}],
                },
                "verification": {"evidence": {"registryIdentity": {"nameMatch": True, "countryMatch": True}}},
            },
            {
                "canonicalId": "u_bad",
                "rorOrganization": {"domains": ["wrong.example"]},
                "verification": {"evidence": {"registryIdentity": {"nameMatch": True, "countryMatch": False}}},
            },
        ]
    }
    ror = ror_domains_by_id(verification)
    assert ror == {"u_good": {"example.edu", "graduate.example.edu"}, "u_good_alias": {"example.edu", "graduate.example.edu"}}

    accepted_application = {
        "canonicalId": "u_good",
        "status": "captured",
        "feature2Eligible": True,
        "programUrl": "https://example.edu/programs/graduate-programs",
    }
    accepted, reason, _url = accept_application_audit_url("u_good", accepted_application, ror)
    assert accepted and reason == "accepted-application-catalog"
    scoped_application = dict(
        accepted_application,
        programUrl="https://example.edu/masters/computer-engineering",
    )
    accepted, reason, _url = accept_application_audit_url("u_good", scoped_application, ror)
    assert accepted and reason == "accepted-application-scope-program"

    application_rejections = [
        (dict(accepted_application, programUrl="https://other.edu/programs/graduate-programs"), "off-trusted-domain"),
        (dict(accepted_application, status="blocked"), "application-not-captured"),
        (dict(accepted_application, feature2Eligible=False), "application-out-of-scope"),
        (dict(accepted_application, programUrl="https://example.edu/graduate-student-life/programs/grad-mentor-program"), "application-non-program"),
        (dict(accepted_application, programUrl="https://example.edu/academics/degrees/master-of-laws"), "application-not-catalog-or-scope-program"),
    ]
    for program, expected_reason in application_rejections:
        accepted, reason, _url = accept_application_audit_url("u_good", program, ror)
        assert not accepted and reason == expected_reason, (program, reason)

    audit = {
        "universities": [
            {"canonicalId": "u_good", "programs": [accepted_application]},
            {"canonicalId": "u_covered", "programs": [dict(accepted_application, canonicalId="u_covered")]},
        ]
    }
    imported, accepted_rows, _rejected = application_audit_urls(
        audit,
        {"u_good", "u_covered"},
        {"u_good"},
        ror,
    )
    assert imported == {"u_good": {"https://example.edu/programs/graduate-programs"}}
    assert len(accepted_rows) == 1

    captured = {
        "status": "captured",
        "kind": "category",
        "statusCode": 200,
        "responseUrl": "https://graduate.example.edu/graduate-degree-programs",
        "documentTitle": "Graduate Degree Programs | Example University",
        "textLength": 4000,
        "blocked": False,
        "dynamicShell": False,
    }
    accepted, reason, _url, score = accept_captured_manifest_url(
        "u_good",
        "https://graduate.example.edu/graduate-degree-programs",
        captured,
        {},
        ror,
    )
    assert accepted and reason == "accepted-captured-catalog" and score >= 300

    scope_page = dict(
        captured,
        kind="program",
        responseUrl="https://example.edu/masters/computer-engineering",
        documentTitle="Master of Science in Computer Engineering",
    )
    accepted, reason, _url, _score = accept_captured_manifest_url(
        "u_good",
        scope_page["responseUrl"],
        scope_page,
        {},
        ror,
    )
    assert accepted and reason == "accepted-captured-scope-program"

    captured_rejections = [
        (
            "https://example.edu/programs/masters-degrees/finance-mba",
            dict(captured, kind="program", responseUrl="https://example.edu/programs/masters-degrees/finance-mba", documentTitle="Master of Business Administration"),
            "captured-not-catalog-or-scope-program",
        ),
        (
            "https://example.edu/graduate-program-application-deadline",
            dict(captured, kind="program", responseUrl="https://example.edu/graduate-program-application-deadline", documentTitle="Graduate Program Application Deadline"),
            "captured-non-program-page",
        ),
        (
            "https://example.edu/graduate-degree-programs",
            dict(captured, responseUrl="https://other.edu/graduate-degree-programs"),
            "off-ror-domain",
        ),
        (
            "https://example.edu/graduate-degree-programs",
            dict(captured, eligibleAsProgramEvidence=False),
            "captured-discovery-only",
        ),
    ]
    for url, record, expected_reason in captured_rejections:
        accepted, reason, _url, _score = accept_captured_manifest_url("u_good", url, record, {}, ror)
        assert not accepted and reason == expected_reason, (url, reason)

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        manifest_dir = root / "u_good"
        manifest_dir.mkdir()
        manifest = {
            "universityId": "u_good",
            "pages": {
                "https://example.edu/masters/computer-engineering": scope_page,
                "https://example.edu/programs/masters-degrees/finance-mba": captured_rejections[0][1],
            },
            "discovery": {"visited": {
                "https://graduate.example.edu/graduate-degree-programs": captured,
            }},
        }
        (manifest_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        imported, accepted_rows, rejected_rows = captured_manifest_urls(
            [root],
            {"u_good", "u_covered"},
            {"u_good"},
            ror,
            aliases={"u_good": "u_good"},
        )
        assert imported == {"u_good": {
            "https://example.edu/masters/computer-engineering",
            "https://graduate.example.edu/graduate-degree-programs",
        }}
        assert len(accepted_rows) == 2
        assert rejected_rows["captured-not-catalog-or-scope-program"] == 1
    print("[feature2-merge-test] passed")


if __name__ == "__main__":
    main()
