import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.build_top500_targets import (
    RANKINGS_DIR,
    RELATIONSHIP_OVERRIDES,
    ROOT,
    SOURCES,
    build_audit,
    build_entities,
    load_relationship_overrides,
    parse_args,
    resolve_ranking_files,
)


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def ranking_row(rank, uid, name, country, year=2025):
    return {
        "rank": rank,
        "universityId": uid,
        "name": name,
        "country": country,
        "score": 1.0,
        "year": year,
    }


def relationship(
    relationship_id,
    relation_type,
    member_ids,
    country,
    canonical_id=None,
    **directed,
):
    return {
        "id": relationship_id,
        "type": relation_type,
        "memberIds": member_ids,
        "canonicalId": canonical_id,
        "country": country,
        "rationale": f"Test relationship for {relationship_id}.",
        **directed,
    }


def test():
    manual_entities = build_entities(
        [
            {**ranking_row(1, "u_technical_university_of_munich", "Technical University of Munich", "Germany"), "source": "qs"},
            {**ranking_row(1, "u_tu_munich", "TU Munich", "Germany"), "source": "the"},
        ],
        aliases={},
    )
    assert len(manual_entities) == 1
    assert manual_entities[0]["canonicalId"] == "u_technical_university_of_munich"
    assert manual_entities[0]["rankingSources"] == ["qs", "the"]

    country_alias_entities = build_entities(
        [
            {**ranking_row(1, "u_charles", "Charles University", "Czech Republic"), "source": "qs"},
            {**ranking_row(1, "u_charles", "Charles University", "Czechia"), "source": "the"},
        ],
        aliases={},
    )
    assert len(country_alias_entities) == 1
    assert country_alias_entities[0]["country"] == "Czechia"

    relationship_payload = {
        "schemaVersion": 1,
        "relationships": [
            relationship(
                "rel-same",
                "sameInstitution",
                ["u_same_old", "u_same_new"],
                "France",
                canonical_id="u_same_new",
            ),
            relationship(
                "rel-former",
                "formerName",
                ["u_osaka_university", "u_the_university_of_osaka"],
                "Japan",
                canonical_id="u_the_university_of_osaka",
                fromId="u_osaka_university",
                toId="u_the_university_of_osaka",
            ),
            relationship(
                "rel-osaka-distinct-old",
                "distinctInstitution",
                ["u_osaka_metropolitan_university", "u_osaka_university"],
                "Japan",
            ),
            relationship(
                "rel-osaka-distinct-new",
                "distinctInstitution",
                ["u_osaka_metropolitan_university", "u_the_university_of_osaka"],
                "Japan",
            ),
            relationship(
                "rel-adelaide-successor",
                "successorOf",
                ["u_the_university_of_adelaide", "u_adelaide_university"],
                "Australia",
                fromId="u_the_university_of_adelaide",
                toId="u_adelaide_university",
            ),
            relationship(
                "rel-system-campus",
                "systemCampus",
                ["u_example_system", "u_example_north", "u_example_south"],
                "United States",
            ),
        ],
    }
    relationship_rows = [
        {**ranking_row(1, "u_same_old", "Universite Exemple", "France"), "source": "qs"},
        {**ranking_row(1, "u_same_new", "Example University", "France"), "source": "the"},
        {**ranking_row(2, "u_osaka_metropolitan_university", "Osaka Metropolitan University", "Japan"), "source": "qs"},
        {**ranking_row(2, "u_osaka_university", "Osaka University", "Japan"), "source": "arwu"},
        {**ranking_row(2, "u_the_university_of_osaka", "The University of Osaka", "Japan"), "source": "usnews"},
        {**ranking_row(3, "u_the_university_of_adelaide", "Adelaide", "Australia"), "source": "arwu"},
        {**ranking_row(3, "u_adelaide_university", "Adelaide", "Australia"), "source": "the"},
        {**ranking_row(4, "u_example_system", "Example University", "United States"), "source": "qs"},
        {**ranking_row(4, "u_example_north", "Example University", "United States"), "source": "the"},
        {**ranking_row(4, "u_example_south", "Example University", "United States"), "source": "arwu"},
    ]
    # Deliberately hostile legacy aliases prove protected relationships win
    # over both alias-root and exact-normalized-name automatic rules.
    hostile_aliases = {
        "u_osaka_metropolitan_university": "u_osaka_root",
        "u_osaka_university": "u_osaka_root",
        "u_the_university_of_osaka": "u_osaka_root",
        "u_the_university_of_adelaide": "u_adelaide_root",
        "u_adelaide_university": "u_adelaide_root",
        "u_example_system": "u_example_root",
        "u_example_north": "u_example_root",
        "u_example_south": "u_example_root",
    }
    relationship_entities = build_entities(
        relationship_rows,
        hostile_aliases,
        relationship_payload,
    )
    same_entity = next(
        item for item in relationship_entities if "u_same_old" in item["sourceUniversityIds"]
    )
    assert same_entity["canonicalId"] == "u_same_new"
    assert same_entity["sourceUniversityIds"] == ["u_same_new", "u_same_old"]
    assert same_entity["institutionRelationshipOverrideIds"] == ["rel-same"]

    osaka = next(
        item
        for item in relationship_entities
        if item["canonicalId"] == "u_the_university_of_osaka"
    )
    assert osaka["sourceUniversityIds"] == [
        "u_osaka_university",
        "u_the_university_of_osaka",
    ]
    metropolitan = next(
        item
        for item in relationship_entities
        if item["canonicalId"] == "u_osaka_metropolitan_university"
    )
    assert metropolitan["sourceUniversityIds"] == ["u_osaka_metropolitan_university"]
    assert "rel-osaka-distinct-old" in metropolitan["institutionRelationshipOverrideIds"]

    assert all(
        len(item["sourceUniversityIds"]) == 1
        for item in relationship_entities
        if set(item["sourceUniversityIds"])
        & {"u_the_university_of_adelaide", "u_adelaide_university"}
    )
    assert len(
        [
            item
            for item in relationship_entities
            if set(item["sourceUniversityIds"])
            & {"u_example_system", "u_example_north", "u_example_south"}
        ]
    ) == 3

    with TemporaryDirectory() as directory:
        root = Path(directory)
        rankings = root / "rankings"
        rankings.mkdir()
        rows_by_source = {
            "qs": [
                ranking_row(1, "u_alpha", "Alpha University", "USA", 2027),
                ranking_row(2, "u_beta", "Beta Institute", "France", 2027),
            ],
            "the": [
                ranking_row(1, "u_alpha_long", "Alpha University (Main Campus)", "United States"),
                ranking_row(2, "u_beta_alt", "Beta Institute", "France"),
            ],
            "arwu": [
                ranking_row(1, "u_alpha", "Alpha University", "United States", 2024),
                ranking_row(2, "u_same_name_de", "Beta Institute", "Germany", 2024),
            ],
            "usnews": [
                ranking_row(1, "u_alpha_long", "Alpha University", "United States"),
                ranking_row(2, "u_gamma", "Gamma University", "France"),
            ],
        }
        for source in SOURCES:
            write_json(rankings / f"{source}.json", rows_by_source[source])

        aliases = root / "aliases.json"
        write_json(
            aliases,
            {"canonicalById": {"u_alpha": "u_alpha", "u_alpha_long": "u_alpha"}},
        )
        raw_targets = root / "raw_targets.json"
        write_json(
            raw_targets,
            [
                {
                    "universityId": "u_alpha",
                    "sourceUniversityIds": ["u_alpha_long"],
                    "name": "Alpha University",
                    "country": "United States",
                    "indexUrl": "https://alpha.example/masters",
                },
                {
                    "universityId": "u_unused",
                    "name": "Unused University",
                    "country": "France",
                    "indexUrl": "https://unused.example/masters",
                },
            ],
        )

        overrides = root / "relationships.json"
        write_json(
            overrides,
            {
                "schemaVersion": 1,
                "relationships": [
                    relationship(
                        "rel-beta",
                        "sameInstitution",
                        ["u_beta", "u_beta_alt"],
                        "France",
                        canonical_id="u_beta",
                    )
                ],
            },
        )

        audit = build_audit(
            rankings,
            aliases,
            raw_targets,
            relationship_overrides_path=overrides,
            expected_rows_per_source=2,
        )
        assert audit["scope"]["rawRankingRows"] == 8
        assert audit["scope"]["canonicalEntityCount"] == 4
        assert audit["sources"]["qs"]["year"] == 2027
        assert audit["sources"]["qs"]["years"] == [2027]
        assert audit["sources"]["arwu"]["rankRange"] == {"min": 1, "max": 2}
        assert audit["sources"]["the"]["inputFile"] == str(
            (rankings / "the.json").resolve()
        )
        assert audit["schemaVersion"] == 2
        assert audit["institutionRelationshipOverrides"]["source"]["path"] == str(
            overrides.resolve()
        )
        assert len(audit["institutionRelationshipOverrides"]["source"]["sha256"]) == 64
        assert audit["institutionRelationshipOverrides"]["countsByType"] == {
            "distinctInstitution": 0,
            "formerName": 0,
            "sameInstitution": 1,
            "successorOf": 0,
            "systemCampus": 0,
        }

        alternate_the = root / "the-2026.json"
        write_json(alternate_the, rows_by_source["the"])
        explicit = build_audit(
            rankings,
            aliases,
            raw_targets,
            relationship_overrides_path=overrides,
            expected_rows_per_source=2,
            ranking_files={"the": alternate_the},
        )
        assert explicit["sources"]["the"]["inputFile"] == str(alternate_the.resolve())
        assert explicit["sources"]["qs"]["inputFile"] == str(
            (rankings / "qs.json").resolve()
        )
        assert resolve_ranking_files(rankings, {"arwu": root / "arwu-new.json"}) == {
            "qs": rankings / "qs.json",
            "the": rankings / "the.json",
            "arwu": root / "arwu-new.json",
            "usnews": rankings / "usnews.json",
        }

        args = parse_args(
            [
                "--qs-file", str(rankings / "qs.json"),
                "--the-file", str(alternate_the),
                "--arwu-file", str(rankings / "arwu.json"),
                "--usnews-file", str(rankings / "usnews.json"),
                "--output", str(root / "audit-v2.json"),
            ]
        )
        assert args.the_file == alternate_the
        assert args.output == root / "audit-v2.json"

        bad_qs = root / "bad-qs.json"
        write_json(bad_qs, rows_by_source["qs"][:1])
        try:
            build_audit(
                rankings,
                aliases,
                raw_targets,
                relationship_overrides_path=overrides,
                expected_rows_per_source=2,
                ranking_files={"qs": bad_qs},
            )
        except RuntimeError as error:
            assert "expected 2, found 1" in str(error)
            assert str(bad_qs) in str(error)
        else:
            raise AssertionError("explicit input row-count mismatch was not rejected")

        alpha = next(entity for entity in audit["entities"] if entity["canonicalId"] == "u_alpha")
        assert alpha["rankingSourceCount"] == 4
        assert alpha["coveredByExistingRawTarget"] is True
        assert alpha["indexUrl"] == "https://alpha.example/masters"
        alpha_target = next(
            target for target in audit["crawlTargetDraft"] if target["universityId"] == "u_alpha"
        )
        assert alpha_target["indexUrl"] == "https://alpha.example/masters"
        assert alpha_target["sourceUniversityIds"] == ["u_alpha", "u_alpha_long"]

        # Exact names merge in one country, but never across countries.
        beta_fr = next(entity for entity in audit["entities"] if entity["country"] == "France" and entity["name"] == "Beta Institute")
        beta_de = next(entity for entity in audit["entities"] if entity["country"] == "Germany")
        assert beta_fr["rankingSourceCount"] == 2
        assert beta_de["rankingSourceCount"] == 1
        assert beta_fr["canonicalId"] != beta_de["canonicalId"]

        gaps = audit["gaps"]
        assert len(gaps) == 3
        assert all(gap["indexUrl"] is None for gap in gaps)
        assert all(gap["coveredByExistingRawTarget"] is False for gap in gaps)
        assert audit["existingRawTargetCoverage"] == {
            "rawTargetCount": 2,
            "coveredCanonicalEntityCount": 1,
            "gapCanonicalEntityCount": 3,
            "usedRawTargetCount": 1,
            "unusedRawTargetCount": 1,
        }

        invalid_overrides = root / "invalid-relationships.json"
        write_json(
            invalid_overrides,
            {
                "schemaVersion": 1,
                "relationships": [
                    relationship(
                        "rel-invalid-successor",
                        "successorOf",
                        ["u_old", "u_new"],
                        "France",
                        canonical_id="u_new",
                        fromId="u_old",
                        toId="u_new",
                    )
                ],
            },
        )
        try:
            load_relationship_overrides(invalid_overrides)
        except RuntimeError as error:
            assert "non-merging relationship cannot declare canonicalId" in str(error)
        else:
            raise AssertionError("non-merging canonicalId was not rejected")

        proposal = root / "proposal.json"
        write_json(proposal, {"highConfidenceDuplicateGroups": []})
        stale_import = root / "stale-import.json"
        write_json(
            stale_import,
            {
                "schemaVersion": 1,
                "reviewedProposalImports": [
                    {
                        "id": "stale-proposal",
                        "path": proposal.name,
                        "sha256": "0" * 64,
                        "field": "highConfidenceDuplicateGroups",
                        "approvedCanonicalIds": [],
                    }
                ],
                "relationships": [],
            },
        )
        try:
            load_relationship_overrides(stale_import)
        except RuntimeError as error:
            assert "proposal SHA-256 mismatch" in str(error)
        else:
            raise AssertionError("stale reviewed proposal import was not rejected")

    production_overrides = load_relationship_overrides(RELATIONSHIP_OVERRIDES)
    production_types = {item["type"] for item in production_overrides["relationships"]}
    assert production_types == {
        "sameInstitution",
        "formerName",
        "successorOf",
        "systemCampus",
        "distinctInstitution",
    }
    production_relationships = {
        item["id"]: item for item in production_overrides["relationships"]
    }
    assert production_relationships["rel-aus-adelaide-2026-succession"]["type"] == "successorOf"
    assert production_relationships["rel-aus-adelaide-2026-succession"]["canonicalId"] is None
    assert production_relationships["rel-jpn-osaka-2025-rename"]["type"] == "formerName"
    assert production_relationships["rel-jpn-osaka-2025-rename"]["canonicalId"] == (
        "u_the_university_of_osaka"
    )
    assert production_relationships[
        "rel-jpn-osaka-metropolitan-distinct-from-renamed-osaka"
    ]["type"] == "distinctInstitution"
    assert production_overrides["_source"]["reviewedProposalSources"] == [
        {
            "id": "reviewed-high-confidence-same-institution-v1",
            "path": str(
                (RELATIONSHIP_OVERRIDES.parent / "top500_alias_proposals.json").resolve()
            ),
            "sha256": "78ce171fc26b67c1288e5bc35d2d64561da02d58f1e163802260a31e75f442e4",
            "field": "highConfidenceDuplicateGroups",
            "approvedCanonicalIdCount": 84,
        }
    ]

    # Current v2 production inputs must remain four complete, intended editions.
    the_files = sorted(
        (ROOT / "scraper" / "raw" / "rankings" / "the" / "year=2026").glob(
            "*/top500.normalized.json"
        ),
        key=lambda path: path.parent.name,
    )
    arwu_files = sorted(
        (ROOT / "scraper" / "raw" / "rankings" / "arwu" / "year=2025").glob(
            "*/top500.normalized.json"
        ),
        key=lambda path: path.parent.name,
    )
    assert the_files and arwu_files
    production_files = {
        "qs": RANKINGS_DIR / "qs.json",
        "the": the_files[-1],
        "arwu": arwu_files[-1],
        "usnews": RANKINGS_DIR / "usnews.json",
    }
    expected_years = {"qs": 2027, "the": 2026, "arwu": 2025, "usnews": 2025}
    for source, path in production_files.items():
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        assert len(rows) == 500
        assert {row["year"] for row in rows} == {expected_years[source]}
    print("[top500-targets-test] passed")


if __name__ == "__main__":
    test()
