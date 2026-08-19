import hashlib
import gzip
import json
import tempfile
import unittest
from pathlib import Path

from scraper.programs.build_browser_recovery_batches_v4 import build_batches


class BrowserRecoveryBatchesV4Test(unittest.TestCase):
    def _fixture(self, root):
        static_raw = root / "homepage.body"
        static_raw.write_bytes(b"challenge")
        static_manifest = root / "homepage.manifest.json"
        static_manifest.write_text(
            json.dumps(
                {
                    "rawFile": str(static_raw),
                    "sha256": hashlib.sha256(b"challenge").hexdigest(),
                    "headers": {"Server": "cloudflare", "CF-RAY": "test"},
                }
            ),
            encoding="utf-8",
        )

        program_raw = root / "programs" / "one.html.gz"
        program_raw.parent.mkdir()
        program_body = b"program"
        program_raw.write_bytes(gzip.compress(program_body))
        program_sha = hashlib.sha256(program_body).hexdigest()
        crawler_manifest = root / "manifest.json"
        crawler_manifest.write_text(
            json.dumps(
                {
                    "pages": {
                        "https://program.example.edu/master/one/": {
                            "file": "programs/one.html.gz",
                            "sha256": program_sha,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        main = {
            "items": [
                {
                    "universityId": "u_captured",
                    "name": "Captured University",
                    "country": "Australia",
                    "url": "https://captured.example.edu/",
                    "kind": "official-homepage",
                    "status": "captured",
                    "browserSha256": "b" * 64,
                },
                {
                    "universityId": "u_home",
                    "name": "Home University",
                    "country": "Canada",
                    "url": "https://home.example.edu/",
                    "kind": "official-homepage",
                    "status": "pending",
                    "sourceRawFile": str(static_raw),
                    "sourceManifestFile": str(static_manifest),
                },
                {
                    "universityId": "u_program",
                    "name": "Program University",
                    "country": "Canada",
                    "url": "https://program.example.edu/master/one",
                    "kind": "program",
                    "status": "pending",
                    "sourceManifestFile": str(crawler_manifest),
                },
            ]
        }
        recovered = [
            {
                "universityId": "u_home_alias",
                "name": "Home University Alias",
                "country": "Canada",
                "indexUrl": "https://home.example.edu",
                "officialDomains": ["home.example.edu"],
                "status": "pending",
                "provenance": {
                    "rorRawFile": "ror.json.gz",
                    "rorRawManifestFile": "ror.manifest.json",
                    "rorRawSha256": "c" * 64,
                },
            }
        ]
        triage = {
            "items": [
                {
                    "canonicalId": "u_triage",
                    "name": "Triage University",
                    "country": "Japan",
                    "category": "blocked",
                    "reasonCodes": ["live_page_http_error"],
                    "livePage": {"requestedUrl": "https://triage.example.jp/"},
                    "rorIdentity": {"selectedDomains": ["triage.example.jp"]},
                    "rorRawEvidence": {
                        "references": [
                            {
                                "rawFile": "ror/triage.json.gz",
                                "manifestFile": "ror/triage.manifest.json",
                                "actualSha256": "d" * 64,
                                "hashVerified": True,
                            }
                        ]
                    },
                    "statusGuardrail": "no-status-change",
                },
                {
                    "canonicalId": "u_auto",
                    "category": "auto-recoverable",
                    "livePage": {"requestedUrl": "https://auto.example.edu/"},
                },
            ]
        }
        return main, recovered, triage

    def test_merge_pending_filter_priority_and_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main, recovered, triage = self._fixture(root)
            result = build_batches(
                main,
                recovered,
                triage,
                main_file=root / "main.json",
                recovered_file=root / "recovered.json",
                triage_file=root / "triage.json",
                max_shard_size=2,
                generated_at="2026-08-14T00:00:00+00:00",
            )

            self.assertEqual(result["summary"]["inputRecords"], 5)
            self.assertEqual(result["summary"]["uniqueTasks"], 4)
            self.assertEqual(result["summary"]["duplicateRecordsMerged"], 1)
            self.assertEqual(result["summary"]["pendingTasks"], 3)
            self.assertEqual(result["summary"]["excludedStatusCounts"], {"captured": 1})
            self.assertEqual(result["policy"]["captcha"]["onDetection"], "stop")
            self.assertTrue(result["policy"]["captcha"]["bypassProhibited"])
            self.assertTrue(result["policy"]["pendingOnly"])

            all_items = [item for batch in result["batches"] for item in batch["items"]]
            self.assertTrue(all(item["status"] == "pending" for item in all_items))
            self.assertEqual(result["batches"][0]["kind"], "official-homepage")
            self.assertEqual(result["batches"][-1]["kind"], "program")
            home = next(item for item in all_items if item["host"] == "home.example.edu")
            self.assertEqual(home["platform"], "cloudflare")
            self.assertEqual(home["mergedRecordCount"], 2)
            self.assertEqual(home["sourceSha256"], hashlib.sha256(b"challenge").hexdigest())
            self.assertEqual(len(home["queueReferences"]), 2)
            program = next(item for item in all_items if item["kind"] == "program")
            self.assertEqual(program["sourceSha256"], hashlib.sha256(b"program").hexdigest())
            self.assertEqual(program["sourceManifestFile"], str((root / "manifest.json").resolve()))
            self.assertTrue(program["sourceRawFile"].endswith("programs\\one.html.gz") or program["sourceRawFile"].endswith("programs/one.html.gz"))
            triage_item = next(item for item in all_items if item["host"] == "triage.example.jp")
            self.assertEqual(triage_item["sourceSha256"], "d" * 64)

    def test_bounded_deterministic_shards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = {
                "items": [
                    {
                        "universityId": "u_%d" % index,
                        "name": "University %d" % index,
                        "country": "United States",
                        "url": "https://shared.example.edu/program/%d" % index,
                        "kind": "program",
                        "status": "pending",
                    }
                    for index in range(7)
                ]
            }
            first = build_batches(
                main,
                [],
                {"items": []},
                main_file=root / "main.json",
                recovered_file=root / "recovered.json",
                triage_file=root / "triage.json",
                max_shard_size=3,
                generated_at="fixed",
            )
            second = build_batches(
                main,
                [],
                {"items": []},
                main_file=root / "main.json",
                recovered_file=root / "recovered.json",
                triage_file=root / "triage.json",
                max_shard_size=3,
                generated_at="fixed",
            )
            self.assertEqual(first, second)
            self.assertEqual(first["summary"]["shards"], 3)
            self.assertEqual(first["summary"]["largestShard"], 3)
            self.assertTrue(all(batch["itemCount"] <= 3 for batch in first["batches"]))
            self.assertEqual(
                [batch["shardNumber"] for batch in first["batches"]], [1, 2, 3]
            )

    def test_captcha_duplicate_stops_pending_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            main = {
                "items": [
                    {
                        "universityId": "u_one",
                        "url": "https://captcha.example.edu/",
                        "kind": "official-homepage",
                        "status": "pending",
                    },
                    {
                        "universityId": "u_two",
                        "url": "https://captcha.example.edu",
                        "kind": "official-homepage",
                        "status": "blocked",
                        "captchaDetected": True,
                        "browserSha256": "e" * 64,
                    },
                ]
            }
            result = build_batches(
                main,
                [],
                {"items": []},
                main_file=root / "main.json",
                recovered_file=root / "recovered.json",
                triage_file=root / "triage.json",
            )
            self.assertEqual(result["summary"]["pendingTasks"], 0)
            self.assertEqual(result["summary"]["excludedStatusCounts"], {"blocked": 1})
            self.assertTrue(result["excludedItems"][0]["captchaDetected"])

    def test_rejects_invalid_shard_size(self):
        with self.assertRaisesRegex(ValueError, "at least 1"):
            build_batches({}, [], {}, max_shard_size=0)


def test():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BrowserRecoveryBatchesV4Test)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("browser recovery batch tests failed")


if __name__ == "__main__":
    test()
