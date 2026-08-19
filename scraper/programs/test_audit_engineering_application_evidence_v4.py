import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.audit_engineering_application_evidence_v4 import (
    build_audit,
    ranking_info,
)


def write_page(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(("<html><body>" + body + "</body></html>").encode("utf-8")))


def write_manifest(root: Path, uid: str, urls) -> None:
    directory = root / uid
    pages = {}
    candidates = {}
    for index, (url, page_status) in enumerate(urls):
        relative = "pages/program-%d.html.gz" % index
        if page_status == "captured":
            write_page(directory, relative, "Admission requirements. Application deadline. Required documents. IELTS language requirement.")
        pages[url] = {"kind": "program", "status": page_status, "file": relative, "sourceUrl": "https://alpha.edu/catalog"}
        candidates[url] = {"url": url, "kind": "program", "sourceUrl": "https://alpha.edu/catalog", "text": "Master programme"}
    manifest = {"universityId": uid, "universityName": "Alpha University", "country": "Testland", "discovery": {"programCandidates": candidates}, "pages": pages}
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        corpus_a = root / "a"
        corpus_b = root / "b"
        engineering_url = "https://alpha.edu/masters/mechanical-engineering"
        blocked_url = "https://alpha.edu/masters/electrical-engineering"
        pending_url = "https://alpha.edu/masters/civil-engineering"
        non_engineering_url = "https://alpha.edu/masters/history"
        write_manifest(corpus_a, "u_alpha", [(engineering_url, "captured"), (blocked_url, "blocked"), (pending_url, "pending"), (non_engineering_url, "captured")])
        write_manifest(corpus_b, "u_alpha_alias", [(engineering_url, "captured")])
        china_url = "https://china.example/masters/mechanical-engineering"
        write_manifest(corpus_a, "u_cn", [(china_url, "captured")])
        target = {"entities": [
            {"canonicalId": "u_alpha", "country": "Testland", "sourceUniversityIds": ["u_alpha", "u_alpha_alias"], "rankingAppearances": [{"source": "qs", "rank": 9999}]},
            {"canonicalId": "u_cn", "country": "China", "sourceUniversityIds": ["u_cn"], "rankingAppearances": [{"source": "qs", "rank": 2}]},
            {"canonicalId": "u_deferred", "country": "Testland", "sourceUniversityIds": ["u_deferred"], "rankingAppearances": [{"source": "qs", "rank": 1}]},
        ]}
        rows_by_source = {
            source: [
                {"universityId": "u_alpha", "rank": 9999},
                {"universityId": "u_cn", "rank": 2},
                {"universityId": "u_deferred", "rank": 1},
            ]
            for source in ("qs", "the", "arwu", "usnews")
        }
        app = {"universities": [{"canonicalId": "u_alpha", "programs": [{"url": engineering_url, "coverage": {"requirements": {"covered": True, "sources": [{"url": engineering_url, "inferredShared": False}]}, "applicationWindow": {"covered": True, "sources": [{"url": engineering_url, "inferredShared": False}]}, "documents": {"covered": False}, "language": {"covered": False}}, "deadline": {"covered": True, "sources": [{"url": engineering_url, "inferredShared": False}]}}]}]}
        aliases = root / "aliases.json"
        aliases.write_text(json.dumps({"canonicalById": {"u_alpha_alias": "u_alpha"}}), encoding="utf-8")
        priority = root / "priority.json"
        priority.write_text(json.dumps({"tasks": [{"canonicalId": "u_alpha", "programUrl": engineering_url, "queuePosition": 1}]}), encoding="utf-8")
        audit = build_audit(
            [("a", corpus_a), ("b", corpus_b)],
            target,
            app,
            aliases,
            [priority],
            rows_by_source=rows_by_source,
            row_limit=2,
        )
        assert audit["summary"]["engineeringUniversityCount"] == 1
        assert audit["summary"]["engineeringProgramCount"] == 3
        assert audit["summary"]["statusCounts"] == {"blocked": 1, "captured": 1, "pending": 1}
        assert audit["summary"]["coverage"]["requirements"]["coveredCount"] == 1
        assert audit["summary"]["coverage"]["deadline"]["coveredCount"] == 1
        assert audit["summary"]["coverage"]["documents"]["coveredCount"] == 1
        assert audit["summary"]["sourceUrl"]["completeCount"] == 3
        assert audit["summary"]["priorityMatchedProgramCount"] == 1
        assert audit["summary"]["rankScope"]["top350"]["programCount"] == 3
        assert audit["summary"]["rankScope"]["top350Unknown"]["programCount"] == 0
        assert audit["summary"]["rankScope"]["top351to500Deferred"]["programCount"] == 0
        assert audit["summary"]["excludedMainlandChinaEntityCount"] == 1
        assert audit["rankingScope"]["rankingRowSummary"]["selectedRowsBySource"] == {
            source: 2 for source in ("qs", "the", "arwu", "usnews")
        }
        ranking, _ = ranking_info(target, rows_by_source=rows_by_source, row_limit=2)
        assert ranking["u_alpha"]["rankScope"] == "top350"
        assert ranking["u_deferred"]["rankScope"] == "top351to500Deferred"
        assert "u_cn" not in ranking
        rows = {item["programUrl"]: item for item in audit["universities"][0]["programs"]}
        assert rows[engineering_url]["status"] == "captured"
        assert rows[blocked_url]["status"] == "blocked"
        assert rows[pending_url]["status"] == "pending"
        assert rows[engineering_url]["evidence"]["documents"]["covered"] is True
        assert engineering_url in rows[engineering_url]["evidence"]["documents"]["sourceUrls"]


if __name__ == "__main__":
    test()
    print("[engineering-application-evidence-audit-test] passed")
