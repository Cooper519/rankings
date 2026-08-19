from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scraper.programs.build_engineering_priority_queue_v4 import (
    build_export,
    surface_signal,
    url_lines,
)


def run() -> None:
    assert surface_signal(("https://example.edu/m-tech/",))[1] == "engineering"
    assert surface_signal(("Master of Technology programme directory",))[1] == "engineering"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        coverage = {"entities": [
            {"canonicalId": "u_top", "name": "Top University", "sourceUniversityIds": ["u_top_alias"]},
            {"canonicalId": "u_deferred", "name": "Deferred University", "sourceUniversityIds": ["u_deferred_alias"]},
        ]}
        audit_entities = []
        rows_by_source = {}
        for source in ("qs", "the", "arwu", "usnews"):
            rows_by_source[source] = [
                {"universityId": "u_top_alias", "rank": 1, "year": 2025},
                {"universityId": "u_other", "rank": 2, "year": 2025},
                {"universityId": "u_deferred_alias", "rank": 2, "year": 2025},
            ]
        audit = {"entities": [
            {"canonicalId": "u_top", "sourceUniversityIds": ["u_top_alias"]},
            {"canonicalId": "u_deferred", "sourceUniversityIds": ["u_deferred_alias"]},
        ]}
        top_manifest = {
            "universityId": "u_top_alias",
            "discovery": {"programCandidates": {
                "https://top.example/master/computer-science": {
                    "text": "MSc Computer Science",
                    "sourceUrl": "https://top.example/masters",
                },
                "https://top.example/master/history": {
                    "text": "MA History",
                    "sourceUrl": "https://top.example/masters",
                },
                "https://top.example/master/ai?major=42&utm_source=test&gclid=abc": {
                    "text": "MSc Artificial Intelligence",
                },
                "https://top.example/master/robotics/&utm_source=story&utm_campaign=test": {
                    "text": "MSc Robotics",
                },
                "https://top.example/": {
                    "text": "MSc Engineering programmes",
                },
            }},
            "pages": {},
        }
        deferred_manifest = {
            "universityId": "u_deferred_alias",
            "discovery": {"programCandidates": {
                "https://deferred.example/master/robotics": {"text": "MSc Robotics"},
            }},
            "pages": {},
        }
        recovered_manifest = {
            "universityId": "u_top_alias",
            "discovery": {
                "programCandidates": {},
                "visited": {
                    "https://top.example/postgraduate/master-of-science-in-robotics": {
                        "status": "captured",
                        "kind": "category",
                        "eligibleAsProgramEvidence": True,
                        "documentTitle": "Master of Science in Robotics",
                        "sourceUrl": "https://top.example/postgraduate",
                    },
                    "https://top.example/faculty/engineering": {
                        "status": "captured",
                        "kind": "catalog",
                        "eligibleAsProgramEvidence": True,
                        "documentTitle": "Faculty of Engineering",
                    },
                    "https://top.example/Admission/Graduate.htm": {
                        "status": "captured",
                        "kind": "catalog",
                        "eligibleAsProgramEvidence": True,
                        "documentTitle": "Graduate programmes",
                    },
                    "https://top.example/graduate-studies": {
                        "status": "captured",
                        "kind": "category",
                        "eligibleAsProgramEvidence": True,
                        "documentTitle": "Centre of Graduate Studies",
                    },
                },
            },
            "pages": {},
        }
        top_path = root / "top" / "manifest.json"
        deferred_path = root / "deferred" / "manifest.json"
        top_path.parent.mkdir()
        deferred_path.parent.mkdir()
        top_path.write_text(json.dumps(top_manifest), encoding="utf-8")
        deferred_path.write_text(json.dumps(deferred_manifest), encoding="utf-8")
        raw_before = {
            top_path: top_path.read_bytes(),
            deferred_path: deferred_path.read_bytes(),
        }
        manifests = [
            ("test", top_path, top_manifest),
            ("test", deferred_path, deferred_manifest),
            ("_top350_engineering_url_recovery_batch_01_raw", top_path, recovered_manifest),
        ]
        result = build_export(
            coverage,
            audit,
            rows_by_source,
            manifests,
            row_limit=2,
            generated_at="fixed",
        )
        assert result["generatedAt"] == "fixed"
        assert result["summary"]["urlOnlyExportCount"] == 5
        assert result["summary"]["top350NoSignalCount"] == 1
        assert result["summary"]["deferredCandidateCount"] == 1
        assert result["summary"]["genericRootUrlCount"] == 1
        assert result["feature2"]["rankingRowSummary"]["selectedRowsBySource"] == {
            "qs": 2, "the": 2, "arwu": 2, "usnews": 2,
        }
        item = next(
            row for row in result["items"]
            if row["url"] == "https://top.example/master/computer-science"
        )
        assert set(item) == {"url", "sourceUrl", "canonicalId", "universityName", "top350Selections"}
        assert item["url"] == "https://top.example/master/computer-science"
        assert item["sourceUrl"] == "https://top.example/masters"
        assert len(item["top350Selections"]) == 4
        assert all(selection["rowIndex"] == 0 for selection in item["top350Selections"])
        assert all(selection["selectionBasis"] == "first-2-rows" for selection in item["top350Selections"])
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

        output_keys = all_keys(result)
        for forbidden in ("requirements", "deadline", "material", "documents", "language", "rawpath", "sha256"):
            assert forbidden not in output_keys
        exported_urls = url_lines(result)
        assert set(exported_urls) == {
            "https://top.example/master/computer-science",
            "https://top.example/master/ai?major=42",
            "https://top.example/master/robotics",
            "https://top.example/postgraduate/master-of-science-in-robotics",
            "https://top.example/Admission/Graduate.htm",
        }
        duplicate = {"items": result["items"] + result["items"]}
        assert url_lines(duplicate) == exported_urls
        again = build_export(coverage, audit, rows_by_source, list(reversed(manifests)), row_limit=2, generated_at="fixed")
        assert json.dumps(result, sort_keys=True) == json.dumps(again, sort_keys=True)
        assert {path: path.read_bytes() for path in raw_before} == raw_before

        china_coverage = {"entities": [{
            "canonicalId": "u_cn",
            "name": "China University",
            "country": "China",
            "sourceUniversityIds": ["u_cn_alias"],
        }]}
        china_audit = {"entities": [{
            "canonicalId": "u_cn",
            "country": "China",
            "sourceUniversityIds": ["u_cn_alias"],
        }]}
        china_rows = {
            source: [{"universityId": "u_cn_alias", "rank": 1}]
            for source in ("qs", "the", "arwu", "usnews")
        }
        china_manifest = {
            "universityId": "u_cn_alias",
            "discovery": {"programCandidates": {
                "https://china.example/msc-computer-science": {
                    "text": "MSc Computer Science"
                }
            }},
            "pages": {},
        }
        china_result = build_export(
            china_coverage,
            china_audit,
            china_rows,
            [("test", top_path, china_manifest)],
            row_limit=1,
            generated_at="fixed",
        )
        assert china_result["items"] == []
        assert china_result["summary"]["excludedMainlandChinaCandidateCount"] == 1
        assert china_result["summary"]["excludedMainlandChinaEntityCount"] == 1
    print("[engineering-url-only-export-test] passed")


if __name__ == "__main__":
    run()
