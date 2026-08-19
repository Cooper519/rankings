from __future__ import annotations

import json
import tempfile
from pathlib import Path

from scraper.programs.browser_recovery_raw import verify_browser_capture
from scraper.programs.import_browser_program_handoff_v1 import import_handoff


def run() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        first = root / "first.html"
        second = root / "second.html"
        third = root / "third.html"
        first.write_text("<title>MSc Robotics</title>", encoding="utf-8")
        second.write_text("<title>MSc AI</title><div class='g-recaptcha'></div>", encoding="utf-8")
        third.write_text("<title>MSc Data Science</title>", encoding="utf-8")
        handoff = {
            "universityId": "u_test",
            "universityName": "Test University",
            "officialDomains": ["example.edu"],
            "pages": [
                {
                    "requestedUrl": "https://example.edu/robotics",
                    "finalUrl": "https://example.edu/robotics",
                    "title": "MSc Robotics",
                    "candidateText": "Master of Science in Robotics",
                    "domFile": str(first),
                    "sourceUrl": "https://example.edu/masters",
                },
                {
                    "requestedUrl": "https://example.edu/ai",
                    "finalUrl": "https://example.edu/challenge",
                    "title": "MSc AI",
                    "domFile": str(second),
                },
                {
                    "requestedUrl": "https://example.edu/data-science",
                    "finalUrl": "https://example.edu/data-science",
                    "title": "MSc Data Science",
                    "domFile": str(third),
                },
            ],
        }
        output = root / "raw"
        result = import_handoff(handoff, output, generated_at="fixed")
        assert result["status"] == "raw-partial"
        assert result["counts"] == {
            "requested": 3,
            "processed": 2,
            "programCandidates": 1,
            "statusCounts": {"blocked": 1, "captured": 1},
        }
        assert result["discovery"]["stoppedReason"] == "captcha-detected"
        assert list(result["discovery"]["programCandidates"]) == [
            "https://example.edu/robotics"
        ]
        assert result["discovery"]["programCandidates"][
            "https://example.edu/robotics"
        ]["text"] == "Master of Science in Robotics"
        manifest_file = output / "u_test" / "manifest.json"
        stored = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert stored == result
        for page in result["pages"].values():
            verified = verify_browser_capture(page["browserManifestFile"])
            assert verified["sha256"] == page["sha256"]
        assert not list(output.rglob("*.tmp-*"))
    print("[import-browser-program-handoff-v1-test] passed")


if __name__ == "__main__":
    run()
