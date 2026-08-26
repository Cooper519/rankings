from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scraper.build_school_urls import (
    hosts_overlap,
    remove_cross_school_program_urls,
    verification_candidate,
    web_url,
)


def test_verified_homepage_prefers_live_final_url() -> None:
    item = {
        "verificationStatus": "verified",
        "rorOrganization": {"links": [{"type": "website", "value": "https://registry.example.edu"}]},
        "verification": {"evidence": {
            "domainConsistency": {"candidateUrl": "https://candidate.example.edu"},
            "liveOfficialPage": {
                "requestedUrl": "https://requested.example.edu",
                "finalUrl": "https://final.example.edu",
            },
        }},
    }
    assert verification_candidate(item) == ("https://final.example.edu", "verified")


def test_blocked_homepage_uses_registry_candidate() -> None:
    item = {
        "verificationStatus": "blocked",
        "rorOrganization": {"links": [{"type": "website", "value": "https://registry.example.edu"}]},
        "verification": {"evidence": {
            "domainConsistency": {"candidateUrl": "https://candidate.example.edu"},
            "liveOfficialPage": {"finalUrl": "https://unverified-redirect.example.org"},
        }},
    }
    assert verification_candidate(item) == ("https://candidate.example.edu", "blocked")


def test_rejected_candidate_is_not_published() -> None:
    item = {
        "verificationStatus": "rejected",
        "rorOrganization": {"links": [{"type": "website", "value": "https://wrong.example.edu"}]},
    }
    assert verification_candidate(item) is None


def test_invalid_urls_are_rejected() -> None:
    assert web_url("javascript:alert(1)") is None
    assert web_url("//example.edu") is None
    assert web_url("https://example.edu/path") == "https://example.edu/path"


def test_subdomains_are_treated_as_the_same_school_domain() -> None:
    assert hosts_overlap("https://www.uibk.ac.at/programmes", "https://uibk.ac.at/")
    assert not hosts_overlap("https://uzh.ch/", "https://ethz.ch/")


def test_program_url_claimed_by_another_school_is_removed() -> None:
    records = {
        "u_university_of_innsbruck": {
            "url": "https://www.uibk.ac.at/en/programmes/ma-computer-science",
            "urlKind": "official-programme-directory",
        },
        "u_medical_university_of_innsbruck": {
            "url": "https://www.uibk.ac.at/en/admission-department/admission/",
            "urlKind": "official-programme-index",
        },
        "u_university_of_zurich": {
            "url": "https://www.ifi.uzh.ch/en.html",
            "urlKind": "official-department",
        },
    }
    filtered = remove_cross_school_program_urls(records)
    assert "u_medical_university_of_innsbruck" not in filtered
    assert "u_university_of_innsbruck" in filtered
    assert "u_university_of_zurich" in filtered


def main() -> None:
    test_verified_homepage_prefers_live_final_url()
    test_blocked_homepage_uses_registry_candidate()
    test_rejected_candidate_is_not_published()
    test_invalid_urls_are_rejected()
    test_subdomains_are_treated_as_the_same_school_domain()
    test_program_url_claimed_by_another_school_is_removed()
    print("[school-url-builder-test] passed")


if __name__ == "__main__":
    main()
