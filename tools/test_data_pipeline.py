"""Regression tests for the canonical raw -> SQLite -> JSON pipeline."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from tools.data_pipeline import RANKING_SOURCES, build_database, export_database


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _fixture(root: Path) -> None:
    package = root / "raw" / "universities" / "u_example"
    _write_json(
        package / "manifest.json",
        {
            "schema_version": 1,
            "package_version": 1,
            "university_id": "u_example",
            "name": "Example University",
            "country": "United Kingdom",
            "website": "https://example.edu/",
            "updated_at": "2026-08-30T10:00:00+00:00",
        },
    )
    _write_json(
        package / "sources.json",
        [
            {
                "source_id": "src_program",
                "url": "https://example.edu/msc-data",
                "source_type": "official_web",
                "retrieved_at": "2026-08-30T09:00:00+00:00",
                "verification_status": "verified",
            }
        ],
    )
    _write_json(package / "reviews.json", [])
    _write_json(
        package / "projects.json",
        [
            {
                "project_id": "u_example_main_data_msc",
                "university_id": "u_example",
                "campus_id": "main",
                "normalized_program_code": "data_msc",
                "name": "MSc Data Science",
                "degree": "MSc",
                "subject": "Computer Science",
                "official_url": "https://example.edu/msc-data",
                "status": "active",
                "verification_status": "verified",
                "admission_cycles": [
                    {
                        "cycle_id": "27fall",
                        "academic_year": 2027,
                        "entry_term": "fall",
                        "status": "current",
                        "verification_status": "verified",
                        "timelines": [
                            {
                                "event": "application_deadline",
                                "date_type": "exact",
                                "date": "2027-01-15",
                                "date_end": None,
                                "applicant_group": "all",
                                "source_id": "src_program",
                                "verification_status": "verified",
                            }
                        ],
                        "requirements": {
                            "language": {
                                "status": "required",
                                "tests": [{"name": "IELTS", "min_score": "7.0"}],
                            },
                            "gre": {"status": "not_required", "min_score": None},
                            "gmat": {"status": "not_required", "min_score": None},
                            "academic": {"status": "required", "description": "2:1 degree"},
                            "source_id": "src_program",
                            "verification_status": "verified",
                        },
                        "fees": [
                            {
                                "fee_type": "tuition",
                                "amount": "25000",
                                "currency": "GBP",
                                "period": "year",
                                "applicant_group": "international",
                                "source_id": "src_program",
                                "verification_status": "verified",
                            }
                        ],
                    }
                ],
            }
        ],
    )

    # An incomplete package must be reported without stopping recoverable data.
    (root / "raw" / "universities" / "u_pending").mkdir(parents=True)

    for source in RANKING_SOURCES:
        _write_json(
            root / "raw" / "rankings" / source / "normalized.json",
            [
                {
                    "rank": 1,
                    "universityId": "u_example",
                    "name": "Example University",
                    "country": "United Kingdom",
                    "score": 99.0,
                    "year": 2026,
                }
            ],
        )
    _write_json(
        root / "raw" / "university_aliases.json",
        {
            "version": 1,
            "canonicalById": {"u_example": "u_example", "u_example_alias": "u_example"},
            "reasonById": {"u_example_alias": "test alias"},
        },
    )

    # This record proves that frontend output is never treated as pipeline input.
    _write_json(
        root / "frontend" / "public" / "data" / "programs.json",
        [{"id": "legacy_only", "universityId": "u_example", "program": "Legacy"}],
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_build_and_export() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _fixture(root)
        database = root / "normalized" / "rankingselect.sqlite"
        report = build_database(root, database)
        assert report["counts"]["projects"] == 1
        assert report["counts"]["ranking_entries"] == 5
        assert report["issuesBySeverity"]["warning"] >= 4

        with closing(sqlite3.connect(str(database))) as conn:
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            assert conn.execute("SELECT project_id FROM projects").fetchone()[0] == "u_example_main_data_msc"
            assert conn.execute("SELECT COUNT(*) FROM projects WHERE project_id = 'legacy_only'").fetchone()[0] == 0

        generated = root / "generated"
        frontend = root / "frontend" / "public" / "data"
        manifest = export_database(root, database, generated, frontend)
        assert manifest["sourceOfTruth"] == "normalized/rankingselect.sqlite"
        programs = json.loads((frontend / "programs.json").read_text(encoding="utf-8"))
        assert [program["id"] for program in programs] == ["u_example_main_data_msc"]
        assert programs[0]["deadlines"][0]["date"] == "2027-01-15"
        assert programs[0]["requirements"]["ielts"] == "7.0"
        assert programs[0]["fees"][0]["amount"] == "25000"
        assert (generated / "timelines.json").is_file()
        assert (generated / "validation_issues.json").is_file()
        assert (frontend / "data-manifest.json").is_file()


def test_rebuild_is_deterministic() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        first_root = root / "checkout-a"
        second_root = root / "checkout-b"
        _fixture(first_root)
        _fixture(second_root)
        first = first_root / "normalized" / "rankingselect.sqlite"
        second = second_root / "normalized" / "rankingselect.sqlite"
        build_database(first_root, first)
        build_database(second_root, second)
        assert _sha256(first) == _sha256(second)

        generated_a = first_root / "generated"
        generated_b = second_root / "generated"
        frontend_a = first_root / "frontend-output"
        frontend_b = second_root / "frontend-output"
        export_database(first_root, first, generated_a, frontend_a)
        export_database(second_root, second, generated_b, frontend_b)
        assert _sha256(generated_a / "data-manifest.json") == _sha256(generated_b / "data-manifest.json")
        assert _sha256(frontend_a / "programs.json") == _sha256(frontend_b / "programs.json")


def main() -> None:
    test_build_and_export()
    test_rebuild_is_deterministic()
    print("[data-pipeline-test] passed")


if __name__ == "__main__":
    main()
