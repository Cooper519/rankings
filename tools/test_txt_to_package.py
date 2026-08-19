from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.txt_to_package import PackageError, build_package, parse_txt, write_package


SAMPLE = """[manifest]
schema_version = 1
package_version = 2026.08.19.1
university_id = u_example_university
name = Example University
country = Netherlands
updated_at = 2026-08-19

[source src_001]
url = https://example.edu/admissions
source_type = official_web
retrieved_at = 2026-08-19T00:00:00Z

[project u_example_university_main_cs_msc]
campus_id = main
normalized_program_code = cs_msc
name = MSc Computer Science
official_url = https://example.edu/program

[cycle u_example_university_main_cs_msc 27fall]
academic_year = 2027
entry_term = fall
status = current

[timeline u_example_university_main_cs_msc 27fall deadline_1]
event = deadline
date_type = exact
date = 2026-12-15
applicant_group = non_eu
source_id = src_001

[requirements u_example_university_main_cs_msc 27fall]
language_status = required
language_tests = IELTS:7.0; TOEFL iBT:100
gre_status = unknown
gmat_status = not_required
academic_status = required
source_id = src_001

[fee u_example_university_main_cs_msc 27fall tuition_1]
type = tuition
amount = 25300
currency = EUR
period = per_year
applicant_group = non_eu
source_id = src_001
"""


def parse_txt_from_text(text: str):
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as handle:
        path = Path(handle.name)
    try:
        path.write_text(text, encoding="utf-8")
        return parse_txt(path)
    finally:
        path.unlink(missing_ok=True)


class TxtToPackageTests(unittest.TestCase):
    def test_build_and_write_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = root / "example.txt"
            output = root / "u_example_university"
            input_path.write_text(SAMPLE, encoding="utf-8")
            package = build_package(parse_txt(input_path), input_path.name)
            write_package(package, input_path, output)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            projects = json.loads((output / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["university_id"], "u_example_university")
            self.assertNotIn("converted_at", manifest)
            self.assertEqual(projects[0]["admission_cycles"][0]["cycle_id"], "27fall")
            self.assertEqual(projects[0]["admission_cycles"][0]["fees"][0]["amount"], "25300")
            self.assertTrue((output / "raw" / "example.txt").exists())
            self.assertEqual(json.loads((output / "reviews.json").read_text(encoding="utf-8")), [])

    def test_rejects_invalid_fee_amount(self) -> None:
        bad = SAMPLE.replace("amount = 25300", "amount = varies")
        with self.assertRaises(PackageError):
            build_package(parse_txt_from_text(bad), "bad.txt")

    def test_rejects_unknown_source(self) -> None:
        bad = SAMPLE.replace("source_id = src_001", "source_id = src_missing", 1)
        with self.assertRaises(PackageError):
            build_package(parse_txt_from_text(bad), "bad.txt")

    def test_rejects_unknown_section(self) -> None:
        bad = SAMPLE.replace("[manifest]", "[unsupported]")
        with self.assertRaises(PackageError):
            parse_txt_from_text(bad)

    def test_rejects_duplicate_fee_id(self) -> None:
        duplicate = SAMPLE + """
[fee u_example_university_main_cs_msc 27fall tuition_1]
type = registration
amount = unknown
currency = EUR
period = per_year
applicant_group = non_eu
source_id = src_001
"""
        with self.assertRaises(PackageError):
            build_package(parse_txt_from_text(duplicate), "bad.txt")

    def test_rejects_project_id_outside_contract(self) -> None:
        bad = SAMPLE.replace(
            "[project u_example_university_main_cs_msc]",
            "[project u_example_university_main_computing]",
        )
        with self.assertRaises(PackageError):
            build_package(parse_txt_from_text(bad), "bad.txt")

    def test_rejects_cycle_id_that_does_not_match_year(self) -> None:
        bad = SAMPLE.replace("academic_year = 2027", "academic_year = 2028")
        with self.assertRaises(PackageError):
            build_package(parse_txt_from_text(bad), "bad.txt")

    def test_records_manual_source_decision(self) -> None:
        sample = SAMPLE + """
[source src_002]
url = https://example.edu/fees
source_type = official_web
retrieved_at = 2026-08-19T00:00:00Z

[review review_tuition]
entity_type = fee
entity_id = u_example_university_main_cs_msc/27fall/tuition_1
field_name = amount
selected_source_id = src_002
rejected_source_ids = src_001
decision = The fees page is specific to the 27fall cycle.
reviewed_by = maintainer
reviewed_at = 2026-08-19T12:00:00Z
"""
        package = build_package(parse_txt_from_text(sample), "review.txt")
        self.assertEqual(package["reviews"][0]["selected_source_id"], "src_002")

    def test_rejects_invalid_calendar_date(self) -> None:
        bad = SAMPLE.replace("date = 2026-12-15", "date = 2026-13-45")
        with self.assertRaises(PackageError):
            build_package(parse_txt_from_text(bad), "bad.txt")


if __name__ == "__main__":
    unittest.main()
