import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.build_official_identity_triage import (
    ROOT,
    build_report,
    classify,
    render_markdown,
    ror_raw_evidence,
)


def item(identifier, status, reason, name="Example University", country="Exampleland"):
    return {
        "canonicalId": identifier,
        "name": name,
        "country": country,
        "verificationStatus": status,
        "registryResolution": {"selected": {
            "name": "Example University",
            "rorId": "https://ror.org/example",
            "registryDomains": ["example.edu"],
        }},
        "rorOrganization": {
            "id": "https://ror.org/example",
            "names": [
                {"value": "EXU", "types": ["acronym"]},
                {"value": "Example University", "types": ["ror_display"]},
                {"value": "示例大学", "types": ["label"], "lang": "zh"},
            ],
        },
        "verification": {
            "reasonCodes": [reason],
            "evidence": {
                "registryIdentity": {"rorId": "https://ror.org/example"},
                "domainConsistency": {"candidateUrl": "https://www1.example.edu/"},
                "liveOfficialPage": {
                    "status": 200,
                    "finalUrl": "https://www.example.edu/",
                    "title": "Admissions",
                    "titleMatches": False,
                    "bodyMatches": False,
                },
            },
        },
    }


def test_classification():
    relationships = [{
        "id": "rel-system",
        "type": "systemCampus",
        "memberIds": ["u_system", "u_campus"],
        "canonicalId": None,
    }]

    multilingual = item("u_multi", "review", "live_page_identity_mismatch")
    multilingual["verification"]["evidence"]["liveOfficialPage"]["title"] = "示例大学"
    assert classify(multilingual, relationships)["recoveryMode"] == "multilingual-title"

    acronym = item("u_acronym", "review", "live_page_identity_mismatch")
    acronym["verification"]["evidence"]["liveOfficialPage"].update({
        "title": "EXU admissions", "bodyMatches": True, "bodyMatchedName": "EXU",
    })
    assert classify(acronym, relationships)["recoveryMode"] == "acronym-or-brand-title"

    redirect = item("u_redirect", "rejected", "redirected_domain_not_in_ror_domains")
    redirect_result = classify(redirect, relationships)
    assert redirect_result["category"] == "auto-recoverable"
    assert redirect_result["recoveryMode"] == "official-domain-redirect"

    relation = item("u_campus", "review", "ror_match_missing")
    relation_result = classify(relation, relationships)
    assert relation_result["category"] == "relationship-rule-required"

    missing = item("u_missing", "review", "ror_match_missing")
    missing["rorOrganization"] = None
    assert classify(missing, relationships)["category"] == "ror-missing"

    blocked = item("u_blocked", "review", "live_page_http_error")
    blocked["verification"]["evidence"]["liveOfficialPage"]["status"] = 502
    assert classify(blocked, relationships)["category"] == "blocked"

    rejected = item("u_wrong", "rejected", "ror_name_not_matched", "Target University")
    rejected["registryResolution"]["selected"]["name"] = "Different Medical School"
    assert classify(rejected, relationships)["category"] == "true-rejection"

    embedded_qualifier = item(
        "u_old_label", "rejected", "ror_name_not_matched", "Example (Region) University"
    )
    assert classify(embedded_qualifier, relationships)["category"] == "relationship-rule-required"


def test_ror_raw_hash():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        body = b'{"items": []}'
        digest = hashlib.sha256(body).hexdigest()
        raw = root / "query.json.gz"
        manifest = root / "query.manifest.json"
        with gzip.open(str(raw), "wb") as target:
            target.write(body)
        manifest.write_text(json.dumps({"rawFile": str(raw), "sha256": digest}), encoding="utf-8")
        record = item("u_raw", "review", "ror_match_missing")
        record["registryResolution"] = {"attempts": [{
            "queryUrl": "https://api.ror.org/v2/organizations?query=example",
            "rawFile": str(raw),
            "rawManifestFile": str(manifest),
            "rawSha256": digest,
        }]}
        evidence = ror_raw_evidence(record)
        assert evidence["attemptCount"] == 1
        assert evidence["rawPresent"] == 1
        assert evidence["manifestPresent"] == 1
        assert evidence["hashVerified"] == 1
        assert evidence["hashFailures"] == 0


def test_current_corpus():
    verification_paths = [
        ROOT / "scraper" / "playwright" / "top500_official_website_verification_v3.json",
        ROOT / "scraper" / "playwright" / "top500_official_website_verification_recovered15_v3.json",
    ]
    relationships_path = ROOT / "scraper" / "programs" / "top500_institution_relationships.json"
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in verification_paths]
    relationship_payload = json.loads(relationships_path.read_text(encoding="utf-8"))
    report = build_report(payloads, relationship_payload, sample_size=3)
    assert report["summary"]["entities"] == 209
    assert report["summary"]["inputStatusCounts"] == {"rejected": 16, "review": 193}
    assert sum(report["summary"]["categoryCounts"].values()) == 209
    assert report["summary"]["categoryCounts"] == {
        "auto-recoverable": 115,
        "relationship-rule-required": 18,
        "ror-missing": 36,
        "true-rejection": 1,
        "blocked": 39,
    }
    assert all(row["statusGuardrail"] == "no-status-change" for row in report["items"])
    assert all(row["originalVerificationStatus"] in {"review", "rejected"} for row in report["items"])
    assert report["guardrails"]["verificationStatusesChanged"] is False
    markdown = render_markdown(report)
    assert "No entity is upgraded" in markdown
    assert "## Samples" in markdown


def test():
    test_classification()
    test_ror_raw_hash()
    test_current_corpus()
    print("[official-identity-triage-test] passed")


if __name__ == "__main__":
    test()
