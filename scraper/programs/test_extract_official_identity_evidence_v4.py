import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.extract_official_identity_evidence_v4 import (
    DEFAULT_OUTPUT,
    DEFAULT_TRIAGE,
    DEFAULT_VERIFICATIONS,
    build_report,
    extract_page_evidence,
    identity_match,
    validate_capture,
)


def write_capture(root, identifier, body, requested="https://www.example.edu/"):
    digest = hashlib.sha256(body).hexdigest()
    directory = root / identifier
    directory.mkdir(parents=True)
    raw = directory / ("homepage_sha256=%s.body" % digest)
    manifest = directory / ("homepage_sha256=%s.manifest.json" % digest)
    raw.write_bytes(body)
    manifest.write_text(json.dumps({
        "schemaVersion": 1,
        "kind": "homepage",
        "requestedUrl": requested,
        "finalUrl": "https://www.example.edu/",
        "status": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "bytes": len(body),
        "sha256": digest,
        "rawFile": str(raw),
    }), encoding="utf-8")
    return raw, manifest


def triage_item(identifier="u_example"):
    return {
        "canonicalId": identifier,
        "name": "Example University",
        "country": "Exampleland",
        "category": "auto-recoverable",
        "recoveryMode": "multilingual-title",
        "originalVerificationStatus": "review",
        "reasonCodes": ["live_page_identity_mismatch"],
        "rankingSources": ["qs"],
        "rorIdentity": {
            "selectedName": "Example University",
            "selectedDomains": ["example.edu"],
        },
    }


def verification_item(identifier="u_example", manifest=None, raw=None):
    live_raw = {}
    if manifest is not None:
        live_raw = {"manifestFile": str(manifest), "rawFile": str(raw)}
    return {
        "canonicalId": identifier,
        "rorOrganization": {
            "names": [
                {"value": "Example University", "types": ["ror_display"]},
                {"value": "EXU", "types": ["acronym"]},
            ],
            "domains": ["example.edu"],
        },
        "registryResolution": {"selected": {
            "name": "Example University",
            "registryDomains": ["example.edu"],
        }},
        "verification": {"evidence": {"liveOfficialPage": {"raw": live_raw}}},
    }


def test_extraction_channels():
    page = b"""<html><head>
    <title>EXU admissions</title>
    <meta property="og:site_name" content="Example University">
    <meta name="application-name" content="EXU">
    <link rel="alternate" hreflang="fr" href="/fr/">
    <script type="application/ld+json">{
      "@context":"https://schema.org",
      "@graph":[{"@type":"CollegeOrUniversity","name":"Example University"}]
    }</script></head><body><h1>Welcome to <span>Example University</span></h1></body></html>"""
    evidence = extract_page_evidence(
        page,
        {"Content-Type": "text/html; charset=utf-8"},
        "https://www.example.edu/",
        ["Example University", "EXU"],
        ["example.edu"],
    )
    sources = {item["source"] for item in evidence["identityCandidates"]}
    assert sources == {
        "title", "h1", "meta:og:site_name", "meta:application-name",
        "json-ld:organization-name",
    }
    assert evidence["jsonLdOrganizationNames"] == ["Example University"]
    assert evidence["alternateLanguageLinks"][0]["officialDomainMatch"] is True
    assert all(item["matchesAcceptedName"] for item in evidence["identityCandidates"])
    assert identity_match("EXU", ["Example University", "EXU"]) == "EXU"


def test_hash_validation_and_report():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        body = b"<html><head><title>Example University</title></head><body><h1>Example University</h1></body></html>"
        raw, manifest = write_capture(root, "u_example", body)
        checked = validate_capture(manifest)
        assert checked["valid"] is True
        assert checked["hashVerified"] is True

        report = build_report(
            {"items": [triage_item()]},
            [{"items": [verification_item(manifest=manifest, raw=raw)]}],
            root,
        )
        assert report["summary"]["entities"] == 1
        assert report["summary"]["sufficientForOriginalVerifierRerun"] == 1
        item = report["items"][0]
        assert item["originalVerificationStatus"] == "review"
        assert item["statusGuardrail"] == "no-status-change"
        assert item["rerunAssessment"]["verificationDecision"] is None
        assert report["guardrails"]["verificationStatusesChanged"] is False

        raw.write_bytes(body + b"corrupt")
        invalid = validate_capture(manifest)
        assert invalid["valid"] is False
        assert invalid["hashVerified"] is False
        invalid_report = build_report(
            {"items": [triage_item()]},
            [{"items": [verification_item(manifest=manifest, raw=raw)]}],
            root,
        )
        assert invalid_report["summary"]["sufficientForOriginalVerifierRerun"] == 0
        assert invalid_report["items"][0]["homepageRaw"] is None


def test_scope_filter():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        other = triage_item("u_other")
        other["category"] = "blocked"
        report = build_report(
            {"items": [triage_item(), other]},
            [{"items": [verification_item()]}],
            root,
        )
        assert report["summary"]["entities"] == 1
        assert report["items"][0]["canonicalId"] == "u_example"


def test_target_name_is_not_registry_evidence():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        body = b"<html><head><title>Example University</title></head><body><h1>Example University</h1></body></html>"
        raw, manifest = write_capture(root, "u_example", body)
        verification = verification_item(manifest=manifest, raw=raw)
        verification["rorOrganization"]["names"] = [{
            "value": "Different Registered Institution",
            "types": ["ror_display"],
        }]
        verification["registryResolution"]["selected"]["name"] = "Different Registered Institution"
        item = triage_item()
        item["rorIdentity"]["selectedName"] = "Different Registered Institution"
        report = build_report({"items": [item]}, [{"items": [verification]}], root)
        result = report["items"][0]
        assert result["rerunAssessment"]["sufficientForOriginalVerifierRerun"] is False
        assert "matching_identity_candidate_missing" in result["rerunAssessment"]["blockingReasons"]


def test_current_corpus():
    triage = json.loads(DEFAULT_TRIAGE.read_text(encoding="utf-8"))
    verifications = [json.loads(path.read_text(encoding="utf-8")) for path in DEFAULT_VERIFICATIONS]
    report = build_report(triage, verifications)
    assert report["summary"]["entities"] == 115
    assert report["summary"]["validHomepageRaw"] == 109
    assert report["summary"]["rawUnavailableOrInvalid"] == 6
    assert all(item["statusGuardrail"] == "no-status-change" for item in report["items"])
    assert all(item["rerunAssessment"]["verificationDecision"] is None for item in report["items"])
    assert report["guardrails"] == {
        "verificationStatusesChanged": False,
        "verifierChanged": False,
        "thresholdsChanged": False,
        "networkUsed": False,
        "verificationDecisionProduced": False,
        "rorAloneCannotVerify": True,
    }


def test():
    test_extraction_channels()
    test_hash_validation_and_report()
    test_scope_filter()
    test_target_name_is_not_registry_evidence()
    test_current_corpus()
    print("[official-identity-evidence-v4-test] passed")


if __name__ == "__main__":
    test()
