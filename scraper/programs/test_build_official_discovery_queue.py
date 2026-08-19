import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.build_official_discovery_queue import (
    INPUT,
    build_queue,
    deterministic_shard,
    parse_args,
)


def fixture_audit() -> dict:
    return {
        "generatedAt": "2026-08-13T00:00:00+00:00",
        "gaps": [
            {
                "canonicalId": "u_us_one",
                "name": "US One University",
                "country": "United States",
                "rankingSources": ["usnews", "qs"],
                "sourceUniversityIds": ["u_us_one_alt", "u_us_one"],
                "rankingAppearances": [{"source": "qs", "rank": 80, "year": 2027}],
            },
            {
                "canonicalId": "u_fr_one",
                "name": "France One University",
                "country": "France",
                "rankingSources": ["the"],
                "sourceUniversityIds": ["u_fr_one"],
                "rankingAppearances": [{"source": "the", "rank": 20, "year": 2025}],
            },
            {
                "canonicalId": "u_fr_four",
                "name": "France Four University",
                "country": "France",
                "rankingSources": ["usnews", "arwu", "the", "qs"],
                "sourceUniversityIds": ["u_fr_four"],
                "rankingAppearances": [{"source": "qs", "rank": 100, "year": 2027}],
            },
        ],
    }


def assert_no_third_party_domains(queue: dict) -> None:
    for item in queue["items"]:
        assert item["officialDomains"] == []
        assert item["indexUrl"] is None
        for query in item["queries"]:
            assert query["domainHintIsVerification"] is False
            # Search text must not contain a concrete host or URL. The only
            # domain-shaped token allowed is the non-verifying US .edu hint.
            scrubbed = query["query"].replace("site:.edu", "")
            assert not re.search(r"(?:https?://|www\.|site:|\b[a-z0-9-]+\.(?:com|org|net|edu)\b)", scrubbed, re.I)
            domain_hint = query["domainHint"]
            assert domain_hint in (None, ".edu")


def test() -> None:
    audit = fixture_audit()
    first = build_queue(audit, shard_count=7)
    second = build_queue(audit, shard_count=7)
    assert first == second
    assert first["total"] == 3
    assert [item["canonicalId"] for item in first["items"]] == [
        "u_fr_four",
        "u_fr_one",
        "u_us_one",
    ]
    assert [item["queuePosition"] for item in first["items"]] == [0, 1, 2]
    assert all(item["verificationStatus"] == "pending" for item in first["items"])
    assert first["items"][0]["rankingSources"] == ["qs", "the", "arwu", "usnews"]
    assert len(first["items"][0]["queries"]) == 2
    assert len(first["items"][2]["queries"]) == 3
    assert "site:.edu" in first["items"][2]["queries"][2]["query"]
    assert deterministic_shard("u_fr_four", 7) == first["items"][0]["shard"]
    assert_no_third_party_domains(first)

    args = parse_args(["--audit", "audit-v2.json", "--output", "queue-v2.json"])
    assert args.audit == Path("audit-v2.json")
    assert args.output == Path("queue-v2.json")
    legacy_args = parse_args(["--input", "legacy.json"])
    assert legacy_args.audit == Path("legacy.json")
    sourced = build_queue(audit, source_audit=Path("audit-v2.json"))
    assert sourced["sourceAudit"] == "audit-v2.json"

    proposals = {
        "generatedAt": "2026-08-13T01:00:00+00:00",
        "highConfidenceDuplicateGroups": [
            {
                "proposalStatus": "review-required",
                "confidence": "high",
                "relation": "sameInstitution",
                "recommendedCanonicalId": "u_fr_one",
                "entityIds": ["u_fr_one", "u_fr_four"],
            }
        ],
    }
    annotated = build_queue(
        audit,
        proposals=proposals,
        source_proposals=Path("alias-proposals.json"),
    )
    assert annotated["total"] == 3  # Proposals must never merge queue entities.
    proposal_items = [item for item in annotated["items"] if item["aliasProposal"]]
    assert {item["canonicalId"] for item in proposal_items} == {"u_fr_one", "u_fr_four"}
    assert all(item["aliasProposal"]["binding"] is False for item in proposal_items)
    assert annotated["policy"]["queueEntitiesMergedByProposal"] is False
    assert annotated["sourceAliasProposals"] == "alias-proposals.json"

    # The production audit must retain exactly the 626 uncovered entities.
    production = build_queue(json.loads(INPUT.read_text(encoding="utf-8-sig")))
    assert production["total"] == 626
    assert len(production["items"]) == 626
    assert len({item["canonicalId"] for item in production["items"]}) == 626
    assert_no_third_party_domains(production)

    # Serialization is deterministic as well as the in-memory structure.
    with TemporaryDirectory() as directory:
        left = Path(directory) / "left.json"
        right = Path(directory) / "right.json"
        payload = json.dumps(production, ensure_ascii=False, indent=2) + "\n"
        left.write_text(payload, encoding="utf-8")
        right.write_text(
            json.dumps(build_queue(json.loads(INPUT.read_text(encoding="utf-8-sig"))), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        assert left.read_bytes() == right.read_bytes()

    print("[official-discovery-queue-test] passed")


if __name__ == "__main__":
    test()
