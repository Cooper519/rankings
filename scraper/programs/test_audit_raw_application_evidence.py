import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.audit_raw_application_evidence import (
    build_audit,
    detect_signals,
    read_raw_text,
)


def write_gzip(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(text.encode("utf-8")))


def write_manifest(root: Path, uid: str, name: str, programs: dict, evidence: dict) -> None:
    directory = root / uid
    pages = {}
    candidates = {}
    for index, (url, body) in enumerate(programs.items()):
        relative = f"pages/program-{index}.html.gz"
        write_gzip(directory / relative, f"<html><body>{body}</body></html>")
        pages[url] = {"kind": "program", "status": "captured", "file": relative}
        candidates[url] = {"url": url, "kind": "program"}
    for index, (url, item) in enumerate(evidence.items()):
        relative = f"pages/evidence-{index}.html.gz"
        write_gzip(directory / relative, f"<html><body>{item['body']}</body></html>")
        pages[url] = {
            "kind": "evidence", "status": "captured", "file": relative,
            "sourceUrl": item.get("sourceUrl"),
        }
    manifest = {
        "schemaVersion": 1, "universityId": uid, "universityName": name, "country": "Testland",
        "discovery": {"programCandidates": candidates}, "pages": pages,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test() -> None:
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        corpus = root / "corpus"
        aliases = root / "aliases.json"
        aliases.write_text(json.dumps({"canonicalById": {"u_alpha_alias": "u_alpha"}}), encoding="utf-8")

        ignored = root / "ignored"
        write_gzip(ignored / "pages/body.html.gz", (
            "<html><head><title>Application deadline in metadata</title></head><body>"
            "Programme&nbsp;overview<script>Required documents and IELTS score</script></body></html>"
        ))
        assert read_raw_text(ignored, {"status": "captured", "file": "pages/body.html.gz"}) == "Programme overview"
        browser_raw = ignored / "browser-rendered.html"
        browser_raw.write_text(
            "<html><body>Admission requirements. Application deadline. IELTS 7.0.</body></html>",
            encoding="utf-8",
        )
        browser_text = read_raw_text(
            ignored, {"status": "captured", "rawFile": str(browser_raw)}
        )
        assert {"requirements", "applicationWindow", "deadline", "language"} <= detect_signals(browser_text)

        p1 = "https://alpha.edu/master/data-science/"
        p2 = "https://alpha.edu/master/physics"
        p3 = "https://alpha.edu/master/history"
        write_manifest(corpus, "u_alpha", "Alpha University", {
            p1: "Admission requirements: a relevant degree. Application period: January to March.",
            p2: "Master of Physics curriculum.",
        }, {
            "https://alpha.edu/master/physics/documents": {
                "sourceUrl": p2,
                "body": "Required documents include an academic transcript and curriculum vitae.",
            },
            "https://alpha.edu/admissions/language": {
                "sourceUrl": "https://alpha.edu/admissions",
                "body": "English language requirement: IELTS 7.0.",
            },
        })
        write_manifest(corpus, "u_alpha_alias", "Alpha Uni Alias", {
            p3: "Master of History overview.",
        }, {
            "https://alpha.edu/admissions/deadlines": {
                "sourceUrl": "https://alpha.edu/programmes",
                "body": "Application deadline: submit by 15 January.",
            },
        })

        audit = build_audit(corpus, aliases, sample_limit=2)
        assert audit["summary"]["canonicalUniversityCount"] == 1
        university = audit["universities"][0]
        assert university["canonicalId"] == "u_alpha"
        assert university["aliasIds"] == ["u_alpha", "u_alpha_alias"]
        assert university["programCount"] == 3
        assert university["coverage"]["requirements"] == {"coveredCount": 1, "coverageRate": 0.3333}
        assert university["coverage"]["documents"] == {"coveredCount": 1, "coverageRate": 0.3333}
        assert university["coverage"]["language"] == {"coveredCount": 3, "coverageRate": 1.0}
        assert university["coverage"]["applicationWindow"] == {"coveredCount": 3, "coverageRate": 1.0}
        assert university["deadlineGap"]["coveredCount"] == 3
        assert len(university["uncoveredProgramSamples"]["documents"]) == 2

        by_url = {row["url"]: row for row in university["programs"]}
        normalized_p1 = p1.rstrip("/")
        assert "requirements" in by_url[normalized_p1]["ownSignals"]
        assert by_url[p2]["coverage"]["documents"]["sources"][0]["inferredShared"] is False
        assert by_url[p3]["coverage"]["documents"]["covered"] is False
        assert all(source["inferredShared"] for source in by_url[p3]["coverage"]["language"]["sources"])
        assert all(source["inferredShared"] for source in by_url[p2]["deadline"]["sources"])


if __name__ == "__main__":
    test()
    print("[raw-application-evidence-audit-test] passed")
