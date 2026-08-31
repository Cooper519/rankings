"""自适应驱动:静态优先,失败(0 项目/封锁)自动转 Playwright 浏览器重抓。

逐校打印进度,断点续跑。目标集 = raw/rankings/four_rankings_pending.json(内容感知)。

用法:
    python scraper/scrape_driver.py --limit 10
    python scraper/scrape_driver.py --skip 40 --limit 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scraper.four_rankings_scrape as fsm  # noqa: E402
from scraper.four_rankings_browser_scrape import BrowserFetcher  # noqa: E402
from scraper.utils import fetch as _static_fetch  # noqa: E402

PENDING_FILE = os.path.join(ROOT, "raw", "rankings", "four_rankings_pending.json")
DRIVER_PROGRESS = os.path.join(ROOT, "raw", "rankings", "four_rankings_driver_progress.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--uid", action="append", default=[])
    ap.add_argument("--browser-first", action="store_true", default=True,
                    help="Playwright 浏览器优先(默认开),静态仅作兜底")
    ap.add_argument("--static-first", dest="browser_first", action="store_false")
    args = ap.parse_args()

    targets = json.load(open(PENDING_FILE, encoding="utf-8"))
    # 内容感知:已有项目则跳过
    keep = []
    for t in targets:
        p = os.path.join(ROOT, "raw", "universities", t["uid"], "projects.json")
        n = 0
        if os.path.exists(p):
            try:
                n = len(json.load(open(p, encoding="utf-8")))
            except Exception:
                n = 0
        if n == 0:
            keep.append(t)
    targets = keep

    done_uids = set()
    if os.path.exists(DRIVER_PROGRESS):
        for line in open(DRIVER_PROGRESS, encoding="utf-8"):
            try:
                done_uids.add(json.loads(line)["uid"])
            except Exception:
                pass
    targets = [t for t in targets if t["uid"] not in done_uids]
    if args.uid:
        uids = set(args.uid)
        targets = [t for t in targets if t["uid"] in uids]
    if args.skip:
        targets = targets[args.skip:]
    if args.limit:
        targets = targets[:args.limit]

    total_pending = len(keep)
    done_before = len(done_uids)
    print(f"== 自适应抓取 {len(targets)} 所 (本轮队列 {total_pending}) ==", flush=True)
    os.makedirs(os.path.dirname(DRIVER_PROGRESS), exist_ok=True)

    bf = None
    try:
        for i, t in enumerate(targets, 1):
            t0 = time.time()
            res = None
            mode = "static"
            if args.browser_first:
                if bf is None:
                    bf = BrowserFetcher()
                    fsm.fetch = bf.fetch
                mode = "browser"
                try:
                    res = fsm.scrape_one(t)
                except Exception as e:
                    res = {"uid": t["uid"], "name": t["name"], "status": "error",
                           "programs": 0, "pages": 0, "deadline": None,
                           "issues": [f"browser:{type(e).__name__}"]}
                if res.get("programs", 0) == 0:
                    # 静态兜底
                    fsm.fetch = _static_fetch
                    try:
                        res2 = fsm.scrape_one(t)
                    except Exception as e:
                        res2 = {"uid": t["uid"], "name": t["name"], "status": "error",
                                "programs": 0, "pages": 0, "deadline": None,
                                "issues": [f"static:{type(e).__name__}"]}
                    fsm.fetch = bf.fetch
                    if res2.get("programs", 0) > 0:
                        res = res2
                        mode = "static"
                    elif res2.get("status") == "extracted":
                        res = res2
                        mode = "static"
            else:
                try:
                    res = fsm.scrape_one(t)
                except Exception as e:
                    res = {"uid": t["uid"], "name": t["name"], "status": "error",
                           "programs": 0, "pages": 0, "deadline": None,
                           "issues": [f"static:{type(e).__name__}"]}
                if res.get("programs", 0) == 0:
                    if bf is None:
                        bf = BrowserFetcher()
                        fsm.fetch = bf.fetch
                    mode = "browser"
                    try:
                        res2 = fsm.scrape_one(t)
                    except Exception as e:
                        res2 = {"uid": t["uid"], "name": t["name"], "status": "error",
                                "programs": 0, "pages": 0, "deadline": None,
                                "issues": [f"browser:{type(e).__name__}"]}
                    if res2.get("programs", 0) > 0:
                        res = res2
                    elif res2.get("status") == "blocked":
                        res = res2
                    else:
                        res2["issues"] = (res.get("issues", [])[:1]
                                          + [f"static_failed:{res.get('status')}"])
                        res = res2
            rec = {"ts": datetime.now(timezone.utc).isoformat(), "mode": mode, **res}
            with open(DRIVER_PROGRESS, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            iss = "; ".join(res.get("issues", [])[:2])
            print(f"[{done_before + i}/{total_pending}] {res['name']} — {res['status']} "
                  f"[{mode}] | 项目 {res.get('programs', 0)} | 页面 {res.get('pages', 0)} | "
                  f"deadline={res.get('deadline') or 'unknown'}"
                  + (f" | issues: {iss}" if iss else "")
                  + f" ({time.time()-t0:.0f}s)", flush=True)
    finally:
        if bf is not None:
            try:
                bf.close()
            except Exception:
                pass


if __name__ == "__main__":
    import time  # noqa: F401
    main()