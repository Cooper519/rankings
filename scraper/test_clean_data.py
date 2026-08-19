"""Regression tests for deterministic data cleaning rules."""
from __future__ import annotations

from scraper.clean_data import (
    canonical_material,
    clean_program_title,
    clean_requirements,
    normalized_country,
    normalized_name,
)
from scraper.programs.normalize import normalize_deadlines


def test_normalized_name_handles_cross_ranking_variants():
    assert normalized_name("University of California--Berkeley") == "california berkeley"
    assert normalized_name("Texas A&M University--College Station") == "texas a and m station"
    assert normalized_name("EPFL - \u00c9cole Polytechnique F\u00e9d\u00e9rale de Lausanne") == "epfl ecole polytechnique federale de lausanne"


def test_country_aliases_keep_product_regions_consistent():
    assert normalized_country("China (Mainland)") == "China"
    assert normalized_country("Hong Kong SAR") == "Hong Kong"
    assert normalized_country("Türkiye") == "Turkey"


def test_low_signal_materials_removed_only_for_unverified_records():
    assert canonical_material("gre", verified=False) is None
    assert canonical_material("bachelor", verified=False) is None
    assert canonical_material("gre", verified=True) == "GRE"
    assert canonical_material("Transcript of records", verified=False) == "Transcript"


def test_requirements_keep_frontend_compatible_keys():
    cleaned = clean_requirements({"ielts": " 6.5 ", "academic": ""})
    assert cleaned == {
        "gpa": None,
        "ielts": "6.5",
        "toefl": None,
        "language": None,
        "academic": None,
    }


def test_admission_title_with_specific_program_is_recovered():
    assert clean_program_title("Admission to the Master's programme in Banking and Finance (MBF)") == "Banking and Finance (MBF)"


def test_deadline_applicant_group_is_classified():
    # Explicit applicant groups are preserved when valid.
    explicit = normalize_deadlines([
        {"round": "EU applicants", "date": "2026-12-01", "applicantGroup": "EU"},
        {"round": "International", "date": "2026-12-15", "applicantGroup": "Non-EU"},
        {"round": "All applicants", "date": "2026-11-01", "applicantGroup": "All"},
    ])
    assert explicit == [
        {"round": "All applicants", "date": "2026-11-01", "applicantGroup": "All"},
        {"round": "EU applicants", "date": "2026-12-01", "applicantGroup": "EU"},
        {"round": "International", "date": "2026-12-15", "applicantGroup": "Non-EU"},
    ]
    # Inferred groups from round labels when none supplied.
    inferred = normalize_deadlines([
        {"round": "Non-EU round", "date": "2026-12-01"},
        {"round": "EU/EEA round", "date": "2026-12-15"},
        {"round": "International", "date": "2026-11-01"},
    ])
    assert inferred == [
        {"round": "International", "date": "2026-11-01", "applicantGroup": "Non-EU"},
        {"round": "Non-EU round", "date": "2026-12-01", "applicantGroup": "Non-EU"},
        {"round": "EU/EEA round", "date": "2026-12-15", "applicantGroup": "EU"},
    ]
    # Invalid applicant group falls back to Unknown, never to a guessed value.
    invalid = normalize_deadlines([
        {"round": "Generic", "date": "2026-12-01", "applicantGroup": "Maybe"},
    ])
    assert invalid == [
        {"round": "Generic", "date": "2026-12-01", "applicantGroup": "Unknown"},
    ]


def test_deadline_cleanup_filters_past_dates_and_sorts():
    cleaned = normalize_deadlines([
        {"round": "Old", "date": "2025-01-01"},
        {"round": "Round 2", "date": "15 December 2026"},
        {"round": "Round 1", "date": "2026-11-01"},
    ])
    # Past dates are filtered; survivors are ISO-normalized, sorted, and tagged
    # with an applicantGroup (EU / Non-EU / All / Unknown) per the deadline spec.
    assert cleaned == [
        {"round": "Round 1", "date": "2026-11-01", "applicantGroup": "Unknown"},
        {"round": "Round 2", "date": "2026-12-15", "applicantGroup": "Unknown"},
    ]


def main():
    test_normalized_name_handles_cross_ranking_variants()
    test_country_aliases_keep_product_regions_consistent()
    test_low_signal_materials_removed_only_for_unverified_records()
    test_requirements_keep_frontend_compatible_keys()
    test_admission_title_with_specific_program_is_recovered()
    test_deadline_cleanup_filters_past_dates_and_sorts()
    test_deadline_applicant_group_is_classified()
    print("[clean-data-test] passed")


if __name__ == "__main__":
    main()
