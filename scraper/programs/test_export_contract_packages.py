from __future__ import annotations

from scraper.programs.export_contract_packages import build_project, project_name, validate_package


def test_project_name_rejects_directory_and_accepts_degree() -> None:
    assert not project_name("https://example.edu/masters", {"text": "Master programmes"})
    assert project_name(
        "https://example.edu/masters/data-science",
        {"text": "MSc Data Science"},
    ) == "MSc Data Science"


def test_unknown_cycle_fields_follow_contract() -> None:
    project = build_project("u_example", "MSc Data Science", "https://example.edu/msc", "src_1", set())
    package = {
        "manifest": {"university_id": "u_example"},
        "sources": [{"source_id": "src_1"}],
        "projects": [project],
    }
    validate_package(package)
    cycle = project["admission_cycles"][0]
    assert cycle["timelines"][0]["date"] is None
    assert cycle["requirements"]["language"]["status"] == "unknown"
    assert cycle["fees"][0]["amount"] == "unknown"


def main() -> None:
    test_project_name_rejects_directory_and_accepts_degree()
    test_unknown_cycle_fields_follow_contract()
    print("[contract-export-test] passed")


if __name__ == "__main__":
    main()
