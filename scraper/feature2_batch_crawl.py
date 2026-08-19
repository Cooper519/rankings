"""Batch-crawl Feature 2 official URLs for missing schools.

For each school in the crawl queue:
1. Fetch the official homepage via HTTP
2. Parse HTML for links containing master/graduate/program/study keywords
3. Follow promising links to find program catalog pages
4. Save URLs categorized by type and raw HTML evidence

Output: scraper/playwright/feature2_crawl_results.json
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = ROOT / "scraper" / "playwright" / "feature2_crawl_queue.json"
OUTPUT_PATH = ROOT / "scraper" / "playwright" / "feature2_crawl_results.json"
RAW_DIR = ROOT / "scraper" / "playwright" / "feature2_raw"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 RankingSelect/0.1"

# Keywords for URL classification
URL_PATTERNS = {
    "master-catalog": re.compile(r"master|graduate.*program|study.*master|postgraduate|msc|master.?s", re.I),
    "engineering-cs": re.compile(r"engineering|computer.?science|informatics|ee|electrical|mechanical", re.I),
    "program-page": re.compile(r"programme|program/|course/|degree/|curriculum", re.I),
    "admission-requirements": re.compile(r"admission|requirements|eligibility|entry.?requirement|prerequisite", re.I),
    "application-deadline": re.compile(r"deadline|application.?period|apply|dates|calendar", re.I),
    "required-documents": re.compile(r"document|material|transcript|cv|recommendation|motivation", re.I),
    "language-requirements": re.compile(r"language|ielts|toefl|english.?proof|english.?requirement", re.I),
}

# Junk patterns to skip
JUNK_PATTERNS = re.compile(
    r"facebook|twitter|linkedin|instagram|youtube|wordpress|blog|news|event|"
    r"library|sport|dining|housing|career|alumni|donate|shop|accessibility|"
    r"cookie|privacy|terms|login|signin|portal|intranet|\.pdf$|\.jpg$|\.png$",
    re.I,
)


def fetch_url(url: str, timeout: int = 10) -> tuple[int, str, str]:
    """Fetch URL and return (status, final_url, html)."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        resp = urllib.request.urlopen(req, timeout=timeout)
        html = resp.read().decode("utf-8", errors="replace")
        return resp.status, resp.url, html
    except urllib.error.HTTPError as e:
        try:
            body = e.read(4096).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return e.code, url, body
    except Exception as e:
        return 0, url, str(e)


def extract_links(html: str, base_url: str) -> list[dict]:
    """Extract and classify links from HTML."""
    links = []
    for m in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html, re.I):
        href = m.group(1).strip()
        text = m.group(2).strip()
        if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        # Resolve relative URLs
        if href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            href = f"{parsed.scheme}://{parsed.netloc}{href}"
        elif not href.startswith("http"):
            continue
        # Skip junk
        if JUNK_PATTERNS.search(href):
            continue
        # Classify
        url_type = None
        for utype, pattern in URL_PATTERNS.items():
            if pattern.search(href) or pattern.search(text):
                url_type = utype
                break
        links.append({"url": href, "text": text, "type": url_type})
    return links


def crawl_school(school: dict, timeout: int = 10, common_path_limit: int = 10) -> dict:
    """Crawl one school and return results."""
    domain = school.get("officialDomain", "")
    name = school.get("name", "")
    cid = school.get("canonicalId", "")

    result = {
        "canonicalId": cid,
        "name": name,
        "domain": domain,
        "homepageStatus": 0,
        "homepageUrl": "",
        "urls": [],
        "errors": [],
        "crawledAt": datetime.now(timezone.utc).isoformat(),
    }

    if not domain:
        result["errors"].append("no-domain")
        return result

    # Fetch homepage
    homepage_url = f"https://{domain}/"
    status, final_url, html = fetch_url(homepage_url, timeout=timeout)

    result["homepageStatus"] = status
    result["homepageUrl"] = final_url

    if status == 0:
        # Try http fallback
        status, final_url, html = fetch_url(f"http://{domain}/", timeout=timeout)
        result["homepageStatus"] = status
        result["homepageUrl"] = final_url

    if status == 0 or not html:
        result["errors"].append(f"fetch-failed: {html[:200] if isinstance(html, str) else 'unknown'}")
        return result

    # Save raw HTML
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", cid)
    raw_path = RAW_DIR / safe_name
    raw_path.mkdir(parents=True, exist_ok=True)
    (raw_path / "homepage.html").write_text(html, encoding="utf-8")

    # Extract and classify links
    links = extract_links(html, final_url)

    # Also try common master's program paths
    common_paths = [
        "/study/masters", "/education/masters", "/admissions/graduate",
        "/programs/masters", "/postgraduate", "/graduate",
        "/en/study/masters", "/en/education/masters",
        "/master", "/msc", "/study/graduate",
    ]

    collected_urls = {}
    for link in links:
        if link["type"]:
            if link["type"] not in collected_urls:
                collected_urls[link["type"]] = link["url"]

    # Try common paths if no master-catalog found
    if "master-catalog" not in collected_urls:
        for path in common_paths[:common_path_limit]:
            test_url = f"https://{domain}{path}"
            s, fu, h = fetch_url(test_url, timeout=timeout)
            if 200 <= s < 300 and h and len(h) > 500:
                collected_urls["master-catalog"] = fu
                (raw_path / f"catalog_{path.replace('/', '_')}.html").write_text(h, encoding="utf-8")
                # Also extract links from this page
                sub_links = extract_links(h, fu)
                for sl in sub_links:
                    if sl["type"] and sl["type"] not in collected_urls:
                        collected_urls[sl["type"]] = sl["url"]
                break

    result["urls"] = [{"type": t, "url": u} for t, u in collected_urls.items()]
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--timeout", type=int, default=10, help="per-request timeout in seconds")
    parser.add_argument("--common-path-limit", type=int, default=10, help="maximum fallback paths per school")
    args = parser.parse_args()

    queue = json.loads(args.queue.read_text(encoding="utf-8"))
    print(f"[feature2-crawl] Queue: {len(queue)} schools", flush=True)

    # Resume from existing results if present
    results = []
    if args.output.exists():
        existing = json.loads(args.output.read_text(encoding="utf-8-sig"))
        if not isinstance(existing, list):
            raise ValueError(f"{args.output} must contain a JSON array")
        # Keep completed rows while resuming. The previous implementation
        # filtered the queue using old rows and then discarded those rows.
        results = [row for row in existing if isinstance(row, dict) and row.get("canonicalId")]
        done_ids = set(r.get("canonicalId") for r in results)
        queue = [s for s in queue if s.get("canonicalId") not in done_ids]
        print(f"[feature2-crawl] Resuming: {len(results)} done, {len(queue)} remaining", flush=True)

    for i, school in enumerate(queue):
        result = crawl_school(school, timeout=max(1, args.timeout), common_path_limit=max(0, args.common_path_limit))
        results.append(result)
        # Save incrementally every 10 schools
        if (i + 1) % 10 == 0 or i == len(queue) - 1:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8"))
            covered = sum(1 for r in results if r.get("urls"))
            print(f"  Progress: {i+1}/{len(queue)} (covered: {covered})", flush=True)
        # Rate limit
        time.sleep(0.3)

    # Save results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8"))

    # Summary
    covered = sum(1 for r in results if r["urls"])
    print(f"[feature2-crawl] Done: {covered}/{len(results)} schools with URLs")
    print(f"[feature2-crawl] -> {args.output}")


if __name__ == "__main__":
    main()
