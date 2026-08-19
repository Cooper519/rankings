"""聚合五榜 rankings/*.json -> universities.json(按 universityId 去重)。

运行: python build_universities.py  (在 main.py 全量抓取后自动调用)
输出: ../frontend/public/data/universities.json  schema: { id: {name, country, region, ...} }
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scraper.programs.scope_policy import is_mainland_china_country

OUTPUT_DIR = ROOT / "frontend" / "public" / "data"
SOURCES = ("qs", "the", "arwu", "usnews", "csrankings")

# 国家 -> 地区 简易映射(可后续扩展)
REGION = {
    "United States": "North America", "USA": "North America", "Canada": "North America",
    "United Kingdom": "United Kingdom", "U.K.": "United Kingdom",
    "Germany": "Western Europe", "France": "Western Europe", "Switzerland": "Western Europe",
    "Netherlands": "Western Europe", "Belgium": "Western Europe",
    "Sweden": "Northern Europe", "Norway": "Northern Europe", "Denmark": "Northern Europe",
    "Finland": "Northern Europe", "Italy": "Southern Europe", "Spain": "Southern Europe",
    "Austria": "Western Europe", "Ireland": "Northern Europe", "Portugal": "Southern Europe",
    "China": "China", "Japan": "Asia", "South Korea": "Asia", "Singapore": "Asia",
    "Hong Kong": "Asia", "Taiwan": "Asia", "Australia": "Oceania", "New Zealand": "Oceania",
}


def build() -> None:
    universities: dict[str, dict] = {}
    for s in SOURCES:
        p = OUTPUT_DIR / "rankings" / f"{s}.json"
        if not p.exists():
            print(f"  跳过(无数据): {p.name}")
            continue
        rows = json.loads(p.read_text(encoding="utf-8"))
        for r in rows:
            uid = r.get("universityId")
            name = r.get("name", "")
            if not uid or not name:
                continue
            country = r.get("country", "")
            # NOTE: Mainland-China schools are KEPT per product spec
            # ("保留历史本地状态和排名"). Only excluded from crawl queues.
            entry = universities.get(uid)
            if entry is None:
                universities[uid] = {
                    "id": uid,
                    "name": {"en": name},
                    "country": country,
                    "region": REGION.get(country, country or ""),
                    "website": "",
                    "subjects": [],
                    "sources": [s],
                }
            else:
                if country and not entry["country"]:
                    entry["country"] = country
                    entry["region"] = REGION.get(country, country)
                if s not in entry["sources"]:
                    entry["sources"].append(s)
    (OUTPUT_DIR / "universities.json").write_text(
        json.dumps(universities, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  universities.json: {len(universities)} 所院校(去重)")


if __name__ == "__main__":
    build()
