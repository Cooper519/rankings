from pathlib import Path
from tempfile import TemporaryDirectory
import json

from scraper.programs.merge_sharded_results import merge_shards


def test():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        expected = root / "expected.json"
        expected.write_text(json.dumps({"items": [{"canonicalId": "a"}, {"canonicalId": "b"}]}), encoding="utf-8")
        one = root / "one.json"
        two = root / "two.json"
        one.write_text(json.dumps({"items": [{"canonicalId": "a", "verificationStatus": "verified"}], "errors": []}), encoding="utf-8")
        two.write_text(json.dumps({"items": [{"canonicalId": "b", "verificationStatus": "blocked"}], "errors": []}), encoding="utf-8")
        output = merge_shards([two, one], expected)
        assert output["summary"]["processed"] == 2
        assert output["summary"]["statusCounts"] == {"verified": 1, "blocked": 1}

        two.write_text(json.dumps({"items": [], "errors": []}), encoding="utf-8")
        try:
            merge_shards([one, two], expected)
        except ValueError as error:
            assert "missing=1" in str(error)
        else:
            raise AssertionError("incomplete shards must fail")
    print("[merge-sharded-results-test] passed")


if __name__ == "__main__":
    test()
