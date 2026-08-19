import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.audit_goal_progress_v4 import build_audit, markdown_report


def write_manifest(root, uid, programs, evidence=None):
    directory = root / uid
    directory.mkdir(parents=True, exist_ok=True)
    pages = {}
    candidates = {}
    for index, (url, item) in enumerate(programs.items()):
        body = item.get("body", "")
        payload = ("<html><body>%s</body></html>" % body).encode("utf-8")
        relative = "pages/program-%d.html.gz" % index
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(payload))
        pages[url] = {
            "kind": "program", "status": item["status"], "file": relative,
            "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        }
        candidates[url] = {"url": url}
    for index, (url, item) in enumerate((evidence or {}).items()):
        payload = ("<html><body>%s</body></html>" % item["body"]).encode("utf-8")
        relative = "pages/evidence-%d.html.gz" % index
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(payload))
        pages[url] = {
            "kind": "evidence", "status": "captured", "file": relative,
            "sourceUrl": item.get("sourceUrl"),
            "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        }
    (directory / "manifest.json").write_text(json.dumps({
        "schemaVersion": 1,
        "universityId": uid,
        "universityName": uid,
        "discovery": {"programCandidates": candidates, "visited": {}},
        "pages": pages,
    }), encoding="utf-8")


def test():
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        old_raw = root / "old"
        new_raw = root / "new"
        old_raw.mkdir()
        new_raw.mkdir()
        p1 = "https://alpha.example/master/data"
        p2 = "https://beta.example/master/physics"
        write_manifest(old_raw, "old_alpha", {
            p1: {"status": "captured", "body": "Admission requirements. Application period. Application deadline."},
        })
        write_manifest(new_raw, "u_beta", {
            p2: {"status": "blocked", "body": "Access denied"},
        }, {
            "https://beta.example/admissions/language": {
                "sourceUrl": "https://beta.example/admissions",
                "body": "English language requirement IELTS 7.0.",
            },
        })

        target_audit = {"entities": [
            {"canonicalId": "u_alpha", "name": "Alpha", "country": "A", "rankingSources": ["qs"],
             "sourceUniversityIds": ["u_alpha"], "existingRawTargetIds": ["old_alpha"],
             "rankingAppearances": [{"source": "qs", "universityId": "u_alpha"}]},
            {"canonicalId": "u_beta", "name": "Beta", "country": "B", "rankingSources": ["the"],
             "sourceUniversityIds": ["u_beta"], "existingRawTargetIds": [],
             "rankingAppearances": [{"source": "the", "universityId": "u_beta"}]},
        ]}
        coverage = {"summary": {"categories": {"existing-program-raw": 1, "new-program-raw": 1}}, "entities": [
            {"canonicalId": "u_alpha", "name": "Alpha", "country": "A", "rankingSources": ["qs"], "category": "existing-program-raw"},
            {"canonicalId": "u_beta", "name": "Beta", "country": "B", "rankingSources": ["the"], "category": "new-program-raw"},
        ]}
        queue_raw = root / "blocked.body"
        queue_raw.write_bytes(b"blocked")
        queue_manifest = root / "blocked.manifest.json"
        queue_manifest.write_text(json.dumps({"sha256": hashlib.sha256(b"blocked").hexdigest()}), encoding="utf-8")
        queue = root / "queue.json"
        queue.write_text(json.dumps({"items": [{
            "universityId": "u_beta", "name": "Beta", "country": "B", "kind": "program",
            "url": p2, "status": "pending", "sourceManifestFile": str(queue_manifest),
            "sourceRawFile": str(queue_raw),
        }]}), encoding="utf-8")

        recovered_queue = root / "recovered.json"
        recovered_queue.write_text(json.dumps([{
            "universityId": "u_alpha", "name": "Alpha", "country": "A",
            "indexUrl": "https://alpha.example", "browserAction": "verify-homepage",
            "status": "pending", "provenance": {"officialHomepageRaw": None},
        }]), encoding="utf-8")

        audit = build_audit(target_audit, coverage, old_raw, new_raw, [queue, recovered_queue], hash_sample_size=10)
        assert audit["coverage"]["rawEntities"]["observed"]["programRawEntities"] == 2
        assert audit["coverage"]["candidateStatus"]["combined"]["captured"] == 1
        assert audit["coverage"]["candidateStatus"]["combined"]["blocked"] == 1
        evidence = audit["coverage"]["applicationEvidence"]
        assert evidence["programUniverse"]["programs"] == 2
        assert evidence["modes"]["direct"]["requirements"]["programLevel"]["covered"] == 1
        assert evidence["modes"]["direct"]["essentialBundle"]["programLevel"]["covered"] == 1
        assert evidence["modes"]["includingShared"]["language"]["programLevel"]["covered"] == 1
        assert audit["integrity"]["existingRaw"]["summary"]["hashSamplesMismatched"] == 0
        assert audit["integrity"]["newRaw"]["summary"]["hashSamplesMismatched"] == 0
        assert audit["integrity"]["browserRecoveryQueue"]["sourceHashCheck"] == {
            "checked": 1, "matched": 1, "mismatched": 0,
        }
        queue_summary = audit["integrity"]["browserRecoveryQueue"]["summary"]
        assert queue_summary["kind:official-homepage"] == 1
        assert queue_summary["tasksWithoutSourceManifest"] == 1
        assert "Application Evidence Coverage" in markdown_report(audit)
    print("[goal-progress-audit-v4-test] passed")


if __name__ == "__main__":
    test()
