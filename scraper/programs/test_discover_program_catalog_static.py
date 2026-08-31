import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.discover_program_catalog_static import (
    build_discovery_batch,
    discover_source,
    is_official_url,
    main as run_discovery,
    normalize_anchor_url,
    score_catalog_link,
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def test():
    official = ["department.example.edu"]
    assert is_official_url("https://department.example.edu/study", official)
    assert is_official_url("https://catalog.department.example.edu/study", official)
    assert not is_official_url("https://example.edu/study", official)  # parent promotion
    assert not is_official_url("https://department.example.edu.attacker.test/study", official)
    assert normalize_anchor_url("../masters/?utm_source=test#top", "https://department.example.edu/en/home/") == (
        "https://department.example.edu/en/masters"
    )
    assert not normalize_anchor_url("mailto:study@department.example.edu", "https://department.example.edu/")

    accepted_languages = [
        ("https://department.example.edu/de/masterstudiengaenge", "Masterstudieng\u00e4nge"),
        ("https://department.example.edu/es/maestrias", "Programas de maestr\u00eda"),
        ("https://department.example.edu/fr/formations", "Catalogue des formations - cycle master"),
        ("https://department.example.edu/it/lauree-magistrali", "Lauree magistrali"),
        ("https://department.example.edu/nl/masteropleidingen", "Masteropleidingen"),
        ("https://department.example.edu/zh/graduate", "\u7855\u58eb\u9879\u76ee"),
    ]
    for url, text in accepted_languages:
        result = score_catalog_link(url, {"text": text, "title": "", "ariaLabel": ""})
        assert result["accepted"], (url, result)

    false_positives = [
        ("https://department.example.edu/news/master-open-day", "Master open day"),
        ("https://department.example.edu/admissions/graduate", "Graduate admissions"),
        ("https://department.example.edu/research/master-projects", "Master research projects"),
        ("https://department.example.edu/courses", "Short courses"),
        ("https://department.example.edu/catalog", "Course catalog"),  # no master's level
        ("https://department.example.edu/programs/data-science", "MSc Data Science"),  # detail, not directory
        ("https://department.example.edu/postgrados/doctorados", "Programas de Doctorado"),
        ("https://department.example.edu/postgrados/especialidades", "Cursos de especializacion"),
        ("https://department.example.edu/calendar", "Postgraduate courses academic calendar"),
        ("https://department.example.edu/study/pre-masters", "Foundation and pre-master's programmes"),
        ("https://department.example.edu/graduate/how-to-apply", "How to apply to graduate programs"),
        ("https://department.example.edu/story", "Graduate programs " + "research summary " * 30),
    ]
    for url, text in false_positives:
        result = score_catalog_link(url, {"text": text, "title": "", "ariaLabel": ""})
        assert not result["accepted"], (url, result)

    html = b"""<!doctype html><html><body>
      <nav>
        <input type="hidden" name="context" value="graduate">
        <a href="../study/masters/?utm_source=nav#top"><span>Master's programmes</span></a>
        <a href="https://catalog.department.example.edu/es/maestrias">Programas de maestria</a>
        <a href="https://example.edu/graduate/programs">Graduate programs on parent</a>
        <a href="https://evil.test/postgraduate/programmes">Postgraduate programmes elsewhere</a>
        <a href="/news/master-open-day">Master open day</a>
        <a href="/admissions/graduate">Graduate admissions</a>
        <a href="/programs/data-science">MSc Data Science</a>
        <a href="/postgraduate/programmes" style="display:none">Hidden postgraduate programmes</a>
        <a href="/masters-guide.pdf">Master's programme guide PDF</a>
      </nav>
    </body></html>"""
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        raw_file = root / "homepage.html.gz"
        raw_file.write_bytes(gzip.compress(html))
        source = {
            "pageUrl": "https://department.example.edu/en/home/",
            "rawFile": str(raw_file),
            "rawManifestFile": str(root / "homepage.manifest.json"),
            "sha256": sha256(html),
            "contentType": "text/html; charset=utf-8",
            "captureMethod": "test-fixture",
        }
        discovered = discover_source(source, official)
        urls = [item["url"] for item in discovered["candidates"]]
        assert urls == [
            "https://department.example.edu/en/study/masters",
            "https://catalog.department.example.edu/es/maestrias",
        ]
        assert discovered["source"]["computedSha256"] == sha256(html)
        assert all(item["sourceRawSha256"] == sha256(html) for item in discovered["candidates"])
        assert all(item["href"] in html.decode("utf-8") for item in discovered["candidates"])

        university_id = "u_example"
        coverage = {
            "entities": [{
                "canonicalId": university_id,
                "category": "verified-zero-candidates",
                "newRaw": {"manifestFile": str(root / university_id / "missing-manifest.json")},
            }, {
                "canonicalId": "u_not_selected",
                "category": "new-program-raw",
            }],
        }
        target = {
            "universityId": university_id,
            "name": "Example University",
            "officialDomains": official,
            "indexUrl": "https://department.example.edu/en/home/",
            "catalogPages": ["https://department.example.edu/existing/masters"],
            "officialVerificationStatus": "verified",
            "provenance": {"officialHomepageRaw": {
                "rawFile": str(raw_file),
                "manifestFile": str(root / "homepage.manifest.json"),
                "sha256": sha256(html),
                "finalUrl": "https://department.example.edu/en/home/",
                "headers": {"Content-Type": "text/html; charset=utf-8"},
            }},
        }
        batch, summary = build_discovery_batch(coverage, [target], root)
        assert len(batch) == 1
        assert batch[0]["catalogPages"] == [
            "https://department.example.edu/existing/masters",
            "https://department.example.edu/en/study/masters",
            "https://catalog.department.example.edu/es/maestrias",
        ]
        evidence = batch[0]["catalogDiscovery"]
        assert evidence["networkRequested"] is False
        assert evidence["guessedUrlsAllowed"] is False
        assert evidence["officialParentDomainsAllowed"] is False
        assert evidence["status"] == "candidates-found"
        assert summary["selectedTargets"] == 1
        assert summary["catalogCandidates"] == 2

        coverage_file = root / "coverage.json"
        targets_file = root / "targets.json"
        output_file = root / "batch.json"
        coverage_file.write_text(json.dumps(coverage), encoding="utf-8")
        targets_file.write_text(json.dumps([target]), encoding="utf-8")
        run_discovery([
            "--coverage", str(coverage_file),
            "--targets", str(targets_file),
            "--raw-root", str(root),
            "--output", str(output_file),
        ])
        written = json.loads(output_file.read_text(encoding="utf-8"))
        assert written[0]["catalogDiscovery"]["candidates"][0]["href"] == "../study/masters/?utm_source=nav#top"

        bad_source = dict(source, sha256="0" * 64)
        rejected = discover_source(bad_source, official)
        assert rejected["source"]["status"] == "sha256-mismatch"
        assert rejected["candidates"] == []


def main():
    test()


if __name__ == "__main__":
    main()
    print("discover_program_catalog_static tests passed")
