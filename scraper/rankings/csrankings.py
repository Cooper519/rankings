"""CS Rankings 抓取(全球 + AI 五领域,真实调整发表数排序;按地区可过滤)。

口径
----
CSRankings (csrankings.org) 的真实排名由前端 JS 基于 DBLP 出版数据计算,
「调整发表数(adjusted count)」需论文级数据做作者去重加权。GitHub gh-pages
只发布按作者聚合的 generated-author-info.csv,纯 Python 无法精确复现去重,
故本脚本以 csrankings.org 页面渲染结果为权威源:用无头 Chrome 渲染目标
URL,直接抽取排行榜表格(机构 / 调整发表数 / 论文数)。

为何按地区分片再合并
--------------------
CSRankings 的「world(全球)」视图在前端是虚拟滚动列表,--dump-dom 只能拿到
视口内的 ~180 行(且会漏掉清华、北大等排在最前但未被渲染的亚洲院校)。
而按地区(europe/northamerica/asia/southamerica/australasia/africa)分别
渲染时,每片都能完整给出该地区的全部机构。因此本脚本对六个地区各渲染一次,
按机构名去重合并(调整发表数取较大值),再按调整发表数降序得到全球完整榜单。

领域:AI / Vision / ML / NLP / Web+IR(ai&vision&mlmining&nlp&inforet)
地区:全球(六个 CSRankings 地区合并)——前端再按 region 下拉做二次过滤。

无头浏览器:复用 ms-playwright 的 chrome-headless-shell。
  - 优先环境变量 CSRHRS_PATH;否则扫描 %LOCALAPPDATA%\ms-playwright
  - 找不到则报错并提示安装

输出:rankings/csrankings.json  schema: {rank, universityId, name, country, score(=adjusted), year}
"""
from __future__ import annotations
import csv
import glob
import html
import io
import json
import os
import re
import subprocess
from pathlib import Path

from utils import fetch, write_json, slug

AREAS = os.environ.get("CSRANKINGS_AREAS", "ai&vision&mlmining&nlp&inforet")
# 六个 CSRankings 地区;分别渲染后合并即为全球完整榜单(world 视图因虚拟滚动不完整)。
REGIONS = ["europe", "northamerica", "asia", "southamerica", "australasia", "africa"]
TARGET_YEAR = int(os.environ.get("CSRANKINGS_YEAR", "2026"))

INST_URL = "https://raw.githubusercontent.com/emeryberger/csrankings/gh-pages/institutions.csv"
COUNTRY_URL = "https://raw.githubusercontent.com/emeryberger/csrankings/gh-pages/countries.csv"

ROW_RE = re.compile(r"^(\d+)\s+►\s+(.+?)\s+(\d+\.\d+)\s+(\d+)\s*$")


def _chrome_headless_shell() -> str:
    p = os.environ.get("CSRHRS_PATH")
    if p and os.path.isfile(p):
        return p
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    cands = glob.glob(os.path.join(base, "chromium_headless_shell-*",
                                   "chrome-headless-shell-win64", "chrome-headless-shell.exe"))
    if cands:
        return sorted(cands)[-1]
    raise RuntimeError(
        "未找到 chrome-headless-shell。请安装后重试,或用环境变量 CSRHRS_PATH 指定:\n"
        "  python -m playwright install chromium-headless-shell"
    )


def _render_dom(url: str, timeout_ms: int = 30000) -> str:
    exe = _chrome_headless_shell()
    cmd = [exe, "--headless", "--disable-gpu", "--hide-scrollbars",
           "--virtual-time-budget=" + str(timeout_ms),
           "--window-size=1440,8000", "--dump-dom", url]
    print(f"  渲染: {url}")
    # 必须字节捕获再按 UTF-8 解码:text=True 在 Windows 用系统代码页,会损坏 ► / &nbsp;
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout_ms // 1000 + 60)
    if proc.returncode != 0 and not proc.stdout:
        err = proc.stderr.decode("utf-8", "replace")[:500]
        raise RuntimeError("chrome-headless-shell 失败: " + err)
    return proc.stdout.decode("utf-8", "replace")


def _parse_ranking(dom: str) -> list[tuple[int, str, float, int]]:
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", dom, re.S)
    out: list[tuple[int, str, float, int]] = []
    for r in rows:
        t = re.sub(r"<[^>]+>", " ", r).replace("&nbsp;", " ").replace("\u00a0", " ")
        t = re.sub(r"\s+", " ", t).strip()
        m = ROW_RE.match(t)
        if m:
            out.append((int(m.group(1)), html.unescape(m.group(2).strip()),
                        float(m.group(3)), int(m.group(4))))
    return out


def _country_map() -> tuple[dict[str, dict], dict[str, str]]:
    inst_rows = list(csv.reader(io.StringIO(fetch(INST_URL).text)))
    inst_meta: dict[str, dict] = {}
    for row in inst_rows[1:]:
        if len(row) >= 4:
            inst_meta[row[0]] = {"region": row[1], "cabbr": row[2], "homepage": row[3]}
    ctry_rows = list(csv.reader(io.StringIO(fetch(COUNTRY_URL).text)))
    hdr = ctry_rows[0]
    ai, ni = hdr.index("alpha_2"), hdr.index("name")
    a2name = {row[ai].upper(): row[ni] for row in ctry_rows[1:] if len(row) > ai and row[ai]}
    return inst_meta, a2name


def scrape(output_dir: Path) -> None:
    print(f"[CS Rankings] 按地区分片渲染({', '.join(REGIONS)})合并为全球榜单...")
    union: dict[str, tuple[float, int]] = {}
    for reg in REGIONS:
        url = f"https://csrankings.org/#/index?{AREAS}&{reg}"
        rows = _parse_ranking(_render_dom(url))
        new = sum(1 for r in rows if r[1] not in union)
        print(f"  {reg:14} -> {len(rows):4} 行(新增 {new})")
        for _rank, name, adj, pubs in rows:
            if name not in union or adj > union[name][0]:
                union[name] = (adj, pubs)

    print(f"[CS Rankings] 去重合并后 {len(union)} 所机构;按调整发表数降序...")
    items = sorted(union.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))

    print("[CS Rankings] 抓取 institutions.csv / countries.csv(国家元数据)...")
    inst_meta, a2name = _country_map()

    entries = []
    for name, (adj, pubs) in items:
        meta = inst_meta.get(name, {})
        cabbr = meta.get("cabbr", "")
        country = a2name.get(cabbr.upper(), cabbr)
        entries.append({
            "rank": 0,
            "universityId": slug(name),
            "name": name,
            "country": country,
            "score": adj,
            "year": TARGET_YEAR,
        })
    for i, e in enumerate(entries, 1):
        e["rank"] = i
    write_json(output_dir / "rankings" / "csrankings.json", entries)
    print(f"[CS Rankings] 完成:{len(entries)} 所全球院校(AI 五领域,按调整发表数排序)。")


if __name__ == "__main__":
    scrape(Path(__file__).resolve().parent.parent.parent / "frontend" / "public" / "data")