import unittest

from scraper.programs.build_feature2_scope_v1 import build_scope


class Feature2ScopeTest(unittest.TestCase):
    def test_mainland_china_is_excluded_but_hong_kong_remains(self):
        audit = {"entities": [
            {
                "canonicalId": "u_cn",
                "name": "Mainland University",
                "country": "China",
                "sourceUniversityIds": ["u_cn_source"],
            },
            {
                "canonicalId": "u_hk",
                "name": "Hong Kong University",
                "country": "Hong Kong",
                "sourceUniversityIds": ["u_hk_source"],
            },
        ]}
        rows_by_source = {
            source: [
                {"universityId": "u_cn_source", "rank": 1},
                {"universityId": "u_hk_source", "rank": 2},
            ]
            for source in ("qs", "the", "arwu", "usnews")
        }
        priority = [
            {"canonicalId": "u_cn", "url": "https://china.example/msc"},
            {"canonicalId": "u_hk", "url": "https://hongkong.example/msc"},
        ]

        result = build_scope(
            audit, {"entities": []}, priority, rows_by_source, row_limit=2
        )

        self.assertEqual(
            [item["canonicalId"] for item in result["entities"]], ["u_hk"]
        )
        self.assertEqual(result["summary"]["excludedMainlandChinaEntities"], 1)
        self.assertEqual(result["summary"]["excludedCountryCounts"], {"China": 1})

    def test_first_rows_select_scope_even_when_displayed_rank_is_banded(self):
        audit = {
            "entities": [
                {
                    "canonicalId": "u_cs",
                    "name": "CS University",
                    "country": "A",
                    "rankingSources": ["qs"],
                    "sourceUniversityIds": ["u_cs_source"],
                },
                {
                    "canonicalId": "u_unknown",
                    "name": "Unknown University",
                    "country": "B",
                    "rankingSources": ["the"],
                    "sourceUniversityIds": ["u_unknown_source"],
                },
                {
                    "canonicalId": "u_deferred",
                    "name": "Deferred University",
                    "country": "C",
                    "rankingSources": ["arwu"],
                    "sourceUniversityIds": ["u_deferred_source"],
                },
            ]
        }
        priority = [{"canonicalId": "u_cs", "url": "https://example.edu/computer-science"}]
        rows_by_source = {
            "qs": [
                {"universityId": "u_cs_source", "rank": 1},
                {"universityId": "u_deferred_source", "rank": 1},
            ],
            "the": [
                {"universityId": "u_unknown_source", "rank": 401},
                {"universityId": "u_deferred_source", "rank": 1},
            ],
            "arwu": [
                {"universityId": "u_cs_source", "rank": 401},
                {"universityId": "u_deferred_source", "rank": 1},
            ],
            "usnews": [
                {"universityId": "u_unknown_source", "rank": 497},
                {"universityId": "u_deferred_source", "rank": 1},
            ],
        }
        result = build_scope(audit, {"entities": []}, priority, rows_by_source, row_limit=1)
        statuses = {item["canonicalId"]: item["status"] for item in result["entities"]}
        self.assertEqual(statuses, {
            "u_cs": "feature2-priority",
            "u_unknown": "top350-unknown-discipline",
            "u_deferred": "deferred-top351-500",
        })
        self.assertEqual(result["summary"]["priorityEntities"], 1)
        self.assertEqual(result["summary"]["deferredTop351To500"], 1)
        self.assertEqual(result["scope"]["rankingRowSummary"]["selectedRowsBySource"], {
            source: 1 for source in ("qs", "the", "arwu", "usnews")
        })
        unknown = next(item for item in result["entities"] if item["canonicalId"] == "u_unknown")
        self.assertEqual(
            {item["displayedRank"] for item in unknown["rankingScope"]["selections"]},
            {401, 497},
        )


if __name__ == "__main__":
    unittest.main()
