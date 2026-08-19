"""Focused tests for the local Feature 2 coverage builder."""
from scraper.programs.build_feature2_coverage_v1 import build_records, make_payload


def main() -> None:
    scope = {
        "entities": [
            {
                "canonicalId": "u_covered",
                "name": "Covered University",
                "country": "France",
                "rankingSources": ["qs"],
                "rankingScope": {
                    "eligible": True,
                    "selections": [{"source": "qs", "rowIndex": 2, "displayedRank": 3, "year": 2027}],
                },
            },
            {
                "canonicalId": "u_missing",
                "name": "Missing University",
                "country": "Germany",
                "rankingSources": ["the"],
                "rankingScope": {
                    "eligible": True,
                    "selections": [{"source": "the", "rowIndex": 7, "displayedRank": 8, "year": 2025}],
                },
            },
            {
                "canonicalId": "u_deferred",
                "name": "Deferred University",
                "country": "Japan",
                "rankingScope": {"eligible": False, "selections": []},
            },
        ]
    }
    review = {
        "urlReviews": [
            {
                "url": "https://covered.example.edu/masters/computing",
                "findings": [],
                "canonicalRecords": [{"canonicalId": "u_covered"}],
            },
            {
                "url": "https://missing.example.edu/",
                "findings": [{"category": "obvious-non-program-catalog"}],
                "canonicalRecords": [{"canonicalId": "u_missing"}],
            },
        ]
    }
    records = build_records(scope, review, {
        "qs": [{"universityId": "u_frontend_covered"}, {"universityId": "u_frontend_covered"}, {"universityId": "u_frontend_covered"}],
        "the": [],
    })
    assert len(records) == 2
    assert records[0]["coverageStatus"] == "covered"
    assert records[0]["urlCount"] == 1
    assert records[0]["rankingUniversityIds"] == ["u_frontend_covered"]
    assert records[1]["coverageStatus"] == "missing"
    payload = make_payload(records, generated_at="2026-08-14T00:00:00+00:00")
    assert payload["summary"]["schools"] == 2
    assert payload["summary"]["coveredSchools"] == 1
    assert payload["summary"]["missingSchools"] == 1
    assert payload["summary"]["coveragePercent"] == 50.0
    print("[feature2-coverage-builder-test] passed")


if __name__ == "__main__":
    main()
