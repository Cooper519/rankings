import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.audit_goal_entity_coverage import build
from scraper.programs.scrape_programs_static import safe_id


def write_manifest(root, identifier, candidates):
    path = root / safe_id(identifier)
    path.mkdir(parents=True)
    (path / "manifest.json").write_text(json.dumps({
        "status": "raw-complete",
        "discovery": {"programCandidates": {str(index): {} for index in range(candidates)}},
        "pages": {},
    }), encoding="utf-8")


def test():
    with TemporaryDirectory() as directory:
        root = Path(directory); old = root / "old"; new = root / "new"; extra = root / "extra"
        write_manifest(old, "old_a", 2); write_manifest(new, "b", 0); write_manifest(new, "c", 0)
        write_manifest(extra, "b", 1)
        audit = {"entities": [
            {"canonicalId": "a", "rankingSources": ["qs"], "existingRawTargetIds": ["old_a"], "coveredByExistingRawTarget": True},
            {"canonicalId": "b", "rankingSources": ["the"], "existingRawTargetIds": []},
            {"canonicalId": "c", "rankingSources": ["arwu"], "existingRawTargetIds": []},
            {"canonicalId": "d", "rankingSources": ["usnews"], "existingRawTargetIds": []},
        ]}
        result = build(
            audit, old, new, {"d": {"verificationStatus": "blocked"}}, [extra]
        )
        assert result["summary"]["categories"] == {
            "existing-program-raw": 1, "new-program-raw": 1,
            "verified-zero-candidates": 1, "official-blocked": 1,
        }
        b = next(item for item in result["entities"] if item["canonicalId"] == "b")
        assert b["newRaw"]["programCandidates"] == 1
        assert len(b["newRawSources"]) == 2
    print("[goal-entity-coverage-test] passed")


if __name__ == "__main__":
    test()
