from scraper.programs.build_top500_alias_proposals import build_proposals, semantic_tokens


def entity(uid, name, country, source, rank=1, covered=False):
    return {
        "canonicalId": uid,
        "name": name,
        "country": country,
        "rankingSources": [source],
        "sourceUniversityIds": [uid],
        "rankingAppearances": [
            {"source": source, "rank": rank, "year": 2026, "universityId": uid, "name": name}
        ],
        "coveredByExistingRawTarget": covered,
    }


def test():
    assert semantic_tokens("Universidad de Buenos Aires (UBA)") == ("aires", "buenos")
    assert semantic_tokens("University of Buenos Aires") == ("aires", "buenos")

    entities = [
        entity("u_universidad_de_buenos_aires_uba", "Universidad de Buenos Aires (UBA)", "Argentina", "qs", 84),
        entity("u_university_of_buenos_aires", "University of Buenos Aires", "Argentina", "arwu", 201),
        entity("u_adelaide_university", "Adelaide University", "Australia", "qs", 79),
        entity("u_the_university_of_adelaide", "The University of Adelaide", "Australia", "arwu", 151),
        entity("u_osaka_metropolitan_university", "Osaka Metropolitan University", "Japan", "arwu", 401),
        entity("u_osaka_university", "Osaka University", "Japan", "usnews", 264),
        entity("u_the_university_of_osaka", "The University of Osaka", "Japan", "qs", 95),
    ]
    audit = {
        "generatedAt": "2026-08-13T00:00:00+00:00",
        "scope": {"rawRankingRows": 7},
        "entities": entities,
    }
    payload = build_proposals(audit)
    assert payload["policy"]["binding"] is False
    assert payload["policy"]["automaticMergeAllowed"] is False

    high = payload["highConfidenceDuplicateGroups"]
    uba = next(group for group in high if "u_university_of_buenos_aires" in group["sourceIds"])
    assert uba["recommendedCanonicalId"] == "u_university_of_buenos_aires"
    assert uba["relation"] == "sameInstitution"
    assert set(uba["entityIds"]) == {
        "u_universidad_de_buenos_aires_uba", "u_university_of_buenos_aires"
    }

    # Adelaide must be temporal review, never an exact-name auto proposal.
    assert not any("u_adelaide_university" in group["sourceIds"] for group in high)
    adelaide = next(group for group in payload["mediumConfidenceReviewGroups"] if "u_adelaide_university" in group["sourceIds"])
    assert adelaide["relation"] == "successorOf"
    assert adelaide["recommendedCanonicalId"] is None

    # The two Osaka labels are aliases, but Metropolitan is explicitly excluded.
    osaka = next(group for group in high if "u_the_university_of_osaka" in group["sourceIds"])
    assert set(osaka["entityIds"]) == {"u_osaka_university", "u_the_university_of_osaka"}
    excluded = payload["explicitDoNotMergeGroups"]
    assert any("u_osaka_metropolitan_university" in group["sourceIds"] for group in excluded)

    print("[top500-alias-proposals-test] passed")


if __name__ == "__main__":
    test()
