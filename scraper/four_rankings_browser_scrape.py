"""Playwright 版四大榜抓取器:处理 JS 渲染站、反爬封锁站。

复用 four_rankings_scrape 的发现/抽取/落盘逻辑,仅把 fetch 换成
真实 Chromium 渲染(page.content())。逐校打印进度,断点续跑。

用法:
    python scraper/four_rankings_browser_scrape.py --limit 8
    python scraper/four_rankings_browser_scrape.py --skip 8 --limit 8
    python scraper/four_rankings_browser_scrape.py --uid u_kyung_hee_university
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import scraper.four_rankings_scrape as fsm  # noqa: E402
from scraper.four_rankings_scrape import (  # noqa: E402
    PROGRESS_FILE as STATIC_PROGRESS,
)

BROWSER_PROGRESS = os.path.join(ROOT, "raw", "rankings", "four_rankings_browser_progress.jsonl")
PENDING_FILE = os.path.join(ROOT, "raw", "rankings", "four_rankings_pending.json")

# 降低预算:浏览器渲染每页更慢
fsm.MAX_HOP_PAGES = 5
fsm.MAX_DETAIL_PAGES = 14
fsm.MAX_PROGRAMS = 48
fsm.REQUEST_BUDGET = 24


class _PwResp:
    def __init__(self, text: str, status: int):
        self.text = text
        self.status_code = status


class BrowserFetcher:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        launch_kwargs = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        }
        # 优先真实 Chrome(反爬通过率高),其次缓存的 chromium,最后 playwright 自带
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        errors = []
        if os.path.exists(chrome):
            try:
                self._browser = self._pw.chromium.launch(
                    executable_path=chrome, **launch_kwargs)
            except Exception as e:
                errors.append(f"chrome:{type(e).__name__}")
                self._browser = None
        else:
            self._browser = None
        if self._browser is None:
            try:
                self._browser = self._pw.chromium.launch(**launch_kwargs)
            except Exception:
                exe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright",
                                   "chromium-1234", "chrome-win64", "chrome.exe")
                if not os.path.exists(exe):
                    if errors:
                        raise RuntimeError(errors[0])
                    raise
                self._browser = self._pw.chromium.launch(executable_path=exe, **launch_kwargs)
        self._context = self._browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        self._context.set_default_timeout(25000)
        self._last = 0.0

    def fetch(self, url: str, headers=None) -> _PwResp:
        # 限速 ~1 req/s
        wait = 1.0 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        page = self._context.new_page()
        try:
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            except Exception:
                # 长轮询站点:domcontentloaded 超时但页面已可读
                resp = None
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            # 触发懒加载
            try:
                page.mouse.wheel(0, 1200)
                time.sleep(0.4)
            except Exception:
                pass
            time.sleep(0.8)
            html = page.content()
            # frameset 老站:合并所有 frame 的 HTML
            try:
                frames = page.frames
                if len(frames) > 1:
                    parts = [html]
                    for fr in frames[1:]:
                        try:
                            parts.append(fr.content())
                        except Exception:
                            pass
                    html = "\n".join(parts)
            except Exception:
                pass
            status = resp.status if resp else 200
            low = html[:4000].lower()
            if ("just a moment" in low or "checking your browser" in low
                    or "enable javascript and cookies" in low):
                raise RuntimeError(f"blocked:anti-bot:{url[:60]}")
            return _PwResp(html, status)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"{type(e).__name__}: {str(e)[:120]}")
        finally:
            page.close()

    def close(self):
        try:
            self._context.close()
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--uid", action="append", default=[])
    ap.add_argument("--source", choices=["pending", "todo"], default="pending",
                    help="pending=内容为空的包(重算); todo=round2 原始清单")
    args = ap.parse_args()

    if args.source == "todo":
        targets = json.load(open(fsm.TODO_FILE, encoding="utf-8"))
    else:
        targets = json.load(open(PENDING_FILE, encoding="utf-8"))
        # 内容感知:跳过已有项目的
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
    if os.path.exists(BROWSER_PROGRESS):
        for line in open(BROWSER_PROGRESS, encoding="utf-8"):
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

    total_all = len(json.load(open(fsm.TODO_FILE, encoding="utf-8")))
    print(f"== 浏览器抓取 {len(targets)} 所 ==", flush=True)
    os.makedirs(os.path.dirname(BROWSER_PROGRESS), exist_ok=True)

    bf = BrowserFetcher()
    orig_fetch = fsm.fetch
    fsm.fetch = bf.fetch
    try:
        for i, t in enumerate(targets, 1):
            t0 = time.time()
            try:
                res = fsm.scrape_one(t)
            except Exception as e:
                res = {"uid": t["uid"], "name": t["name"], "status": "error",
                       "programs": 0, "pages": 0, "deadline": None,
                       "issues": [f"{type(e).__name__}: {str(e)[:120]}"]}
            rec = {"ts": datetime.now(timezone.utc).isoformat(), **res}
            with open(BROWSER_PROGRESS, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            iss = "; ".join(res.get("issues", [])[:2])
            print(f"[browser {i}/{len(targets)}] {res['name']} — {res['status']} | "
                  f"项目 {res.get('programs', 0)} | 页面 {res.get('pages', 0)} | "
                  f"deadline={res.get('deadline') or 'unknown'}"
                  + (f" | issues: {iss}" if iss else "")
                  + f" ({time.time()-t0:.0f}s)", flush=True)
    finally:
        fsm.fetch = orig_fetch
        bf.close()


if __name__ == "__main__":
    main()