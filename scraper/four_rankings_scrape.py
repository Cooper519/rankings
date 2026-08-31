"""四大榜(QS/THE/ARWU/US News)院校硕士项目抓取器。

遵循 docs/SUBAGENT_SCRAPING_PROMPT.md:
- 证据优先、宁缺毋滥、不可臆测、可重复运行
- 每所院校输出 raw/universities/<uid>/{manifest,projects,sources,reviews}.json + raw/source_evidence.json
- 所有事实回指 source_id(URL/hash/时间/摘录/定位)
- 逐校打印进度行,支持断点续跑(以 progress JSONL 为准)

用法:
    python scraper/four_rankings_scrape.py --limit 10        # 抓 10 所
    python scraper/four_rankings_scrape.py --limit 10 --skip 40
    python scraper/four_rankings_scrape.py --uid u_york_university
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scraper.utils import fetch  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODO_FILE = os.path.join(ROOT, "raw", "rankings", "round2_todo_300_500.json")
PROGRESS_FILE = os.path.join(ROOT, "raw", "rankings", "four_rankings_progress.jsonl")

MAX_HOP_PAGES = 6        # 首页之外抓取的目录/招生/费用页上限
MAX_DETAIL_PAGES = 20    # 抓取的项目详情页上限
MAX_PROGRAMS = 48        # 每校保存的具体项目上限
REQUEST_BUDGET = 34      # 每校请求预算(防失控)

NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------- HTML 解析

_SCRIPT = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class LinkParser(HTMLParser):
    """收集 <a href> 文本、<title>、<h1>;并输出去标签正文。"""

    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[dict] = []
        self.h1 = ""
        self.title = ""
        self._in_title = False
        self._in_h1 = False
        self._buf: list[str] = []
        self._cur_text: list[str] | None = None
        self._cur_href: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self._cur_href = urljoin(self.base_url, href.strip())
            self._cur_text = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "a" and self._cur_href is not None:
            text = _WS.sub(" ", "".join(self._cur_text)).strip()
            if text and self._cur_href.startswith("http"):
                self.links.append({"href": self._cur_href, "text": text[:160]})
            self._cur_href = None
            self._cur_text = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_h1:
            self.h1 += data
        if self._cur_text is not None:
            self._cur_text.append(data)
        self._buf.append(data)

    @property
    def body_text(self) -> str:
        return _WS.sub(" ", "".join(self._buf)).strip()


def parse_page(html: str, base_url: str) -> dict:
    html = _SCRIPT.sub(" ", html)
    p = LinkParser(base_url)
    try:
        p.feed(html)
    except Exception:
        pass
    title = _WS.sub(" ", p.title).strip()
    h1 = _WS.sub(" ", _TAG.sub(" ", p.h1)).strip()
    if not title:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
        if m:
            title = _WS.sub(" ", _TAG.sub(" ", m.group(1))).strip()
    return {"title": title[:200], "h1": h1[:200], "links": p.links,
            "text": p.body_text[:220_000]}


# ---------------------------------------------------------------- 字典/正则

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t)?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
RE_MDY = re.compile(_MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(20\d{2})", re.I)
RE_DMY = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON + r"\.?\s*,?\s+(20\d{2})", re.I)
RE_ISO = re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})")
RE_MY = re.compile(_MON + r"\.?\s*,?\s+(20\d{2})", re.I)
# 无年份:"February 5" / "5 February"(仅在有 cycle 锚点时按 needs_review 归年)
RE_MDY_NY = re.compile(_MON + r"\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*,?\s*20)", re.I)
RE_DMY_NY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MON + r"\b(?!\s*,?\s*20)", re.I)
# 周期锚点:页面明示 2027 入学/2026-27 学年
CYCLE_ANCHOR = re.compile(
    r"(fall|autumn|september)\s+2027|2027\s+(?:intake|entry|cohort)|"
    r"academic\s+year\s+2027|2027[-/](?:28|2028)|2026[-/](?:27|2027)", re.I)

DEADLINE_KW = re.compile(
    r"(application\s+deadline|deadline[s]?\s+(?:for|is|:)|deadline[s]?|closing\s+date|"
    r"applications?\s+(?:close|closes|closed|due|must\s+be\s+(?:submitted|received)|open|opens)|"
    r"apply\s+by|submission\s+deadline|due\s+by|submit\s+by|closes?\s+on)", re.I)

LANG_CTX = re.compile(r"english(?:[- ]language)?\s+(?:language\s+)?(?:proficiency|requirement|requirements)", re.I)

RE_IELTS = re.compile(r"IELTS[^.;()]{0,80}?(?:overall(?:\s+(?:band\s+)?score)?(?:\s+of)?|band\s+)?(\d\.\d)", re.I)
RE_TOEFL = re.compile(r"TOEFL[^.;()]{0,80}?(\d{2,3})", re.I)

RE_GRE = re.compile(r"\bGRE\b[^.;]{0,60}?(not\s+required|not\s+needed|not\s+accepted|waived|optional|recommended|required)", re.I)
RE_GMAT = re.compile(r"\bGMAT\b[^.;]{0,60}?(not\s+required|not\s+needed|not\s+accepted|waived|optional|recommended|required)", re.I)

CURRENCY_PAT = (
    r"(?:US)?\$|€|£|¥|CHF|SEK|NOK|DKK|CAD|AUD|NZD|CNY|RMB|JPY|KRW|SGD|HKD|TWD|INR|EUR|GBP|USD"
)
CUR_MAP = {
    "$": "USD", "US$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "£": "GBP",
    "GBP": "GBP", "¥": "JPY", "JPY": "JPY", "CHF": "CHF", "SEK": "SEK", "NOK": "NOK",
    "DKK": "DKK", "CAD": "CAD", "AUD": "AUD", "NZD": "NZD", "CNY": "CNY", "RMB": "CNY",
    "KRW": "KRW", "SGD": "SGD", "HKD": "HKD", "TWD": "TWD", "INR": "INR",
}
RE_FEE = re.compile(
    r"(" + CURRENCY_PAT + r")\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?)|"
    r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\s?(" + CURRENCY_PAT + r")", re.I)
TUITION_CTX = re.compile(r"tuition|fees?\b|per\s+(?:year|annum)|annually|/year|/yr|per\s+semester", re.I)

# 大小写敏感:避免 re.I 下 MArch 撞上 March、MEd 撞上 med 等
PROGRAM_TOKEN = re.compile(
    r"\b(MSc|M\.S\.c?\.?|MS\b|MEng|M\.Eng\.?|MA\b|M\.A\.|MBA|LLM|LL\.M\.?|MPH|MPA|MRes|MFA|MEd|M\.Ed\.?|"
    r"MArch|M\.Arch|MLitt|MMus|MTh|"
    r"[Mm]aster\s+of\s+[A-Z][a-z]+|"
    r"[Mm]asters?(?:\s+degree)?\s+in\b|"
    r"[Mm]aster'?s?\s+[Pp]rogram(?:me)?\s+in\b|"
    r"[Mm]aster'?s?\s+[Dd]egree\s+in\b|"
    r"[Mm]asterstudiengang\b|"
    r"[Ll]aurea\s+[Mm]agistrale\b|"
    r"[Mm]estrado\s+em\b|"
    r"[Mm]\u00e1ster\s+en\b|"
    r"[Mm]aster\b\s+(?!1\b|2\b)[A-Z\u00c9\u00c8\u00c0\u00c2\u00ca\u00ce\u00d4\u00db\u00c7\u00dc\u00d6\u00c4])")
PROGRAM_HREF_DETAIL = re.compile(
    r"(programmes?/[a-z]|programs?/[a-z]|courses?/[a-z]|degrees?/[a-z]|/study/[a-z]|"
    r"/msc[-/]|/ma[-/]|/mba[-/]?$|/llm[-/]|/meng[-/]|/mph[-/]|/mpa[-/]|"
    r"master[-/s]|masters/[a-z]|postgraduate/[a-z]|graduate/program|"
    r"formation[s]?/[a-z]|offre[s]?-de-formation|studiengang|studiengaenge|"
    r"mestrado|magistrale|m[a\u00e1]ster[s]?/|posgrado|maestria)", re.I)
PROGRAM_LISTING_HREF = re.compile(
    r"(/programs?$|/programmes?$|/masters?/?$|/master-?degrees?/?$|/postgraduate/?$|"
    r"/graduate/?$|/graduate-programs?/?$|/programmes-a-?z|/course-?finder|/study-?options?/?$|"
    r"/formations?/?$|/offre[s]?-de-formation|/studiengaenge?/?$|/mestrados?/?$|"
    r"/magistrale/?$|/m[a\u00e1]sters?/?$|/posgrados?/?$|/maestrias?/?$|/oferta-?academica)", re.I)
SUBJECT_KW = re.compile(
    r"computer|engineer|business|law\b|data|financ|management|health|psycholog|educat|"
    r"biotech|chemi|physic|math|econom|architectur|design|nurs|medicine|international|"
    r"environment|public policy|marketing|humanities|social", re.I)
# 非项目页路径(文章/新闻/博客/证书)
NONPROGRAM_PATH = re.compile(r"/article|/blog|/news|/post/|/story|/diploma|/certificate|/minor", re.I)
JUNK_HREF = re.compile(
    r"\.(pdf|jpg|jpeg|png|gif|svg|ico|zip|css|js|webp)(\?|$)|mailto:|tel:|javascript:|"
    r"twitter|facebook|instagram|linkedin|youtube|wechat|weibo|cookie|privacy|"
    r"/signin|/login|/register|/cart|/donate|/alumni\b|/news\b|/events?\b|/press|/careers?|"
    r"/jobs|/contact|/search|/staff|/people|/research\b|/library\b|/sport|undergrad", re.I)
HUB_TEXT = re.compile(
    r"^(master(s)?('s)?|postgraduate|graduate)\s*(study|studies|programmes?|programs?|degrees?|"
    r"admission[s]?|courses?|entry|education|prospectus|portfolio|subjects?|a[- ]?z|"
    r"by\s+\w+|at\s+[\w\s]+)?[?!.]*$", re.I)

COMMON_PATHS = [
    "/graduate/programs", "/graduate/programs/", "/study/masters", "/masters",
    "/postgraduate", "/postgraduate-taught", "/programs", "/study/programs",
    "/en/study/masters", "/education/masters", "/academics/graduate",
    "/graduate-program", "/graduate-programs", "/study/postgraduate-taught",
]


# ---------------------------------------------------------------- 工具函数


def content_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def slug_code(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    s = re.sub(r"_+", "_", s)[:80]
    return s or "program"


def is_official(url: str, base: str) -> bool:
    try:
        h1 = urlparse(url).netloc.lower().split(":")[0]
        h2 = urlparse(base).netloc.lower().split(":")[0]
    except Exception:
        return False
    if not h1 or not h2:
        return False
    reg2 = ".".join(h2.split(".")[-2:])
    return h1 == h2 or h1.endswith("." + reg2) or h1.endswith(reg2)


def link_score(href: str, text: str) -> int:
    u, t = href.lower(), text.lower()
    if JUNK_HREF.search(u) or JUNK_HREF.search(t):
        return 0
    if "undergrad" in u or "undergrad" in t:
        return 0
    s = 0
    if re.search(r"master|msc|postgraduate|graduate|studiengang|mestrado|m[a\u00e1]ster|magistrale|formation", t):
        s += 4
    if re.search(r"programme|program|course|degree|formation", t):
        s += 1
    if re.search(r"admission|apply|application|entry\s+requirement|requirement|admission|candidature", t):
        s += 3
    if re.search(r"tuition|fees", t):
        s += 2
    if re.search(r"international", t):
        s += 1
    if re.search(r"master|msc|postgrad|studiengang|mestrado|magistrale|m[a\u00e1]ster", u):
        s += 2
    if re.search(r"admission|application|how-to-apply|apply|candidater", u):
        s += 2
    if re.search(r"tuition|fees", u):
        s += 2
    if PROGRAM_LISTING_HREF.search(u):
        s += 4
    return s


GENERIC_SLUG = {
    "all", "graduate", "grad", "masters", "master", "programs", "program",
    "programme", "programmes", "courses", "course", "index", "home", "search",
    "list", "overview", "online", "international", "admissions", "admission",
    "study", "studies", "degrees", "degree", "postgraduate", "a", "z",
    "future", "students", "subjects", "schools", "faculty", "departments",
}

def _clean_title(t: str) -> str:
    """去站名后缀、折叠重复段。"""
    t = re.split(r"\s+\|\s+|\s+–\s+|\s+—\s+|\s+-\s+", t or "", 1)[0].strip()
    # 折叠 "X X" / "X X X" 式重复
    m = re.match(r"^(.+?)\1(?:\s*\1)*$", t)
    if m:
        t = m.group(1).strip()
    return t.strip()


def name_from_slug(url: str) -> str | None:
    """从 URL 末段推导候选名,仅用于抓取后的判定,不直接入库。"""
    try:
        seg = urlparse(url).path.rstrip("/").split("/")[-1]
    except Exception:
        return None
    seg = re.sub(r"\.\w+$", "", seg)
    seg = re.sub(r"[-_]+", " ", seg).strip()
    if not seg or seg.lower() in GENERIC_SLUG or any(ch.isdigit() for ch in seg):
        return None
    seg = re.sub(r"\b(Msc|Mba|Ma|Meng|Mph|Mpa|Llm|It|Ai|Hr)\b",
                 lambda m: m.group(1).upper(), seg.title())
    return seg if 3 <= len(seg) <= 90 else None


def clean_program_name(raw: str) -> str | None:
    name = _clean_title(_WS.sub(" ", raw or "").strip())
    if not name or len(name) < 4 or len(name) > 130:
        return None
    if HUB_TEXT.match(name):
        return None
    low = name.lower()
    if any(w in low for w in ("undergrad", "phd", "doctoral", "scholarship", "webinar")):
        return None
    if re.search(r"\b(diploma|certificate)\b", low) and not re.search(r"master|mba|msc|ma\b", low):
        return None
    if PROGRAM_TOKEN.search(name):
        return name.rstrip(". ")
    # 北欧/英式:"X, Master's Programme, 120 credits" / "Master's Programme in X"
    if re.search(r"master'?s?\s+(programme|program|degree)\s+in\b", low):
        return name.rstrip(". ")
    if re.search(r"master'?s?\s+programme\b", low) and re.search(r"\d+\s*credits", low):
        return name.rstrip(". ")
    return None


# ---------------------------------------------------------------- 日期/事实抽取


def _month_safe(mon: str) -> int | None:
    return MONTHS.get(mon.lower()) or MONTHS.get(mon.lower()[:3])


def parse_dates(text: str) -> list[dict]:
    """解析 exact/range/month 日期命中,按位置排序输出。"""
    exact_hits: list[tuple[int, dict]] = []
    for m in RE_ISO.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            exact_hits.append((m.start(), {"y": y, "m": mo, "d": d}, m.end()))
    for m in RE_MDY.finditer(text):
        mo = _month_safe(m.group(1))
        if mo:
            exact_hits.append((m.start(), {"y": int(m.group(3)), "m": mo, "d": int(m.group(2))}, m.end()))
    for m in RE_DMY.finditer(text):
        mo = _month_safe(m.group(2))
        if mo:
            exact_hits.append((m.start(), {"y": int(m.group(3)), "m": mo, "d": int(m.group(1))}, m.end()))
    exact_hits.sort(key=lambda x: x[0])

    out: list[dict] = []
    exact_spans = []
    i = 0
    while i < len(exact_hits):
        pos, a, end = exact_hits[i]
        if i + 1 < len(exact_hits) and exact_hits[i + 1][0] - end < 48:
            pos2, b, end2 = exact_hits[i + 1]
            da = f"{a['y']:04d}-{a['m']:02d}-{a['d']:02d}"
            db = f"{b['y']:04d}-{b['m']:02d}-{b['d']:02d}"
            if da <= db:
                out.append({"type": "range", "date": da, "date_end": db, "pos": pos})
                exact_spans.append((pos, end2))
                i += 2
                continue
        da = f"{a['y']:04d}-{a['m']:02d}-{a['d']:02d}"
        out.append({"type": "exact", "date": da, "date_end": None, "pos": pos})
        exact_spans.append((pos, end))
        i += 1
    # month-only:RE_MY 命中且不与任何 exact 重叠
    for m in RE_MY.finditer(text):
        if any(s <= m.start() <= e for s, e in exact_spans):
            continue
        mo = _month_safe(m.group(1))
        if mo:
            y = int(m.group(2))
            out.append({"type": "month", "date": f"{y:04d}-{mo:02d}", "date_end": None, "pos": m.start()})
    out.sort(key=lambda d: d["pos"])
    return out


def in_27fall(d: dict) -> bool:
    if d["type"] in ("rolling", "tba"):
        return True
    lo, hi = (2026, 6), (2027, 12)
    if d["type"] == "exact":
        y, m = int(d["date"][:4]), int(d["date"][5:7])
        return lo <= (y, m) <= hi
    if d["type"] == "month":
        y, m = int(d["date"][:4]), int(d["date"][5:7])
        return lo <= (y, m) <= hi
    if d["type"] == "range":
        parts = []
        for dt in (d.get("date"), d.get("date_end")):
            if dt and re.match(r"^\d{4}-\d{2}", dt):
                parts.append((int(dt[:4]), int(dt[5:7])))
        if not parts:
            return True
        return any(lo <= p <= hi for p in parts)
    return True


def find_deadlines(text: str, anchored: bool = False) -> list[dict]:
    """anchored=True 时,无年份日期按页面周期锚点归 27fall(needs_review)。"""
    out, seen = [], set()

    def add(d: dict, inferred: bool = False):
        key = (d["type"], d["date"], d["date_end"])
        if key in seen:
            return
        seen.add(key)
        d["inferred_year"] = inferred
        out.append(d)

    for m in DEADLINE_KW.finditer(text):
        lo, hi = max(0, m.start() - 30), min(len(text), m.end() + 140)
        win = text[lo:hi]
        for d in parse_dates(win):
            add({**d, "evidence": _WS.sub(" ", text[max(0, m.start() - 40):hi]).strip()[:200]})
        if anchored:
            for m2 in RE_MDY_NY.finditer(win):
                mo = _month_safe(m2.group(1))
                if not mo:
                    continue
                d_ = int(m2.group(2))
                year = 2026 if mo >= 10 else 2027
                da = f"{year:04d}-{mo:02d}-{d_:02d}"
                add({"type": "exact", "date": da, "date_end": None,
                     "pos": m.start(), "evidence": _WS.sub(" ", text[max(0, m.start() - 40):hi]).strip()[:200]},
                    inferred=True)
            for m2 in RE_DMY_NY.finditer(win):
                mo = _month_safe(m2.group(2))
                if not mo:
                    continue
                d_ = int(m2.group(1))
                year = 2026 if mo >= 10 else 2027
                da = f"{year:04d}-{mo:02d}-{d_:02d}"
                add({"type": "exact", "date": da, "date_end": None,
                     "pos": m.start(), "evidence": _WS.sub(" ", text[max(0, m.start() - 40):hi]).strip()[:200]},
                    inferred=True)
        if re.search(r"\brolling\b", win, re.I):
            add({"type": "rolling", "date": None, "date_end": None, "pos": m.start(),
                 "evidence": _WS.sub(" ", win).strip()[:200]})
    # rolling/tba 全局兜底(没有关键词窗口命中时)
    if not out:
        if re.search(r"rolling\s+admission", text, re.I):
            out.append({"type": "rolling", "date": None, "date_end": None, "pos": 0,
                        "evidence": _WS.sub(" ", text[:200])})
        elif re.search(r"to\s+be\s+announced|\btba\b", text, re.I) and re.search(r"deadline|application", text, re.I):
            out.append({"type": "tba", "date": None, "date_end": None, "pos": 0,
                        "evidence": _WS.sub(" ", text[:200])})
    return out[:6]


def find_lang_tests(text: str) -> list[dict]:
    tests = []
    m = RE_IELTS.search(text)
    if m:
        v = float(m.group(1))
        if 4.0 <= v <= 9.0:
            tests.append({"name": "IELTS", "min_score": m.group(1)})
    m = RE_TOEFL.search(text)
    if m:
        v = int(m.group(1))
        if 45 <= v <= 120:
            tests.append({"name": "TOEFL iBT", "min_score": str(v)})
    return tests


def find_test_status(text: str, name: str) -> str | None:
    m = (RE_GRE if name == "gre" else RE_GMAT).search(text)
    if not m:
        return None
    v = m.group(1).lower()
    if "not required" in v or "not needed" in v or "not accepted" in v or "waived" in v:
        return "not_required"
    if "optional" in v or "recommended" in v:
        return "optional"
    if "required" in v:
        return "required"
    return None


def find_fees(text: str) -> list[dict]:
    fees, seen = [], set()
    for m in RE_FEE.finditer(text):
        lo = max(0, m.start() - 80)
        ctx = text[lo:m.end() + 80]
        if not TUITION_CTX.search(ctx):
            continue
        cur_raw = (m.group(1) or m.group(5) or "").strip()
        amount = (m.group(2) or m.group(4) or "").replace(",", "")
        if not amount or not cur_raw:
            continue
        cur = CUR_MAP.get(cur_raw) or CUR_MAP.get(cur_raw.upper())
        if not cur:
            continue
        try:
            val = float(amount)
        except ValueError:
            continue
        if not (300 <= val <= 3_000_000):
            continue
        key = (amount, cur)
        if key in seen:
            continue
        seen.add(key)
        period = "year" if re.search(r"/\s*year|per\s+year|per\s+annum|annually|/yr|annual|per\s+semester", ctx, re.I) else (
            "total" if re.search(r"total|entire\s+(?:programme|program|degree)", ctx, re.I) else "unknown")
        group = ("non_eu" if re.search(r"non[- ]?EU|overseas|international", ctx, re.I) else
                 ("domestic" if re.search(r"\bEU\b|home|domestic|in[- ]state", ctx, re.I) else "international"))
        fees.append({"amount": amount, "currency": cur, "period": period,
                     "applicant_group": group,
                     "condition": _WS.sub(" ", ctx).strip()[:200]})
        if len(fees) >= 4:
            break
    return fees


# ---------------------------------------------------------------- 页面事实封装


def extract_facts(text: str) -> dict:
    anchored = bool(CYCLE_ANCHOR.search(text[:30000]))
    return {
        "deadlines": find_deadlines(text, anchored=anchored),
        "lang": find_lang_tests(text),
        "gre": find_test_status(text, "gre"),
        "gmat": find_test_status(text, "gmat"),
        "fees": find_fees(text),
        "english_taught": bool(re.search(r"taught\s+in\s+english|english[- ]taught", text, re.I)),
        "bachelor": bool(re.search(r"\bbachelor", text, re.I)),
        "anchored": anchored,
    }


# ---------------------------------------------------------------- 打包保存


def src_id_for(url: str) -> str:
    return "src_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]


def save_package(uid: str, name: str, country: str, website: str,
                 status: str, programs: list[dict], sources: list[dict],
                 evidence: list[dict], notes: str, issues: list[str]) -> int:
    out = os.path.join(ROOT, "raw", "universities", uid)
    os.makedirs(os.path.join(out, "raw"), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": 1, "package_version": 1, "university_id": uid,
        "name": name, "country": country, "website": website, "updated_at": now,
        "notes": notes, "converter": "four-rankings-webfetch-v2",
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if sources:
        with open(os.path.join(out, "sources.json"), "w", encoding="utf-8") as f:
            json.dump(sources, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out, "reviews.json"), "w", encoding="utf-8") as f:
        json.dump([], f)
    with open(os.path.join(out, "raw", "source_evidence.json"), "w", encoding="utf-8") as f:
        json.dump({"captured_at": now, "status": status, "pages": evidence,
                   "issues": issues}, f, ensure_ascii=False, indent=2)
    if not programs:
        pp = os.path.join(out, "projects.json")
        if os.path.exists(pp):
            os.remove(pp)
        return 0

    projs, used_codes = [], set()
    for i, p in enumerate(programs):
        code = slug_code(p["name"])
        if code in used_codes:
            code = f"{code}_{i}"
        used_codes.add(code)
        pid = f"{uid}_main_{code}"
        cycles_in = p.get("timelines_final") or p.get("timelines") or []
        cycles = []
        for t in cycles_in:
            t = dict(t)
            t.setdefault("applicant_group", None)
            t.setdefault("round", None)
            t["timeline_id"] = slug_code(
                f"{t.get('event','application_deadline')}_{t['date_type']}_{t.get('date') or 'na'}")
            cycles.append(t)
        proj = {
            "project_id": pid, "university_id": uid, "campus_id": "main",
            "normalized_program_code": code, "name": p["name"],
            "degree": p.get("degree"), "subject": None, "study_mode": None,
            "official_url": p["official_url"], "admission_cycles": [{
                "cycle_id": "27fall", "academic_year": 2027, "entry_term": "fall",
                "status": "current", "timelines": cycles,
                "requirements": p.get("requirements", {}),
                "fees": p.get("fees", []),
            }],
            "status": "active",
            "verification_status": p.get("_vs", "extracted"),
        }
        if p.get("teaching_language"):
            proj["teaching_language"] = p["teaching_language"]
        if p.get("notes"):
            proj["notes"] = p["notes"]
        projs.append(proj)
    with open(os.path.join(out, "projects.json"), "w", encoding="utf-8") as f:
        json.dump(projs, f, ensure_ascii=False, indent=2)
    return len(projs)


# ---------------------------------------------------------------- 单校抓取


def scrape_one(t: dict) -> dict:
    uid, name, country = t["uid"], t["name"], t["country"]
    website = (t.get("website") or "").strip()
    if not website:
        mp = os.path.join(ROOT, "raw", "universities", uid, "manifest.json")
        if os.path.exists(mp):
            try:
                website = (json.load(open(mp, encoding="utf-8")).get("website") or "").strip()
            except Exception:
                pass
    # 官网字段修正表(仿冒/失效域名)
    ov_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "website_overrides.json")
    if os.path.exists(ov_path):
        try:
            website = (json.load(open(ov_path, encoding="utf-8")).get(uid) or website).strip()
        except Exception:
            pass
    res = {"uid": uid, "name": name, "country": country, "status": "blocked",
           "programs": 0, "pages": 0, "deadline": None, "issues": [], "url": website}

    sources: list[dict] = []
    evidence: list[dict] = []
    issues: list[str] = []
    captured: list[dict] = []  # {url,title,cls,text,source_id}

    def capture(url: str, status_code: int, pg: dict, cls: str) -> None:
        sid = src_id_for(url)
        sources.append({
            "source_id": sid, "url": url, "source_type": "official_web",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "verification_status": "extracted" if status_code == 200 else "needs_review",
            "title": (pg.get("title") or "")[:200], "content_hash": content_hash(pg.get("text", "")),
            "evidence_text": _WS.sub(" ", pg.get("text", "")[:300]),
        })
        evidence.append({"url": url, "http_status": status_code, "title": pg.get("title", ""),
                         "class": cls, "content_hash": content_hash(pg.get("text", "")),
                         "retrieved_at": datetime.now(timezone.utc).isoformat(),
                         "text_snippet": _WS.sub(" ", pg.get("text", "")[:500])})
        captured.append({"url": url, "title": pg.get("title", ""), "cls": cls,
                         "text": pg.get("text", ""), "source_id": sid})

    if not website:
        issues.append("no_website_in_manifest")
        save_package(uid, name, country, website, "blocked", [], [], evidence,
                     "blocked: no official website available", issues)
        res["issues"] = issues
        return res

    # 1) 入口页
    try_urls = [website]
    try:
        _p = urlparse(website)
        if _p.path and _p.path not in ("/", ""):
            try_urls.append(f"{_p.scheme}://{_p.netloc}/")
    except Exception:
        pass
    r = None
    for attempt_url in try_urls:
        try:
            r = fetch(attempt_url)
        except Exception as e:
            issues.append(f"homepage_fetch_failed:{type(e).__name__}")
            continue
        if r.status_code < 400 and len(r.text) >= 200:
            if attempt_url != website:
                website = attempt_url
                issues.append("homepage_path_404_fallback_to_root")
            break
        issues.append(f"homepage_http_{r.status_code}")
        r = None
    if r is None:
        save_package(uid, name, country, website, "blocked", [], [], evidence,
                     f"blocked: homepage unreachable ({website})", issues)
        res["issues"] = issues
        return res
    home = parse_page(r.text, website)
    capture(website, r.status_code, home, "navigation")
    budget = 1
    entry_program = clean_program_name(home["h1"]) or clean_program_name(home["title"])

    # 2) 目录/招生/费用页(1 hop)
    hop_pages: list[dict] = []
    seen_urls = {website.rstrip("/")}
    scored: list[tuple[int, str]] = []
    for lk in home["links"]:
        if not is_official(lk["href"], website):
            continue
        s = link_score(lk["href"], lk["text"])
        if s >= 3:
            scored.append((s, lk["href"]))
    scored.sort(key=lambda x: -x[0])
    hop_candidates = [u for _s, u in scored[:MAX_HOP_PAGES * 2]]

    detail_cands: dict[str, dict] = {}  # url -> {text, found_on}

    def harvest_links(pg: dict, page_url: str) -> None:
        for lk in pg["links"]:
            href = lk["href"]
            if not is_official(href, website) or JUNK_HREF.search(href.lower()):
                continue
            href = urlunparse(urlparse(href)._replace(fragment="")).rstrip("/")
            if href.rstrip("/") in seen_urls:
                continue
            if NONPROGRAM_PATH.search(urlparse(href).path.lower()):
                continue
            txt = lk["text"]
            name_c = clean_program_name(txt)
            if name_c:
                if href not in detail_cands:
                    detail_cands[href] = {"name": name_c, "found_on": page_url}
            elif PROGRAM_HREF_DETAIL.search(href.lower()):
                # 目录页链接文本常无学位词,靠 URL 模式入候选,详情页 title 再判定
                if href not in detail_cands:
                    detail_cands[href] = {"name": "", "found_on": page_url}

    for url in hop_candidates[:MAX_HOP_PAGES]:
        if budget >= REQUEST_BUDGET:
            break
        if url.rstrip("/") in seen_urls:
            continue
        seen_urls.add(url.rstrip("/"))
        try:
            r2 = fetch(url)
            budget += 1
        except Exception:
            budget += 1
            issues.append(f"fetch_failed:{url[:60]}")
            continue
        if r2.status_code >= 400 or len(r2.text) < 500:
            issues.append(f"http_{r2.status_code}:{url[:70]}")
            continue
        pg = parse_page(r2.text, url)
        title = (pg["title"] or "").strip()
        low = title.lower()
        if "404" in low or "not found" in low or "error" in low:
            continue
        cls = ("official_admission" if re.search(r"admission|apply|application|deadline|requirement", low) else
               "official_fee" if re.search(r"tuition|fees", low) else
               "directory" if re.search(r"programme|program|course|study|master|graduate|postgraduate", low) else
               "navigation")
        capture(url, r2.status_code, pg, cls)
        hop_pages.append({"url": url, "title": title, "cls": cls, "pg": pg})
        harvest_links(pg, url)

    # 2b) 兜底:常见项目目录路径
    if not detail_cands:
        for path in COMMON_PATHS:
            if budget >= REQUEST_BUDGET:
                break
            guess = website.rstrip("/") + path
            if guess.rstrip("/") in seen_urls or not is_official(guess, website):
                continue
            seen_urls.add(guess.rstrip("/"))
            try:
                r2 = fetch(guess)
                budget += 1
            except Exception:
                budget += 1
                continue
            if r2.status_code >= 400 or len(r2.text) < 500:
                continue
            pg = parse_page(r2.text, guess)
            capture(guess, r2.status_code, pg, "directory")
            hop_pages.append({"url": guess, "title": pg["title"], "cls": "directory", "pg": pg})
            harvest_links(pg, guess)
            if detail_cands:
                break

    # 3) 详情页抓取(带事实)
    def cand_rank(url: str) -> tuple:
        found = detail_cands[url].get("found_on", "")
        from_dir = any(h["url"] == found and h["cls"] == "directory" for h in hop_pages)
        return (0 if from_dir else 1,
                0 if re.search(r"master|msc|mba|llm|postgrad", url.lower()) else 1,
                0 if SUBJECT_KW.search(url.lower()) else 1)

    programs: list[dict] = []
    have: set[str] = set()
    detail_order = sorted(detail_cands.keys(), key=cand_rank)
    for url in detail_order[:MAX_DETAIL_PAGES]:
        if budget >= REQUEST_BUDGET:
            break
        seen_urls.add(url)
        try:
            r3 = fetch(url)
            budget += 1
        except Exception:
            budget += 1
            continue
        if r3.status_code >= 400 or len(r3.text) < 400:
            continue
        pg = parse_page(r3.text, url)
        pname = (clean_program_name(pg["h1"]) or clean_program_name(pg["title"])
                 or clean_program_name(detail_cands[url]["name"]))
        if not pname:
            # 详情页 title 无学位词,但页面正文有 master 证据 + URL 模式强匹配 → 接受
            lowu = url.lower()
            if PROGRAM_HREF_DETAIL.search(lowu) and re.search(r"master'?s?\b", pg["text"][:20000], re.I):
                pname = name_from_slug(url) or detail_cands[url]["name"]
                if not pname or len(pname) > 80:
                    continue
            else:
                continue
        key = re.sub(r"\W+", " ", pname.lower()).strip()
        if key in have:
            continue
        have.add(key)
        facts = extract_facts(pg["text"])
        dl27 = [d for d in facts["deadlines"] if in_27fall(d)]
        capture(url, r3.status_code, pg, "concrete_program")
        dm = PROGRAM_TOKEN.search(pname)
        programs.append({
            "name": pname,
            "degree": re.sub(r"[^A-Za-z]", "", dm.group(1)).replace(".", "") if dm else None,
            "official_url": url,
            "source_id": src_id_for(url),
            "facts": facts, "timelines": dl27, "detail": True,
        })

    # 3b) 入口页本身就是具体项目(如深链)
    if entry_program:
        key = re.sub(r"\W+", " ", entry_program.lower()).strip()
        if key not in have:
            have.add(key)
            facts = extract_facts(home["text"])
            dl27 = [d for d in facts["deadlines"] if in_27fall(d)]
            dm = PROGRAM_TOKEN.search(entry_program)
            programs.insert(0, {
                "name": entry_program,
                "degree": re.sub(r"[^A-Za-z]", "", dm.group(1)).replace(".", "") if dm else None,
                "official_url": website,
                "source_id": src_id_for(website),
                "facts": facts, "timelines": dl27, "detail": True,
            })

    # 4) link-only 项目(目录页证据,含 URL 模式候选,未抓详情)
    for url, meta in detail_cands.items():
        if len(programs) >= MAX_PROGRAMS:
            break
        nm_raw = meta["name"]
        if not nm_raw:
            # URL 模式候选:slug 名需含学科词才算具体项目
            slug_nm = name_from_slug(url)
            if not slug_nm or not SUBJECT_KW.search(slug_nm):
                continue
            nm_raw = slug_nm + " (catalog listing)"
        nm = re.sub(r"\W+", " ", nm_raw.lower()).strip()
        if nm in have or any(nm in h or h in nm for h in have):
            continue
        dm = PROGRAM_TOKEN.search(nm_raw)
        have.add(nm)
        programs.append({
            "name": nm_raw,
            "degree": re.sub(r"[^A-Za-z]", "", dm.group(1)).replace(".", "") if dm else None,
            "official_url": url,
            "source_id": src_id_for(meta["found_on"]),
            "facts": None, "timelines": [], "detail": False,
        })
    programs = programs[:MAX_PROGRAMS]

    # 4b) 兜底:项目太少时再试常见目录路径
    if len(programs) < 8:
        for path in COMMON_PATHS:
            if len(programs) >= 8 or budget >= REQUEST_BUDGET:
                break
            guess = website.rstrip("/") + path
            if guess.rstrip("/") in seen_urls or not is_official(guess, website):
                continue
            seen_urls.add(guess.rstrip("/"))
            try:
                r4 = fetch(guess)
                budget += 1
            except Exception:
                budget += 1
                continue
            if r4.status_code >= 400 or len(r4.text) < 500:
                continue
            pg4 = parse_page(r4.text, guess)
            capture(guess, r4.status_code, pg4, "directory")
            before = len(programs)
            for lk in pg4["links"]:
                if len(programs) >= 8:
                    break
                href = lk["href"]
                if not is_official(href, website) or JUNK_HREF.search(href.lower()):
                    continue
                href = urlunparse(urlparse(href)._replace(fragment="")).rstrip("/")
                if href.rstrip("/") in seen_urls:
                    continue
                if NONPROGRAM_PATH.search(urlparse(href).path.lower()):
                    continue
                name_c = clean_program_name(lk["text"])
                if not name_c:
                    continue
                nm = re.sub(r"\W+", " ", name_c.lower()).strip()
                if nm in have:
                    continue
                have.add(nm)
                dm = PROGRAM_TOKEN.search(name_c)
                programs.append({
                    "name": name_c,
                    "degree": re.sub(r"[^A-Za-z]", "", dm.group(1)).replace(".", "") if dm else None,
                    "official_url": href,
                    "source_id": src_id_for(guess),
                    "facts": None, "timelines": [], "detail": False,
                })
            if len(programs) == before:
                continue
            break

    # 5) 学校级事实页(admission/fee) → link-only 项目
    fact_pages = [c for c in captured if c["cls"] in ("official_admission", "official_fee")]
    school_deadlines: list[dict] = []
    for c in fact_pages:
        for d in extract_facts(c["text"])["deadlines"]:
            if in_27fall(d):
                school_deadlines.append({**d, "source_id": c["source_id"], "url": c["url"]})
    school_deadlines.sort(key=lambda d: ({"exact": 0, "range": 1, "month": 2, "rolling": 3, "tba": 4}[d["type"]], d.get("date") or ""))
    school_fees = find_fees(" ".join(c["text"] for c in fact_pages)) if fact_pages else []
    primary_fact = fact_pages[0] if fact_pages else (captured[0] if captured else None)

    def req_from(text: str, sid: str) -> dict:
        lang = find_lang_tests(text)
        gre = find_test_status(text, "gre")
        gmat = find_test_status(text, "gmat")
        m = re.search(r"([^.]{0,140}bachelor[^.]{0,140}\.)", text, re.I)
        return {
            "language": {
                "status": "required" if (lang or LANG_CTX.search(text)) else "unknown",
                "tests": lang,
            },
            "gre": {"status": gre or "unknown", "min_score": None},
            "gmat": {"status": gmat or "unknown", "min_score": None},
            "academic": {
                "status": "required" if re.search(r"\bbachelor", text, re.I) else "unknown",
                "description": _WS.sub(" ", m.group(1)).strip()[:280] if m else None,
            },
            "notes": "",
            "source_id": sid,
            "verification_status": "extracted" if (lang or gre or gmat) else "needs_review",
        }

    for p in programs:
        if p["detail"]:
            f = p["facts"]
            text_for_req = ""
            for c in captured:
                if c["url"] == p["official_url"]:
                    text_for_req = c["text"]
                    break
            p["requirements"] = req_from(text_for_req, p["source_id"])
            fees = f["fees"][:4] if f["fees"] else school_fees[:2]
            fee_sid = p["source_id"] if f["fees"] else (primary_fact["source_id"] if primary_fact else p["source_id"])
            timelines = p["timelines"] or school_deadlines[:3]
        else:
            text_for_req = primary_fact["text"] if primary_fact else ""
            p["requirements"] = req_from(text_for_req, primary_fact["source_id"] if primary_fact else p["source_id"])
            fees = school_fees[:2]
            fee_sid = primary_fact["source_id"] if primary_fact else p["source_id"]
            timelines = school_deadlines[:3]

        p["fees"] = [{
            "fee_id": slug_code(f"tuition_{f2['amount']}_{f2['currency']}"),
            "type": "tuition", "amount": f2["amount"], "currency": f2["currency"],
            "period": f2["period"], "applicant_group": f2["applicant_group"],
            "condition": f2["condition"], "source_id": fee_sid,
            "verification_status": "extracted",
        } for f2 in fees]
        p["timelines_final"] = [{
            "event": "application_deadline", "date_type": d["type"],
            "date": d.get("date"), "date_end": d.get("date_end"),
            "applicant_group": None, "round": None,
            "source_id": d.get("source_id", p["source_id"]),
            "verification_status": ("needs_review" if (d.get("inferred_year")
                                                       or d["type"] in ("rolling", "tba")
                                                       or (d.get("date") or "") < "2026-09")
                                    else "extracted"),
        } for d in timelines]
        if p["detail"] and p["facts"] and p["facts"]["english_taught"]:
            p["teaching_language"] = ["English"]
        ev = []
        if p["timelines_final"]:
            t0 = p["timelines_final"][0]
            ev.append("deadline:" + t0["date_type"] + (":" + t0["date"] if t0["date"] else ""))
        req = p["requirements"]
        if req["language"]["tests"]:
            ev.append("lang:" + "/".join(x["name"] + " " + x["min_score"] for x in req["language"]["tests"]))
        if p["fees"]:
            ev.append(f"fee:{p['fees'][0]['currency']}{p['fees'][0]['amount']}/{p['fees'][0]['period']}({p['fees'][0]['applicant_group']})")
        p["notes"] = ("from official page; " + "; ".join(ev)) if ev else \
            ("official listing (facts pending review)" if not p["detail"]
             else "official page captured; facts pending review")
        p["_vs"] = "extracted" if p["detail"] else "needs_review"
        p.pop("facts", None)
        p.pop("timelines", None)
        p.pop("detail", None)

    # 6) 保存
    dl_desc = ""
    if school_deadlines or programs:
        all_t = school_deadlines[:1]
        for p in programs:
            pass
        if all_t:
            dl_desc = all_t[0].get("date") or all_t[0]["type"]
        elif programs:
            for p in programs:
                if p["timelines_final"]:
                    dl_desc = p["timelines_final"][0].get("date") or p["timelines_final"][0]["date_type"]
                    break

    n = save_package(
        uid, name, country, website,
        "extracted" if programs else "no_concrete_project",
        programs, sources, evidence,
        notes=(f"four-rankings scrape 27fall: pages={len(sources)} captured, programs={len(programs)} "
               f"({sum(1 for p in programs if p.get('notes','').startswith('from official'))} with per-project facts), "
               f"school_deadline={dl_desc or 'unknown'}, fees={'yes' if school_fees else 'unknown'}, "
               f"issues={issues[:2] if issues else 'none'}"),
        issues=issues,
    )
    res.update({"status": "extracted" if programs else "no_concrete_project",
                "programs": n, "pages": len(sources), "deadline": dl_desc or None})
    return res


# ---------------------------------------------------------------- CLI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip", type=int, default=0)
    ap.add_argument("--uid", action="append", default=[])
    args = ap.parse_args()

    targets = json.load(open(TODO_FILE, encoding="utf-8"))
    done_uids = set()
    if os.path.exists(PROGRESS_FILE):
        for line in open(PROGRESS_FILE, encoding="utf-8"):
            try:
                done_uids.add(json.loads(line)["uid"])
            except Exception:
                pass
    targets = [t for t in targets if t["uid"] not in done_uids]
    if args.uid:
        targets = [t for t in targets if t["uid"] in args.uid]
    if args.skip:
        targets = targets[args.skip:]
    if args.limit:
        targets = targets[:args.limit]

    total_all = len(json.load(open(TODO_FILE, encoding="utf-8")))
    done_before = len(done_uids)
    print(f"== 待抓取 {len(targets)} 所 (已完成 {done_before}/{total_all}) ==", flush=True)
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)

    for i, t in enumerate(targets, 1):
        t0 = time.time()
        try:
            res = scrape_one(t)
        except Exception as e:
            res = {"uid": t["uid"], "name": t["name"], "status": "error",
                   "programs": 0, "pages": 0, "deadline": None,
                   "issues": [f"{type(e).__name__}: {str(e)[:120]}"]}
        rec = {"ts": datetime.now(timezone.utc).isoformat(), **res}
        with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done_now = done_before + i
        iss = "; ".join(res.get("issues", [])[:2])
        print(f"[{done_now}/{total_all}] {res['name']} — {res['status']} | "
              f"项目 {res.get('programs', 0)} | 页面 {res.get('pages', 0)} | "
              f"deadline={res.get('deadline') or 'unknown'}"
              + (f" | issues: {iss}" if iss else "")
              + f" ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()