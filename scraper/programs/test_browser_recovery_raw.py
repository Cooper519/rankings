import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scraper.programs.browser_recovery_raw import (
    detect_captcha,
    persist_browser_capture,
    update_queue_status,
    verify_browser_capture,
)


class BrowserRecoveryRawTest(unittest.TestCase):
    def test_persists_and_verifies_rendered_dom(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dom = "<!doctype html><title>Master programmes</title><p>Apply now</p>"
            capture = persist_browser_capture(
                root,
                kind="program",
                requested_url="https://example.edu/program",
                final_url="https://example.edu/program/",
                title="Master programmes",
                dom=dom,
                source_static_status=403,
                captured_at="2026-08-14T00:00:00+00:00",
            )

            manifest_path = Path(capture["manifestFile"])
            manifest = verify_browser_capture(manifest_path)
            raw = Path(manifest["rawFile"]).read_bytes()
            self.assertEqual(raw, dom.encode("utf-8"))
            self.assertEqual(manifest["captureType"], "browser-rendered-dom")
            self.assertEqual(manifest["status"], "captured")
            self.assertFalse(manifest["captchaDetected"])
            self.assertEqual(manifest["sourceStaticStatus"], 403)
            self.assertEqual(manifest["bytes"], len(raw))
            self.assertEqual(manifest["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertFalse(list(root.glob("*.tmp-*")))

    def test_captcha_is_detected_and_forces_blocked_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            capture = persist_browser_capture(
                temporary,
                kind="official-homepage",
                requested_url="https://example.edu/",
                final_url="https://example.edu/challenge",
                title="Verify you are human",
                dom='<div class="g-recaptcha"></div>',
                status="captured",
                captcha_detected=False,
            )
            self.assertTrue(detect_captcha("<div>hCaptcha</div>"))
            self.assertTrue(capture["captchaDetected"])
            self.assertEqual(capture["status"], "blocked")

    def test_invisible_recaptcha_badge_is_not_a_challenge_gate(self):
        dom = (
            '<script src="https://www.google.com/recaptcha/api.js"></script>'
            '<div class="grecaptcha-badge" style="visibility: hidden">'
            '<iframe src="https://www.google.com/recaptcha/api2/anchor?size=invisible">'
            '</iframe></div><h1>Master programmes</h1>'
        )
        self.assertFalse(detect_captcha(dom, "Master programmes"))

    def test_hash_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            capture = persist_browser_capture(
                temporary,
                kind="evidence",
                requested_url="https://example.edu/requirements",
                final_url="https://example.edu/requirements",
                title="Requirements",
                dom="<p>Transcript required</p>",
            )
            manifest_path = Path(capture["manifestFile"])
            Path(capture["rawFile"]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "byte count|SHA-256"):
                verify_browser_capture(manifest_path)

    def test_long_university_path_uses_bounded_capture_filename(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = (
                Path(temporary)
                / ("u_" + "long_university_identifier_" * 3)
                / "browser-pages"
            )
            capture = persist_browser_capture(
                output,
                kind="catalog",
                requested_url="https://example.edu/graduate",
                final_url="https://example.edu/graduate",
                title="Graduate catalog",
                dom="<h1>Graduate catalog</h1>",
            )
            manifest = verify_browser_capture(capture["manifestFile"])
            self.assertEqual(len(manifest["sha256"]), 64)
            self.assertIn(manifest["sha256"][:24], Path(manifest["rawFile"]).name)
            self.assertNotIn(manifest["sha256"], Path(manifest["rawFile"]).name)

    def test_queue_update_is_atomic_and_recounts_statuses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "queue.json"
            queue = {
                "schemaVersion": 1,
                "summary": {"tasks": 2, "uniqueKeys": 2},
                "items": [
                    {
                        "universityId": "u_test", "url": "https://example.edu/",
                        "kind": "official-homepage", "status": "pending",
                    },
                    {
                        "universityId": "u_other", "url": "https://other.edu/",
                        "kind": "official-homepage", "status": "pending",
                    },
                ],
            }
            queue_path.write_text(json.dumps(queue), encoding="utf-8")
            capture = persist_browser_capture(
                root / "raw",
                kind="official-homepage",
                requested_url="https://example.edu/",
                final_url="https://example.edu/",
                title="Example University",
                dom="<h1>Example University</h1>",
            )

            updated = update_queue_status(
                queue_path, "u_test", "https://example.edu/", "official-homepage", capture
            )
            stored = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(updated["status"], "captured")
            self.assertEqual(updated["browserSha256"], capture["sha256"])
            self.assertEqual(stored["summary"]["statusCounts"], {"captured": 1, "pending": 1})
            self.assertEqual(stored["summary"]["kindCounts"], {"official-homepage": 2})
            self.assertFalse(list(root.glob("queue.json.tmp-*")))

    def test_queue_rejects_capture_for_different_url(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue_path = root / "queue.json"
            queue_path.write_text(json.dumps({
                "items": [{
                    "universityId": "u_test", "url": "https://example.edu/expected",
                    "kind": "program", "status": "pending",
                }]
            }), encoding="utf-8")
            capture = persist_browser_capture(
                root / "raw", "program", "https://example.edu/other",
                "https://example.edu/other", "Other", "<p>Other</p>",
            )
            with self.assertRaisesRegex(ValueError, "requestedUrl"):
                update_queue_status(
                    queue_path, "u_test", "https://example.edu/expected", "program", capture
                )


def test():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BrowserRecoveryRawTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("browser recovery raw tests failed")


if __name__ == "__main__":
    test()
