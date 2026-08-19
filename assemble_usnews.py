import json, sys
from pathlib import Path
ROOT = Path(r"D:\code Analysis\Rankings")
sys.path.insert(0, str(ROOT / "scraper"))
from utils import slug, first_int, top_n, write_json

YEAR = 2025
raw = json.load(open(ROOT / "_usnews_raw.json", encoding="utf-8"))
items = []
for r in raw:
    name = (r.get("name") or "").strip()
    if not name:
        continue
    rank = first_int(r.get("rank"))
    if not rank:
        continue
    score = None
    try:
        score = float(r.get("score"))
    except (TypeError, ValueError):
        score = None
    items.append({"rank": rank, "universityId": slug(name), "name": name,
                  "country": (r.get("country") or "").strip(), "score": score, "year": YEAR})

best = {}
for it in items:
    bid = it["universityId"]
    if bid not in best or it["rank"] < best[bid]["rank"]:
        best[bid] = it
items = top_n(list(best.values()))

write_json(ROOT / "frontend" / "public" / "data" / "rankings" / "usnews.json", items)
print("USNews assembled:", len(items), "rows, year", YEAR)
print("  #1", items[0]["name"], items[0]["country"], "rank", items[0]["rank"], "score", items[0]["score"])
print("  #500", items[-1]["name"], "rank", items[-1]["rank"])