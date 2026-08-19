import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.audit_top500_raw_corpus import audit
from scraper.programs.scrape_programs_static import safe_id


def test():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        uid = "u_université_test"
        target_dir = root / safe_id(uid)
        target_dir.mkdir()
        (target_dir / "manifest.json").write_text(json.dumps({
            "universityId": uid,
            "status": "raw-partial",
            "discovery": {"status": "complete", "programCandidates": {"https://example.edu/master": {}}},
            "pages": {"https://example.edu/master": {"kind": "program", "status": "captured"}},
        }), encoding="utf-8")
        result = audit([{"universityId": uid, "name": "Test"}], root)
        assert result["summary"]["manifests"] == 1
        assert result["summary"].get("missingManifests", 0) == 0
        assert result["summary"]["program_captured"] == 1
    print("[audit-top500-raw-corpus-test] passed")


if __name__ == "__main__":
    test()
