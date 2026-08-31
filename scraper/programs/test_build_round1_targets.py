from __future__ import annotations

from scraper.programs.build_round1_targets import SOURCES, build, in_scope


def row(rank, uid, country="Germany", name=None):
    return {
        "rank": rank,
        "universityId": uid,
        "name": name or uid,
        "country": country,
        "year": 2026,
    }


def test_scope_bounds_and_mainland_policy() -> None:
    assert in_scope(row(50, "u_a"))
    assert in_scope(row(250, "u_b"))
    assert not in_scope(row(49, "u_c"))
    assert not in_scope(row(251, "u_d"))
    assert not in_scope(row(100, "u_cn", "China"))
    assert in_scope(row(100, "u_hk", "Hong Kong"))


def test_build_deduplicates_aliases_and_prefers_programme_url() -> None:
    rankings = {source: [] for source in SOURCES}
    rankings["qs"] = [row(50, "u_alias", name="Example Tech")]
    rankings["the"] = [row(75, "u_example", name="Example University")]
    targets, audit = build(
        rankings,
        {"u_alias": "u_example"},
        {"u_example": {"name": {"en": "Example University"}, "country": "Germany", "region": "Western Europe"}},
        [
            {"canonicalId": "u_example", "url": "https://example.edu", "urlKind": "school-homepage", "verificationStatus": "verified"},
            {"canonicalId": "u_example", "url": "https://example.edu/masters", "urlKind": "official-programme-directory", "verificationStatus": "verified"},
        ],
    )
    assert len(targets) == 1
    assert targets[0]["universityId"] == "u_example"
    assert targets[0]["indexUrl"] == "https://example.edu/masters"
    assert targets[0]["rankingSources"] == ["qs", "the"]
    assert audit["summary"]["rankingEntries"] == 2


def main() -> None:
    test_scope_bounds_and_mainland_policy()
    test_build_deduplicates_aliases_and_prefers_programme_url()
    print("[round1-targets-test] passed")


if __name__ == "__main__":
    main()
