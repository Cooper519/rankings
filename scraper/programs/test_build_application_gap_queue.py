from __future__ import annotations

import json

from scraper.programs.build_application_gap_queue import build_queue


def covered(url: str | None = None) -> dict:
    return {"covered": True, "sources": ([{"url": url}] if url else [])}


def missing() -> dict:
    return {"covered": False, "sources": []}


def program(url: str, missing_names: set[str]) -> dict:
    return {
        "url": url,
        "deadline": missing() if "deadline" in missing_names else covered(url + "/deadline"),
        "coverage": {
            name: missing() if name in missing_names else covered(url + "/" + name)
            for name in ("applicationWindow", "requirements", "documents", "language")
        },
    }


def university(uid: str, name: str, programs: list[dict], rate: float = 0.0) -> dict:
    deadline_missing = sum(not item["deadline"]["covered"] for item in programs)
    return {
        "canonicalId": uid,
        "aliasIds": [uid],
        "universityName": name,
        "country": "Testland",
        "programCount": len(programs),
        "coverage": {
            name: {"coverageRate": rate}
            for name in ("applicationWindow", "requirements", "documents", "language")
        },
        "deadlineGap": {"coverageRate": 1 - deadline_missing / len(programs)},
        "programs": programs,
    }


def http_urls(value) -> set[str]:
    if isinstance(value, str):
        return {value} if value.startswith(("http://", "https://")) else set()
    if isinstance(value, dict):
        return set().union(*(http_urls(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(http_urls(item) for item in value), set())
    return set()


def run() -> None:
    top_programs = [
        program("https://official.example/program-b", {"deadline", "requirements", "documents"}),
        program("https://official.example/program-a", {"deadline", "language"}),
    ]
    non_top_programs = [
        program(f"https://other.example/program-{index:02d}", {"deadline", "requirements"})
        for index in range(4)
    ]
    audit = {
        "generatedAt": "2026-08-13T00:00:00Z",
        "universities": [
            university("u_non_top", "Large Non Top", non_top_programs),
            university("u_top", "Top University", top_programs, rate=0.5),
        ],
    }
    ranking = {
        "entities": [
            {
                "canonicalId": "u_top",
                "sourceUniversityIds": ["u_top_alias"],
                "existingRawTargetIds": [],
            }
        ]
    }
    manifests = [
        {
            "universityId": "u_top",
            "officialDomains": ["OFFICIAL.EXAMPLE"],
            "indexUrl": "https://official.example/masters",
            "discovery": {
                "programCandidates": {
                    "https://official.example/program-a": {
                        "sourceUrl": "https://official.example/catalog"
                    }
                }
            },
        },
        {
            "universityId": "u_non_top",
            "officialDomains": [],
            "indexUrl": None,
            "discovery": {"programCandidates": {}},
        },
    ]

    first = build_queue(audit, ranking, manifests, shard_count=4, sample_limit=2)
    second = build_queue(audit, ranking, list(reversed(manifests)), shard_count=4, sample_limit=2)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True), "queue must be deterministic"

    tasks = first["tasks"]
    assert all(task["status"] == "pending" for task in tasks)
    assert [task["taskType"] for task in tasks[:2]] == ["universityDeadline", "universityDeadline"]
    assert tasks[0]["canonicalId"] == "u_top", "Top 500 must outrank a larger non-Top500 entity"
    assert sum(task["taskType"] == "universityDeadline" and task["canonicalId"] == "u_top" for task in tasks) == 1

    top_tasks = [task for task in tasks if task["taskType"] == "programEvidence" and task["canonicalId"] == "u_top"]
    assert top_tasks[0]["programUrl"] == "https://official.example/program-b", "more missing categories sort first"
    top_a = next(task for task in top_tasks if task["programUrl"].endswith("program-a"))
    assert top_a["sourceUrl"] == "https://official.example/catalog"
    assert top_a["officialDomains"] == ["official.example"]
    assert top_a["existingEvidenceLinks"]["requirements"] == [
        "https://official.example/program-a/requirements"
    ]

    non_top = [item for item in first["universities"] if item["canonicalId"] == "u_non_top"][0]
    assert non_top["completeGapCounts"]["requirements"] == 4
    assert non_top["sampledProgramTaskCount"] == 2
    assert non_top["omittedProgramTaskCount"] == 2

    allowed_urls = http_urls(audit) | http_urls(manifests)
    for task in tasks:
        assert task["programUrl"] is None or task["programUrl"] in allowed_urls
        assert task["sourceUrl"] is None or task["sourceUrl"] in allowed_urls
    assert http_urls(first) <= allowed_urls, "every output URL must be copied from an input"
    no_manifest_deadline = next(
        task for task in tasks
        if task["taskType"] == "universityDeadline" and task["canonicalId"] == "u_non_top"
    )
    assert no_manifest_deadline["sourceUrl"] is None, "must not guess a URL from identity or domain"

    print("[application-gap-queue-test] passed")


if __name__ == "__main__":
    run()
