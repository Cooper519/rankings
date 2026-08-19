from scraper.programs.build_top350_engineering_zero_candidate_browser_queue_v4 import (
    build_queue,
)


SOURCES = ("qs", "the", "arwu", "usnews")


def entity(canonical_id, source_ids, country=None):
    item = {
        "canonicalId": canonical_id,
        "sourceUniversityIds": source_ids,
        "name": canonical_id,
    }
    if country is not None:
        item["country"] = country
    return item


def queue_item(canonical_id, priority, level="strong"):
    return {
        "taskId": "task:" + canonical_id,
        "universityId": canonical_id,
        "country": "Testland",
        "priorityPosition": priority,
        "engineeringVisibleTextSignals": {"level": level, "score": 10},
        "status": "pending",
    }


def source_rows(source, inside_id, outside_id):
    rows = [
        {"universityId": "%s_filler_%d" % (source, index), "rank": index + 1}
        for index in range(351)
    ]
    # Displayed ranks deliberately contradict array position. The item at index
    # 349 must be selected and the rank-1 item at index 350 must be excluded.
    rows[349] = {"universityId": inside_id, "rank": 9999}
    rows[350] = {"universityId": outside_id, "rank": 1}
    return rows


def test_scope_uses_array_position_and_reuses_canonical_mapping():
    inside_ids = [source + "_inside" for source in SOURCES]
    outside_ids = [source + "_outside" for source in SOURCES]
    rows_by_source = {
        source: source_rows(source, inside_id, outside_id)
        for source, inside_id, outside_id in zip(SOURCES, inside_ids, outside_ids)
    }
    filler_entities = []
    for source in SOURCES:
        for index in range(349):
            source_id = "%s_filler_%d" % (source, index)
            filler_entities.append(entity(source_id, [source_id]))
    coverage = {
        "entities": filler_entities + [
            entity("u_inside", inside_ids),
            entity("u_outside", outside_ids),
        ]
    }
    queue = {
        "items": [
            queue_item("u_inside", 7),
            queue_item("u_outside", 8, level="none"),
        ]
    }

    result = build_queue(
        queue,
        coverage,
        {"entities": []},
        rows_by_source,
        row_limit=350,
        generated_at="2026-08-14T00:00:00+00:00",
    )

    assert result["scope"]["selectionBasis"] == "first-350-rows"
    assert result["scope"]["rankingRowSummary"]["selectedRowsBySource"] == {
        source: 350 for source in SOURCES
    }
    assert result["summary"]["sourceQueueRows"] == 2
    assert result["summary"]["scopedTasks"] == 1
    assert result["summary"]["excludedRows"] == 1
    assert result["summary"]["exclusionCounts"] == {
        "outside-first-350-rows": 1
    }
    assert result["summary"]["tasksByTop350RankingSource"] == {
        source: 1 for source in SOURCES
    }
    assert [item["universityId"] for item in result["items"]] == ["u_inside"]
    assert result["items"][0]["priorityPosition"] == 0
    assert result["items"][0]["sourcePriorityPosition"] == 7
    assert all(
        selection["rowIndex"] == 349
        and selection["displayedRank"] == 9999
        for selection in result["items"][0]["top350Selections"]
    )


def test_invalid_queue_payload_is_rejected():
    try:
        build_queue({}, {"entities": []}, {"entities": []}, {}, row_limit=350)
    except ValueError as error:
        assert "items array" in str(error)
    else:
        raise AssertionError("missing queue items must fail")


def test_recovered_program_url_is_excluded():
    rows_by_source = {
        source: [{"universityId": "u_inside", "rank": 1}]
        for source in SOURCES
    }
    coverage = {"entities": [entity("u_inside", ["u_inside"])]}
    result = build_queue(
        {"items": [queue_item("u_inside", 0)]},
        coverage,
        {"entities": []},
        rows_by_source,
        priority_url_payload={
            "items": [{"canonicalId": "u_inside", "url": "https://example.edu/msc"}]
        },
        row_limit=1,
        generated_at="fixed",
    )
    assert result["summary"]["scopedTasks"] == 0
    assert result["summary"]["exclusionCounts"] == {
        "recovered-program-url": 1
    }


def test_mainland_china_is_excluded_but_hong_kong_remains():
    rows_by_source = {
        source: [
            {"universityId": "u_cn", "rank": 1},
            {"universityId": "u_hk", "rank": 2},
        ]
        for source in SOURCES
    }
    coverage = {"entities": [
        entity("u_cn", ["u_cn"], country="China"),
        entity("u_hk", ["u_hk"], country="Hong Kong"),
    ]}
    result = build_queue(
        {"items": [
            queue_item("u_cn", 0),
            queue_item("u_hk", 1),
        ]},
        coverage,
        {"entities": []},
        rows_by_source,
        row_limit=2,
        generated_at="fixed",
    )
    assert [item["canonicalId"] for item in result["items"]] == ["u_hk"]
    assert result["summary"]["exclusionCounts"] == {
        "excluded-country:china": 1
    }


def main():
    test_scope_uses_array_position_and_reuses_canonical_mapping()
    test_invalid_queue_payload_is_rejected()
    test_recovered_program_url_is_excluded()
    test_mainland_china_is_excluded_but_hong_kong_remains()
    print("[top350-engineering-zero-candidate-browser-queue-v4-test] passed")


if __name__ == "__main__":
    main()
