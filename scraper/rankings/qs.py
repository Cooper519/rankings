"""QS World University Rankings 抓取(前 500)。

数据策略(2026-08 验证):
  ⚠️ QS 站点数据端点(/rankings/download/*、/api/*)被 Cloudflare JS challenge 拦截,
     纯 urllib 无法通过。世界排名主列表也不再以静态 .txt 暴露在 /sites/default/files/。
  ✅ 可靠来源:Wayback Machine 归档的 QS 静态数据文件
     https://www.topuniversities.com/sites/default/files/qs-rankings-data/en/<nid>.txt
     nid=3897789 为 QS 世界大学排名(QS World University Rankings 2025 版,1498 所,MIT #1)。
     归档快照通过 web.archive.org/web/<ts>id_/... 获取(无 Cloudflare)。

  本脚本优先尝试 Live 端点(供未来 Cloudflare 放行/装了 Playwright 的机器),
  失败则回退 Wayback 归档,保证离线可复现。

输出: rankings/qs.json  schema: [{rank, universityId, name, country, score, year}]
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from utils import fetch, write_json, slug, top_n, SOURCE_YEAR, first_int

# Live 页面(发现数据端点;当前会被 Cloudflare 拦截)
LIVE_PAGE = "https://www.topuniversities.com/world-university-rankings"
DATA_FILE_RE = re.compile(r"/sites/default/files/qs-rankings-data/[^\s\"<>]+\.json")

# Wayback 归档回退(已验证:QS World University Rankings 2025 版,1498 所,MIT #1,1401 个名次)
WAYBACK_TS = "20260414104605"
WAYBACK_NID = "3897789"
WAYBACK_URL = (
    f"https://web.archive.org/web/{WAYBACK_TS}id_/"
    f"https://www.topuniversities.com/sites/default/files/qs-rankings-data/en/{WAYBACK_NID}.txt"
)
TAG_RE = re.compile(r"<[^>]+>")


def _clean_name(title: str) -> str:
    return TAG_RE.sub("", title or "").strip()


def _parse_rows(rows: list) -> list[dict]:
    items = []
    for n in rows:
        try:
            name = _clean_name(n.get("title") or n.get("name") or "")
            if not name:
                continue
            rank = first_int(n.get("rank_display") or n.get("rank"))
            if not rank:
                continue
            score = n.get("score")
            try:
                score = float(score) if score not in (None, "", "N/A") else None
            except (TypeError, ValueError):
                score = None
            items.append({
                "rank": rank,
                "universityId": slug(name),
                "name": name,
                "country": (n.get("country") or n.get("location") or "").strip(),
                "score": score,
                "year": SOURCE_YEAR["qs"],
            })
        except Exception as e:
            print(f"  跳过: {e}")
    return items


def _try_live() -> list[dict]:
    try:
        html = fetch(LIVE_PAGE).text
        m = DATA_FILE_RE.search(html)
        if not m:
            return []
        data_url = "https://www.topuniversities.com" + m.group(0)
        payload = fetch(data_url).json()
        rows = payload.get("nodes") or payload.get("data") or []
        return _parse_rows(rows)
    except Exception as e:
        print(f"  [QS] Live 端点不可用({e}),回退 Wayback 归档")
        return []


def scrape(output_dir: Path) -> None:
    print("[QS] 尝试 Live 端点...")
    items = _try_live()
    if not items:
        print(f"[QS] 抓取 Wayback 归档 {WAYBACK_URL}")
        payload = fetch(WAYBACK_URL).json()
        rows = payload.get("data") or payload.get("nodes") or []
        print(f"  归档原始条目: {len(rows)}")
        items = _parse_rows(rows)
    items = top_n(items)
    print(f"[QS] 解析有效条目: {len(items)}")
    if items:
        print(f"  #1 {items[0]['name']} ({items[0]['country']}) score={items[0]['score']}")
    write_json(output_dir / "rankings" / "qs.json", items)
