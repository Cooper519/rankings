"""USNews Best Global Universities 抓取(前 500)。

数据策略(2026-08 验证):
  ⚠️ USNews 站点为重度 SSR + 付费墙,单页加载约 60-90s,纯 urllib 频繁超时;
     页面无独立 JSON API,排名列表按 ?page=N 分页 SSR(每页 10 所),共 217 页。
     页面内嵌 window.__PAGE_CONTEXT_QUERY_STATE__ 含本页 10 条(items)+ total_count。
  ✅ 可靠来源:Wayback Machine 归档的分页快照
     https://www.usnews.com/education/best-global-universities/rankings?page=N
     通过 web.archive.org/web/<ts>id_/... 抓取,解析 __PAGE_CONTEXT_QUERY_STATE__。

  本脚本:CDX 检索 page=1..60 的最新归档快照 → 逐页抓取 → 解析 items(10/页)。
  归档不连续的页会产生名次空缺(已在控制台与输出条目中标注,供人工补录)。

输出: rankings/usnews.json  schema: [{rank, universityId, name, country, score, year}]
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from utils import fetch, write_json, slug, top_n, SOURCE_YEAR, first_int

CDX = ("https://web.archive.org/cdx/search/cdx?"
       "url=usnews.com/education/best-global-universities/rankings?page=*&"
       "output=json&limit=3000&from=2022&collapse=urlkey&filter=statuscode:200")
SEARCH_PAGE = "https://www.usnews.com/education/best-global-universities/rankings"
PAGE_RE = re.compile(r"page=(\d+)")
STATE_RE = re.compile(r"window\['__PAGE_CONTEXT_QUERY_STATE__'\]\s*=\s*")
STATS_LABEL = "Global Score"


def _extract_state(html: str):
    """从页面 HTML 中提取 __PAGE_CONTEXT_QUERY_STATE__ 的 JSON 对象。"""
    m = STATE_RE.search(html)
    if not m:
        return None
    # 取到 </script> 为止,替换 JS undefined -> null 再解析
    end = html.find("</script", m.end())
    blob = html[m.end():end].lstrip(" =").rstrip().rstrip(";").rstrip()
    blob = re.sub(r"\bundefined\b", "null", blob)
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        # 兜底:截断到最后一个完整 }
        for i in range(len(blob) - 1, 0, -1):
            if blob[i] == "}":
                try:
                    return json.loads(blob[:i + 1])
                except json.JSONDecodeError:
                    continue
        return None


def _page_items(state) -> list:
    """从 state 中定位 search/index.js 的 data.items。"""
    if not isinstance(state, dict):
        return []
    for k, v in state.items():
        if k.endswith("global-universities/search/index.js") and isinstance(v, dict):
            d = v.get("data")
            if isinstance(d, dict) and isinstance(d.get("items"), list):
                return d["items"]
    return []


def _row_to_item(row: dict) -> dict | None:
    name = (row.get("name") or "").strip()
    if not name:
        return None
    # ranks 数组中 label 含 "Best Global Universities" 的为综合排名
    rank = None
    for r in row.get("ranks") or []:
        if r.get("is_ranked"):
            rank = first_int(r.get("value"))
            if rank:
                break
    if not rank:
        rank = first_int(row.get("rank_display"))
    if not rank:
        return None
    score = None
    for s in row.get("stats") or []:
        if (s.get("label") or "").lower().startswith("global score"):
            try:
                score = float(s.get("value"))
            except (TypeError, ValueError):
                score = None
            break
    return {
        "rank": rank,
        "universityId": slug(name),
        "name": name,
        "country": (row.get("country_name") or "").strip(),
        "score": score,
        "year": SOURCE_YEAR["usnews"],
    }


def _latest_snapshot_per_page(max_page: int) -> dict[int, str]:
    """CDX 检索分页快照,返回 {page: timestamp}。"""
    print("[USNews] CDX 检索分页快照...")
    rows = fetch(CDX).json()
    by_page: dict[int, str] = {}
    for row in rows[1:]:
        ts = row[1]
        m = PAGE_RE.search(row[2])
        if not m:
            continue
        p = int(m.group(1))
        if p > max_page + 5:
            continue
        if p not in by_page or ts > by_page[p]:
            by_page[p] = ts
    print(f"  发现 {len(by_page)} 个页码的归档快照(范围 1..{max_page})")
    return by_page


def scrape(output_dir: Path) -> None:
    max_page = 50  # 10/页 × 50 = 500 所
    snapshots = _latest_snapshot_per_page(max_page)
    items: list[dict] = []
    missing: list[int] = []
    for p in range(1, max_page + 1):
        ts = snapshots.get(p)
        if not ts:
            missing.append(p)
            continue
        url = f"https://web.archive.org/web/{ts}id_/" + SEARCH_PAGE + f"?page={p}"
        try:
            html = fetch(url).text
            state = _extract_state(html)
            rows = _page_items(state) if state else []
        except Exception as e:
            print(f"  page {p} 抓取失败: {e}")
            missing.append(p)
            continue
        added = 0
        for r in rows:
            it = _row_to_item(r)
            if it:
                items.append(it)
                added += 1
        print(f"  page {p}: +{added} (ts={ts})")
    # 去重(按 universityId 取 rank 最小)
    best: dict[str, dict] = {}
    for it in items:
        bid = it["universityId"]
        if bid not in best or it["rank"] < best[bid]["rank"]:
            best[bid] = it
    items = top_n(list(best.values()))
    if missing:
        print(f"[USNews] 归档缺失页(名次有空缺,待人工补录): {missing}")
    print(f"[USNews] 解析有效条目: {len(items)}")
    if items:
        print(f"  #1 {items[0]['name']} ({items[0]['country']}) score={items[0]['score']}")
    write_json(output_dir / "rankings" / "usnews.json", items)
