"""Concurrent lossless HTTP crawler for official master's programme pages.

This is the fast first pass of the raw-first pipeline.  It stores untouched
HTML responses and catalogue manifests per university.  No programme title,
deadline, requirement, language, or quality normalization is performed here.
Dynamic shells, WAF responses, and failed pages remain explicitly pending for
the Playwright MCP fallback.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parent.parent.parent
PW = ROOT / "scraper" / "playwright"
DEFAULT_TARGETS = PW / "raw_crawl_targets.json"
DEFAULT_OUTPUT = PW / "_programs_full_raw"
USER_AGENT = "Mozilla/5.0 (compatible; RankingSelectRawCrawler/1.0; +local-research)"

DENIED_HOSTS = {
    "wikipedia.org", "daad.de", "mygermanuniversity.com", "studyportals.com",
    "mastersportal.com", "findamasters.com", "masterstudies.com",
    "topuniversities.com", "timeshighereducation.com", "shanghairanking.com",
    "usnews.com", "reddit.com", "linkedin.com", "facebook.com",
    "instagram.com", "youtube.com", "globalstudyprep.com",
    "globaladmissions.com", "university-directory.eu", "collegelearners.org",
    "studyindenmark.dk", "educations.com", "study.eu",
}
TRACKING_QUERY = re.compile(r"^(?:utm_.+|fbclid|gclid|mc_cid|mc_eid|ref|source)$", re.I)
ASSET_PATH = re.compile(r"\.(?:pdf|docx?|xlsx?|pptx?|zip|rar|7z|jpe?g|png|gif|svg|webp|ico|mp[34]|avi|mov|css|js|xml)$", re.I)
BLOCKED_TEXT = re.compile(r"\b403\b|forbidden|access denied|access blocked|just a moment|cloudflare|captcha|verify you are human|incapsula|imperva", re.I)
REDIRECT_ERROR_TEXT = re.compile(
    r"redirect(?:ed|ion)?(?:\s+(?:error|loop|limit|limit exceeded|too many))?|"
    r"too many redirects|infinite redirect|redirect loop",
    re.I,
)
DEGREE_WORDS = re.compile(
    r"\b(?:master(?:'s|s)?|msc|m\.sc\.?|ma\b|m\.a\.?|llm|m\.eng|meng|"
    r"graduate|postgraduate|second[ -]?cycle|laurea magistrale|maestr[ií]a|"
    r"m[aá]ster|magister|masterstudium|masterstudiengang|masteropleiding|"
    r"masterprogramme|masterprogram)\b", re.I,
)
PROGRAMME_WORDS = re.compile(
    r"\b(?:programme|program|degree|course|curriculum|study option|education|"
    r"formation|opleiding|studiengang|studieprogram|studies|study)\b", re.I,
)
CATEGORY_WORDS = re.compile(
    r"\b(?:all|find|search|explore|list|catalog(?:ue)?|faculty|faculties|school|"
    r"department|subject|discipline|field|area|filter|results?|academic)\b", re.I,
)
RELATED_WORDS = re.compile(
    r"admission|application|apply|deadline|entry requirements?|eligibility|"
    r"language requirements?|documents?|how to apply|required documents?|"
    r"selection criteria|tuition|fees", re.I,
)
WRONG_LEVEL = re.compile(r"\b(?:bachelor|undergraduate|doctoral|doctorate|ph\.?d\.?)\b", re.I)
REJECT_WORDS = re.compile(
    r"\b(?:news|events?|webinars?|open days?|summer schools?|continuing education|"
    r"professional education|education for professionals|information activities|scholarship|housing|accommodation|exchange|"
    r"mobility|alumni|staff|people|vacanc|job|press|privacy|cookie|login|sign in|"
    r"contact|about us|research project|publications?)\b", re.I,
)
NON_PROGRAM_SIGNAL = re.compile(
    r"\b(?:open days?|summer schools?|webinars?|information activities|"
    r"continuing education|education for professionals|professional education)\b",
    re.I,
)
REJECT_PATH = re.compile(
    r"/(?:news|events?|webinars?|research|people|staff|jobs?|vacanc(?:y|ies)|press|"
    r"privacy|cookies?|login|contact|about|alumni|housing|accommodation|scholarships?|search|"
    r"exchange|mobility|publications?)(?:/|$)", re.I,
)
CATEGORY_PATH = re.compile(
    r"/(?:study|studies|education|academic|programmes?|programs?|degrees?|courses?|"
    r"curricul|masters?|graduate|postgraduate|facult(?:y|ies)|schools?|departments?|"
    r"subjects?|disciplines?|fields?|second-cycle)(?:/|$)", re.I,
)
PROGRAM_PATH = re.compile(
    r"/(?:programmes?|programs?|degrees?|courses?|curricul(?:um|a)|study-programmes?|"
    r"study-programs?|masters?|master-degree|second-cycle|laurea-magistrale)"
    r"(?:/[^/?#]+){1,}", re.I,
)
OPAQUE_PROGRAM_PATH = re.compile(
    r"(?:/program\d+\.html$|/course_of_study/[^/?#]+$|"
    r"/oferta-de-masteres/[^/?#]+$|/estudio/ver$|/ProgramHakkinda\.php$|"
    r"/program_detay\.php$|/lisansustu-programlari/\d+$|"
    r"/lisans-ustu-programlar/\d+$|/course/[^/?#]+$|"
    r"/degree-program/[^/?#]+$|/studiengaenge/[^/?#]+-master$)", re.I,
)
SITEMAP_PROGRAM_PATH = re.compile(
    r"(?:/studium/studiengaenge/[^/?#]+-master|"
    r"/degree-program/[^/?#]+-(?:m-sc|m-a|mba|ll-m|mhba|llm-magister)|"
    r"/(?:masters?|master-degree|master-programmes?|master-programs?|"
    r"study-programmes?|study-programs?|degree-programmes?|degree-programs?|"
    r"second-cycle|laurea-magistrale)/(?:[^/?#]+/)*[^/?#]*"
    r"(?:master|masters|msc|m-sc|m-a|mba|llm|ll-m|mhba|magister)[^/?#]*)$",
    re.I,
)
PAGINATION_TEXT = re.compile(r"^(?:next|previous|prev|older|newer|more|load more|show more|view more|\d{1,3}|[>»›→]+)$", re.I)
PAGINATION_QUERY = re.compile(r"^(?:page|p|offset|start|pageNumber|page_num)$", re.I)
GENERIC_CATEGORY = re.compile(
    r"/(?:en|fr|de|it|es|pt|nl|sv|da|fi|no)?/?(?:study|studies|education|programmes?|"
    r"programs?|courses?|degrees?|masters?|graduate|postgraduate|faculties|schools?)?/?$", re.I,
)
PROTOCOL_BOOTSTRAP_PATHS = (
    "/robots.txt",
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap.xml.gz",
)
ROBOTS_SITEMAP_LINE = re.compile(r"^\s*Sitemap\s*:\s*(\S+)\s*(?:#.*)?$", re.I)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def write_json_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%d-%d" % (os.getpid(), threading.get_ident()))
    temporary.write_bytes(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8"))
    os.replace(str(temporary), str(path))


def safe_id(value):
    text = unicodedata.normalize("NFKD", str(value or "unknown"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_")
    return text or "unknown"


def normalize_url(value, base=None):
    try:
        joined = urljoin(base or "", value or "")
        parts = urlsplit(joined)
    except (TypeError, ValueError):
        return ""
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return ""
    query = urlencode([(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_QUERY.match(key)], doseq=True)
    # urllib on Windows rejects non-ASCII request targets. Keep the URL
    # lossless while percent-encoding Unicode path segments before fetching.
    path = quote(parts.path or "/", safe="/%:@-._~!$&'()*+,;=")
    if path != "/":
        path = path.rstrip("/")
    try:
        hostname = parts.hostname.encode("idna").decode("ascii") if parts.hostname else ""
        netloc = hostname
        if parts.port:
            netloc += ":%d" % parts.port
    except (AttributeError, UnicodeError, ValueError):
        netloc = parts.netloc.lower()
    return urlunsplit((parts.scheme.lower(), netloc.lower(), path, query, ""))


def host_of(url):
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def denied_host(host):
    return any(host == item or host.endswith("." + item) for item in DENIED_HOSTS)


def allowed_url(url, domains):
    host = host_of(url)
    if not host or denied_host(host):
        return False
    return any(host == domain or host.endswith("." + domain) or domain.endswith("." + host) for domain in domains if domain)


def normalized_official_domains(target):
    """Return strict host-only domains approved by the upstream verifier."""
    result = []
    for value in target.get("officialDomains", []) or []:
        raw = str(value or "").strip().lower().strip(".")
        if not raw or any(char in raw for char in "/:@?#"):
            continue
        try:
            domain = raw.encode("idna").decode("ascii")
        except UnicodeError:
            continue
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain or denied_host(domain) or not re.match(r"^[a-z0-9.-]+$", domain):
            continue
        if domain not in result:
            result.append(domain)
    return result


def has_verified_official_domains(target):
    """Require an explicit upstream verification result before protocol probing."""
    direct = any(
        str(target.get(key) or "").lower() == "verified"
        for key in ("verificationStatus", "officialVerificationStatus")
    )
    nested = str((target.get("verification") or {}).get("verificationStatus") or "").lower() == "verified"
    return bool((direct or nested) and normalized_official_domains(target))


def allowed_protocol_url(url, domains):
    """Apply a one-way boundary: children of a verified domain are allowed, parents are not."""
    host = host_of(url)
    return bool(host and not denied_host(host) and any(
        host == domain or host.endswith("." + domain) for domain in domains
    ))


def protocol_bootstrap_urls(target):
    """Construct finite protocol roots only from explicitly verified officialDomains."""
    if not has_verified_official_domains(target):
        return []
    return [
        "https://" + domain + path
        for domain in normalized_official_domains(target)
        for path in PROTOCOL_BOOTSTRAP_PATHS
    ]


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def url_hash(url):
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:24]


def decode_html(data, headers):
    charset = None
    if isinstance(headers, Message):
        charset = headers.get_content_charset()
    head = data[:4096].decode("ascii", "ignore")
    if not charset:
        match = re.search(r"charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)", head, re.I)
        charset = match.group(1) if match else None
    for encoding in [charset, "utf-8", "cp1252", "latin-1"]:
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


class CatalogueParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.title = []
        self.text = []
        self.json_ld = []
        self._anchor = None
        self._title_depth = 0
        self._ignored_depth = 0
        self._json_ld_depth = 0
        self._json_ld_parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        lower = tag.lower()
        if lower in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
        if lower == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._json_ld_depth += 1
            self._json_ld_parts = []
        if lower == "title":
            self._title_depth += 1
        if lower == "a" and attrs.get("href"):
            self._anchor = {"href": attrs["href"], "text": [], "rel": attrs.get("rel", ""), "title": attrs.get("title", ""), "aria": attrs.get("aria-label", "")}
        if lower == "link" and attrs.get("href") and re.search(r"\b(?:next|prev)\b", attrs.get("rel", ""), re.I):
            self.links.append({"href": attrs["href"], "text": attrs.get("rel", ""), "rel": attrs.get("rel", ""), "source": "link-rel"})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() in {"script", "style", "noscript", "svg", "title", "a"}:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        lower = tag.lower()
        if lower == "a" and self._anchor is not None:
            self._anchor["text"] = " ".join(self._anchor["text"])
            self._anchor["source"] = "anchor"
            self.links.append(self._anchor)
            self._anchor = None
        if lower == "title" and self._title_depth:
            self._title_depth -= 1
        if lower == "script" and self._json_ld_depth:
            self.json_ld.append("".join(self._json_ld_parts))
            self._json_ld_depth -= 1
            self._json_ld_parts = []
        if lower in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if self._json_ld_depth:
            self._json_ld_parts.append(data)
        if self._title_depth:
            self.title.append(data)
        if not self._ignored_depth:
            value = re.sub(r"\s+", " ", data).strip()
            if value:
                self.text.append(value)
                if self._anchor is not None:
                    self._anchor["text"].append(value)


def parse_html(html):
    parser = CatalogueParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser


def parse_sitemap(data, content_type="", response_url=""):
    """Return a sitemap root type and its loc values without altering raw bytes."""
    payload = data or b""
    if payload[:2] == b"\x1f\x8b":
        try:
            payload = gzip.decompress(payload)
        except (EOFError, OSError):
            return None
    hint = (content_type or "").lower()
    path = urlsplit(response_url or "").path.lower()
    stripped = payload.lstrip()
    if "xml" not in hint and not path.endswith((".xml", ".xml.gz")) and not stripped.startswith((b"<?xml", b"<urlset", b"<sitemapindex")):
        return None
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return None
    root_type = root.tag.rsplit("}", 1)[-1].lower()
    if root_type not in {"urlset", "sitemapindex"}:
        return None
    item_type = "url" if root_type == "urlset" else "sitemap"
    locations = []
    for item in root:
        if item.tag.rsplit("}", 1)[-1].lower() != item_type:
            continue
        for child in item:
            if child.tag.rsplit("}", 1)[-1].lower() == "loc" and child.text:
                value = child.text.strip()
                if value:
                    locations.append(value)
                break
    return {"type": root_type, "locations": locations}


def parse_robots_sitemaps(data, response_url, domains):
    """Extract only official-domain Sitemap directives from a robots.txt body."""
    try:
        text = (data or b"").decode("utf-8-sig", "replace")
    except (AttributeError, UnicodeDecodeError):
        return []
    result = []
    seen = set()
    for line in text.splitlines():
        match = ROBOTS_SITEMAP_LINE.match(line)
        if not match:
            continue
        url = normalize_url(match.group(1), response_url)
        if not url or not allowed_protocol_url(url, domains) or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def classify_sitemap_program_url(value, source_url, domains, protocol_probe=False):
    """Accept only unambiguous official master's detail paths from a sitemap."""
    url = normalize_url(value, source_url)
    boundary_check = allowed_protocol_url if protocol_probe else allowed_url
    if not url or not boundary_check(url, domains):
        return None
    try:
        path = unquote(urlsplit(url).path).rstrip("/")
    except (UnicodeDecodeError, ValueError):
        return None
    if not SITEMAP_PROGRAM_PATH.search(path):
        return None
    return {
        "url": url, "text": "", "kind": "program", "score": 90,
        "source": "sitemap",
        "protocolProbe": bool(protocol_probe),
        "sourceUrlRole": "discovery-only" if protocol_probe else "catalog-discovery",
        "eligibleAsProgramEvidence": False if protocol_probe else True,
    }


def path_depth(url):
    try:
        return len([part for part in urlsplit(url).path.split("/") if part])
    except ValueError:
        return 0


def program_prefixes(program_urls):
    by_host = {}
    for url in program_urls:
        clean = normalize_url(url)
        if not clean:
            continue
        parts = urlsplit(clean)
        segments = [part for part in parts.path.split("/") if part]
        if not segments:
            continue
        by_host.setdefault(parts.netloc, []).append(segments[:-1])
    prefixes = []
    for host, groups in by_host.items():
        common = []
        for values in zip(*groups):
            if len(set(values)) != 1:
                break
            common.append(values[0])
        if common:
            prefixes.append("https://" + host + "/" + "/".join(common) + "/")
    return prefixes


def classify_link(raw, source_url, domains, prefixes):
    url = normalize_url(raw.get("href"), source_url)
    if not url or not allowed_url(url, domains) or ASSET_PATH.search(urlsplit(url).path):
        return None
    if url == normalize_url(source_url):
        return None
    text = re.sub(r"\s+", " ", " ".join(str(raw.get(key) or "") for key in ("text", "title", "aria"))).strip()[:500]
    try:
        path_text = unquote(urlsplit(url).path + "?" + urlsplit(url).query)
    except (UnicodeDecodeError, ValueError):
        path_text = url
    semantic = text + " " + path_text
    if NON_PROGRAM_SIGNAL.search(semantic):
        return None
    if REJECT_PATH.search(path_text) or (REJECT_WORDS.search(semantic) and not DEGREE_WORDS.search(semantic)):
        return None
    query_keys = [key for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)]
    pagination = bool(re.search(r"\b(?:next|prev)\b", str(raw.get("rel") or ""), re.I) or any(PAGINATION_QUERY.match(key) for key in query_keys) or PAGINATION_TEXT.match(text))
    if pagination:
        return {"url": url, "text": text, "kind": "pagination", "score": 20, "source": raw.get("source", "anchor")}
    degree = bool(DEGREE_WORDS.search(semantic))
    programme = bool(PROGRAMME_WORDS.search(semantic))
    opaque_detail = bool(OPAQUE_PROGRAM_PATH.search(urlsplit(url).path))
    detail_path = bool(opaque_detail or PROGRAM_PATH.search(path_text))
    prefix_hit = any(url.startswith(prefix) and len(url) > len(prefix) for prefix in prefixes)
    category = bool(CATEGORY_WORDS.search(semantic) or CATEGORY_PATH.search(path_text))
    if RELATED_WORDS.search(semantic) and not degree:
        return None
    score = (7 if degree else 0) + (4 if programme else 0) + (5 if detail_path else 0) + (5 if prefix_hit else 0) + (2 if category else 0)
    if RELATED_WORDS.search(semantic):
        score -= 3
    if WRONG_LEVEL.search(semantic) and not DEGREE_WORDS.search(text):
        return None
    if opaque_detail and len(text) >= 5:
        kind = "program"
    elif (degree and programme and (detail_path or prefix_hit)) or (degree and (detail_path or prefix_hit)):
        kind = "program"
    elif prefix_hit and not GENERIC_CATEGORY.search(urlsplit(url).path):
        kind = "program"
    elif category and (degree or programme):
        kind = "category"
    elif degree and path_depth(url) >= path_depth(source_url):
        kind = "category"
    else:
        return None
    return {"url": url, "text": text, "kind": kind, "score": score, "source": raw.get("source", "anchor")}


def json_ld_links(parser):
    result = []

    def walk(node, depth=0):
        if depth > 12 or node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        types = node.get("@type") or []
        if isinstance(types, str):
            types = [types]
        if set(types) & {"Course", "EducationalOccupationalProgram", "ItemList", "CollectionPage"}:
            result.append({"href": node.get("url") or node.get("@id"), "text": node.get("name") or node.get("headline") or "", "source": "json-ld"})
        for key in ("item", "itemListElement", "mainEntity", "hasCourse", "@graph"):
            walk(node.get(key), depth + 1)

    for raw in parser.json_ld:
        try:
            walk(json.loads(raw))
        except (TypeError, ValueError):
            continue
    return result


class HostThrottle:
    def __init__(self, delay):
        self.delay = delay
        self.lock = threading.Lock()
        self.last = {}

    def wait(self, host):
        if not self.delay:
            return
        with self.lock:
            remaining = self.delay - (time.monotonic() - self.last.get(host, 0))
            if remaining > 0:
                time.sleep(remaining)
            self.last[host] = time.monotonic()


class Fetcher:
    def __init__(self, timeout, retries, delay):
        self.timeout = timeout
        self.retries = retries
        self.throttle = HostThrottle(delay)
        self.local = threading.local()

    def opener(self):
        if not hasattr(self.local, "opener"):
            handlers = [ProxyHandler({})]
            try:
                import certifi

                context = ssl.create_default_context(cafile=certifi.where())
                handlers.append(HTTPSHandler(context=context))
            except (ImportError, OSError, ssl.SSLError):
                pass
            self.local.opener = build_opener(*handlers)
        return self.local.opener

    def fetch(self, url):
        error = None
        for attempt in range(1, self.retries + 2):
            self.throttle.wait(host_of(url))
            request = Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.2",
                "Accept-Language": "en,en-US;q=0.9,*;q=0.2",
            })
            started = time.monotonic()
            try:
                with self.opener().open(request, timeout=self.timeout) as response:
                    data = response.read()
                    return {
                        "ok": 200 <= response.status < 400,
                        "status": response.status,
                        "url": normalize_url(response.geturl()) or url,
                        "headers": dict(response.headers.items()),
                        "messageHeaders": response.headers,
                        "data": data,
                        "elapsedMs": round((time.monotonic() - started) * 1000),
                        "attempts": attempt,
                    }
            except HTTPError as exc:
                body = b""
                try:
                    body = exc.read()
                except Exception:
                    pass
                error = {
                    "ok": False, "status": exc.code, "url": normalize_url(exc.geturl()) or url,
                    "headers": dict(exc.headers.items()) if exc.headers else {}, "messageHeaders": exc.headers,
                    "data": body, "elapsedMs": round((time.monotonic() - started) * 1000),
                    "attempts": attempt, "error": str(exc),
                }
                blocked_body = bool(BLOCKED_TEXT.search(body[:12000].decode("utf-8", "ignore")))
                transient_status = exc.code in {408, 425, 429} or 500 <= exc.code < 600
                if blocked_body or not transient_status:
                    return error
            except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
                error = {
                    "ok": False, "status": None, "url": url, "headers": {}, "messageHeaders": None,
                    "data": b"", "elapsedMs": round((time.monotonic() - started) * 1000),
                    "attempts": attempt, "error": str(exc),
                }
            if attempt <= self.retries:
                time.sleep(min(4, 0.5 * (2 ** (attempt - 1))))
        return error


def write_raw_response(directory, url, response, kind):
    directory.mkdir(parents=True, exist_ok=True)
    suffix = ".html.gz" if "html" in (response.get("headers", {}).get("Content-Type", "").lower()) else ".bin.gz"
    filename = url_hash(url) + suffix
    path = directory / filename
    temporary = path.with_name(path.name + ".tmp-%d-%d" % (os.getpid(), threading.get_ident()))
    with gzip.open(str(temporary), "wb", compresslevel=9) as handle:
        handle.write(response.get("data") or b"")
    os.replace(str(temporary), str(path))
    return filename


def initial_manifest(target):
    now = utc_now()
    return {
        "schemaVersion": 1,
        "universityId": target["universityId"],
        "universityName": target["name"],
        "country": target.get("country", ""),
        "region": target.get("region", ""),
        "officialDomains": target.get("officialDomains", []),
        "indexUrl": target.get("indexUrl", ""),
        "discoveryStrategy": "recursive-catalog",
        "status": "pending",
        "discovery": {
            "status": "pending", "queue": [], "visited": {},
            "protocolBootstrap": {
                "enabled": False, "seeded": [], "robotsSitemaps": [],
            },
            "programCandidates": {}, "categoryCandidates": {}, "paginationCandidates": {},
            "evidenceCandidates": {}, "apiEndpoints": target.get("apiEndpoints", []),
            "searchAttempted": False, "searchCandidates": [], "selectedSearchResult": None,
            "startedAt": None, "completedAt": None, "stoppedReason": None,
        },
        "pages": {},
        "counts": {"catalogsVisited": 0, "programCandidates": 0, "captured": 0, "blocked": 0, "errors": 0, "pending": 0},
        "createdAt": now, "updatedAt": now,
    }


def migrate_manifest(manifest, target):
    manifest.setdefault("schemaVersion", 1)
    manifest.setdefault("discovery", {})
    discovery = manifest["discovery"]
    for key, default in (
        ("queue", []), ("visited", {}), ("programCandidates", {}),
        ("categoryCandidates", {}), ("paginationCandidates", {}),
        ("evidenceCandidates", {}), ("apiEndpoints", []),
        ("searchCandidates", []),
    ):
        discovery.setdefault(key, default)
    discovery.setdefault("protocolBootstrap", {
        "enabled": False, "seeded": [], "robotsSitemaps": [],
    })
    manifest.setdefault("pages", {})
    domains = list(manifest.get("officialDomains") or [])
    for domain in target.get("officialDomains") or []:
        if domain and domain not in domains:
            domains.append(domain)
    for url in [target.get("indexUrl", "")] + target.get("catalogPages", []) + target.get("programUrls", []):
        host = host_of(url)
        if host and not denied_host(host) and host not in domains:
            domains.append(host)
    manifest["officialDomains"] = domains
    return manifest


def update_counts(manifest):
    pages = list(manifest.get("pages", {}).values())
    for page in pages:
        if page.get("status") == "loading":
            page["status"] = "pending"
    manifest["counts"] = {
        "catalogsVisited": len(manifest["discovery"].get("visited", {})),
        "programCandidates": len(manifest["discovery"].get("programCandidates", {})),
        "captured": sum(page.get("status") == "captured" for page in pages),
        "blocked": sum(page.get("status") == "blocked" for page in pages),
        "errors": sum(page.get("status") == "error" for page in pages),
        "pending": sum(page.get("status") == "pending" for page in pages),
    }
    manifest["updatedAt"] = utc_now()


def response_record(response, filename, html, parser, kind):
    text = " ".join(parser.text) if parser else ""
    blocked = bool(BLOCKED_TEXT.search(text[:3000])) or response.get("status") in {401, 403}
    dynamic_shell = bool(response.get("ok") and "html" in response.get("headers", {}).get("Content-Type", "").lower() and len(text) < 400)
    return {
        "status": "blocked" if blocked else ("captured" if response.get("ok") else "error"),
        "captureMethod": "static-http",
        "kind": kind,
        "file": filename,
        "responseUrl": response.get("url"),
        "statusCode": response.get("status"),
        "contentType": response.get("headers", {}).get("Content-Type") or response.get("headers", {}).get("content-type"),
        "bytes": len(response.get("data") or b""),
        "sha256": sha256(response.get("data") or b""),
        "textLength": len(text),
        "documentTitle": " ".join(parser.title).strip()[:500] if parser else "",
        "blocked": blocked,
        "dynamicShell": dynamic_shell,
        "elapsedMs": response.get("elapsedMs"),
        "attempts": response.get("attempts", 1),
        "error": response.get("error"),
        "capturedAt": utc_now(),
    }


def add_candidate(bucket, link, source_url):
    existing = bucket.get(link["url"])
    value = {**link, "sourceUrl": source_url}
    if not existing or existing.get("score", 0) < value.get("score", 0):
        bucket[link["url"]] = value


def discover_catalogues(target, manifest, output_dir, fetcher, args):
    discovery = manifest["discovery"]
    domains = manifest["officialDomains"]
    prefixes = program_prefixes(target.get("programUrls", []))
    queue = deque()
    queued = set()
    bootstrap_seeded_now = False
    for item in discovery.get("queue", []):
        url = normalize_url(item.get("url"))
        if url:
            queue.append({**item, "url": url})
            queued.add(url)
    for url in [target.get("indexUrl", "")] + target.get("catalogPages", []):
        clean = normalize_url(url)
        if clean and clean not in queued and clean not in discovery["visited"]:
            queue.append({"url": clean, "kind": "catalog", "depth": 0, "sourceUrl": None})
            queued.add(clean)
    if getattr(args, "protocol_bootstrap", False):
        protocol = discovery.setdefault("protocolBootstrap", {})
        protocol["enabled"] = True
        protocol.setdefault("seeded", [])
        protocol.setdefault("robotsSitemaps", [])
        for url in protocol_bootstrap_urls(target):
            clean = normalize_url(url)
            if clean not in protocol["seeded"]:
                protocol["seeded"].append(clean)
            if clean and clean not in queued and clean not in discovery["visited"]:
                kind = "robots" if urlsplit(clean).path.lower() == "/robots.txt" else "sitemap-probe"
                queue.append({
                    "url": clean, "kind": kind, "depth": 0,
                    "sitemapDepth": 0, "sourceUrl": None, "protocolProbe": True,
                })
                queued.add(clean)
                bootstrap_seeded_now = True
    for raw in target.get("programUrls", []):
        url = normalize_url(raw if isinstance(raw, str) else raw.get("url") or raw.get("href"))
        if url and allowed_url(url, domains):
            discovery["programCandidates"].setdefault(url, {"url": url, "text": "", "kind": "program", "score": 100, "source": "seed", "sourceUrl": target.get("indexUrl")})

    discovery["status"] = "running"
    discovery["startedAt"] = discovery.get("startedAt") or utc_now()
    processed = 0
    while queue and len(discovery["visited"]) < args.max_catalog_pages and processed < args.max_catalog_pages_per_run:
        item = queue.popleft()
        url = normalize_url(item["url"])
        if not url or url in discovery["visited"]:
            continue
        processed += 1
        response = fetcher.fetch(url)
        response_url = response.get("url") or url
        protocol_probe = bool(item.get("protocolProbe"))
        protocol_response_allowed = not protocol_probe or allowed_protocol_url(
            response_url, normalized_official_domains(target),
        )
        content_type = response.get("headers", {}).get("Content-Type") or response.get("headers", {}).get("content-type") or ""
        sitemap = parse_sitemap(response.get("data") or b"", content_type, response_url) if protocol_response_allowed else None
        is_robots = item.get("kind") == "robots"
        robots_sitemaps = parse_robots_sitemaps(
            response.get("data") or b"", response_url, normalized_official_domains(target),
        ) if is_robots and protocol_response_allowed else []
        html = "" if sitemap or is_robots else decode_html(response.get("data") or b"", response.get("messageHeaders"))
        parser = parse_html(html) if html else None
        filename = write_raw_response(output_dir / "catalogs", url, response, "catalog") if response.get("data") else None
        record_kind = "sitemap" if sitemap else item.get("kind", "catalog")
        record = response_record(response, "catalogs/" + filename if filename else None, html, parser, record_kind)
        record.update({
            "depth": item.get("depth", 0), "sourceUrl": item.get("sourceUrl"),
            "protocolProbe": protocol_probe,
            "protocolResponseAllowed": protocol_response_allowed,
            "eligibleAsProgramEvidence": not protocol_probe,
        })
        if sitemap:
            record.update({"sitemapType": sitemap["type"], "sitemapLocations": len(sitemap["locations"])})
        if is_robots:
            record["robotsSitemaps"] = len(robots_sitemaps)
        discovery["visited"][url] = record
        if is_robots and record["status"] == "captured":
            protocol = discovery.setdefault("protocolBootstrap", {})
            recorded = protocol.setdefault("robotsSitemaps", [])
            for child in robots_sitemaps:
                if child not in recorded:
                    recorded.append(child)
                if child in queued or child in discovery["visited"]:
                    continue
                queue.append({
                    "url": child, "kind": "sitemap", "depth": 0,
                    "sitemapDepth": 0, "sourceUrl": url, "protocolProbe": True,
                })
                queued.add(child)
        if sitemap and record["status"] == "captured":
            sitemap_depth = item.get("sitemapDepth", 0)
            if sitemap["type"] == "sitemapindex" and sitemap_depth < getattr(args, "max_sitemap_depth", 3):
                for location in sitemap["locations"]:
                    child = normalize_url(location, response_url)
                    boundary_check = allowed_protocol_url if protocol_probe else allowed_url
                    boundary_domains = normalized_official_domains(target) if protocol_probe else domains
                    if not child or not boundary_check(child, boundary_domains) or child in queued or child in discovery["visited"]:
                        continue
                    queue.append({
                        "url": child, "kind": "sitemap", "depth": item.get("depth", 0),
                        "sitemapDepth": sitemap_depth + 1, "sourceUrl": url,
                        "protocolProbe": bool(item.get("protocolProbe")),
                    })
                    queued.add(child)
            elif sitemap["type"] == "urlset":
                for location in sitemap["locations"]:
                    link = classify_sitemap_program_url(
                        location, response_url,
                        normalized_official_domains(target) if protocol_probe else domains,
                        protocol_probe=protocol_probe,
                    )
                    if link and len(discovery["programCandidates"]) < args.max_candidates:
                        add_candidate(discovery["programCandidates"], link, url)
        elif parser and record["status"] == "captured" and not record["dynamicShell"]:
            links = parser.links + json_ld_links(parser)
            for raw_link in links:
                link = classify_link(raw_link, response.get("url") or url, domains, prefixes)
                if not link:
                    continue
                kind = link["kind"]
                if kind == "program":
                    if len(discovery["programCandidates"]) < args.max_candidates:
                        add_candidate(discovery["programCandidates"], link, url)
                    continue
                bucket = discovery["paginationCandidates"] if kind == "pagination" else discovery["categoryCandidates"]
                add_candidate(bucket, link, url)
                depth = item.get("depth", 0) if kind == "pagination" else item.get("depth", 0) + 1
                if depth <= args.max_depth and link["url"] not in queued and link["url"] not in discovery["visited"]:
                    queue.append({"url": link["url"], "kind": kind, "depth": depth, "sourceUrl": url})
                    queued.add(link["url"])
        discovery["queue"] = list(queue)
        update_counts(manifest)
        write_json_atomic(output_dir / "manifest.json", manifest)

    discovery["queue"] = list(queue)
    candidate_count = len(discovery["programCandidates"])
    blocked_catalogs = [row for row in discovery["visited"].values() if row.get("status") == "blocked" or row.get("dynamicShell")]
    if queue:
        discovery["status"] = "partial"
        discovery["stoppedReason"] = "catalog-run-budget" if processed >= args.max_catalog_pages_per_run else "max-catalog-pages"
    elif not candidate_count and getattr(args, "protocol_bootstrap", False) and not bootstrap_seeded_now and has_verified_official_domains(target):
        discovery["status"] = "complete"
        discovery["stoppedReason"] = "protocol-bootstrap-already-visited"
    elif not candidate_count:
        discovery["status"] = "partial"
        discovery["stoppedReason"] = "dynamic-or-blocked-catalog" if blocked_catalogs else "no-program-candidates"
    else:
        discovery["status"] = "complete"
        discovery["stoppedReason"] = None
    discovery["completedAt"] = utc_now()
    materialize_program_pages(manifest)


def materialize_program_pages(manifest):
    """Make interrupted discovery candidates available to capture-only passes."""
    for candidate in manifest["discovery"].get("programCandidates", {}).values():
        url = normalize_url(candidate.get("url"))
        if url:
            manifest["pages"].setdefault(url, {
                "status": "pending", "kind": "program",
                "text": candidate.get("text", ""),
                "sourceUrl": candidate.get("sourceUrl"), "attempts": 0,
            })


def discover_evidence(parser, page_url, domains, max_links):
    result = []
    seen = set()
    for raw in parser.links:
        url = normalize_url(raw.get("href"), page_url)
        text = re.sub(r"\s+", " ", " ".join(str(raw.get(key) or "") for key in ("text", "title", "aria"))).strip()[:500]
        semantic = text + " " + unquote(urlsplit(url).path + "?" + urlsplit(url).query) if url else text
        if not url or url in seen or not allowed_url(url, domains) or not RELATED_WORDS.search(semantic) or WRONG_LEVEL.search(semantic):
            continue
        seen.add(url)
        score = (4 if re.search(r"deadline|requirements?|eligibility|documents?", semantic, re.I) else 0) + (2 if re.search(r"apply|application|admission", semantic, re.I) else 0)
        if re.search(r"deadlines?|closing dates?|application dates?", semantic, re.I):
            evidence_type = "deadline"
        elif re.search(r"required documents?|documents? required|application documents?|materials?", semantic, re.I):
            evidence_type = "documents"
        elif re.search(r"language|english|ielts|toefl", semantic, re.I):
            evidence_type = "language"
        elif re.search(r"requirements?|eligibility|selection criteria", semantic, re.I):
            evidence_type = "requirements"
        else:
            evidence_type = "application"
        result.append({"url": url, "text": text, "score": score, "evidenceType": evidence_type, "sourceUrl": page_url})
    ordered = sorted(result, key=lambda item: (
        {"deadline": 0, "requirements": 1, "documents": 2, "language": 3, "application": 4}.get(item["evidenceType"], 5),
        -item["score"], item["url"],
    ))
    selected = []
    seen_types = set()
    for item in ordered:
        if item["evidenceType"] in seen_types:
            continue
        selected.append(item)
        seen_types.add(item["evidenceType"])
        if len(selected) >= max_links:
            break
    return selected


def response_status_code(record):
    """Read HTTP status from current and legacy raw manifest records."""
    for key in ("statusCode", "httpStatus"):
        value = record.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def is_transient_retryable(record):
    """Return whether a failed raw manifest record is safe to retry.

    The manifest status remains authoritative for blocked/WAF records. Missing
    HTTP status means the request failed at the transport layer; otherwise the
    retry allowlist is limited to 408/425/429 and 5xx responses.
    """
    if record.get("status") != "error" or record.get("blocked"):
        return False
    evidence = " ".join(str(record.get(key) or "") for key in (
        "error", "documentTitle", "responseUrl", "finalUrl",
    ))
    if BLOCKED_TEXT.search(evidence) or REDIRECT_ERROR_TEXT.search(evidence):
        return False
    status_code = response_status_code(record)
    if status_code is None:
        return True
    if 300 <= status_code < 400:
        return False
    return status_code in {408, 425, 429} or 500 <= status_code < 600


def capture_pages(target, manifest, output_dir, fetcher, args):
    domains = manifest["officialDomains"]
    eligible = []
    for url, page in manifest["pages"].items():
        status = page.get("status")
        if getattr(args, "retry_transient_only", False):
            if not is_transient_retryable(page):
                continue
        elif status == "captured":
            continue
        elif status in {"error", "blocked"} and not args.retry_errors:
            continue
        eligible.append((url, page))
        if len(eligible) >= args.max_detail_pages_per_run:
            break

    def fetch_one(item):
        url, page = item
        return url, page, fetcher.fetch(url)

    with ThreadPoolExecutor(max_workers=min(args.detail_workers, max(1, len(eligible)))) as pool:
        futures = [pool.submit(fetch_one, item) for item in eligible]
        for future in as_completed(futures):
            url, page, response = future.result()
            html = decode_html(response.get("data") or b"", response.get("messageHeaders"))
            parser = parse_html(html) if html else None
            filename = write_raw_response(output_dir / "pages", url, response, page.get("kind", "program")) if response.get("data") else None
            record = response_record(response, "pages/" + filename if filename else None, html, parser, page.get("kind", "program"))
            page.update(record)
            if parser and record["status"] == "captured" and page.get("kind", "program") == "program":
                for related in discover_evidence(parser, response.get("url") or url, domains, args.max_evidence_links):
                    evidence_url = related["url"]
                    manifest["discovery"]["evidenceCandidates"].setdefault(evidence_url, related)
                    manifest["pages"].setdefault(evidence_url, {"status": "pending", "kind": "evidence", "text": related["text"], "sourceUrl": url, "attempts": 0})
            update_counts(manifest)
            write_json_atomic(output_dir / "manifest.json", manifest)


def finalize(manifest):
    update_counts(manifest)
    dynamic = any(page.get("dynamicShell") for page in manifest["pages"].values())
    if manifest["discovery"].get("status") == "complete" and manifest["counts"]["programCandidates"] and not manifest["counts"]["pending"] and not manifest["counts"]["errors"] and not manifest["counts"]["blocked"] and not dynamic:
        manifest["status"] = "raw-complete"
    else:
        manifest["status"] = "raw-partial"
    manifest["completedAt"] = utc_now()


def crawl_university(target, output_root, fetcher, args, index, total):
    output_dir = output_root / safe_id(target["universityId"])
    manifest_file = output_dir / "manifest.json"
    manifest = migrate_manifest(load_json(manifest_file, initial_manifest(target)), target)
    if manifest.get("status") == "raw-complete" and not args.force_discovery and not args.retry_errors and not getattr(args, "retry_transient_only", False) and not getattr(args, "protocol_bootstrap", False):
        return {"universityId": target["universityId"], "name": target["name"], "skipped": True, "counts": manifest["counts"], "status": manifest["status"]}
    if args.force_discovery:
        manifest["discovery"]["status"] = "pending"
        manifest["discovery"]["queue"] = []
        manifest["discovery"]["visited"] = {}
        manifest["discovery"]["categoryCandidates"] = {}
        manifest["discovery"]["paginationCandidates"] = {}
    write_json_atomic(manifest_file, manifest)
    if not args.capture_only and (manifest["discovery"].get("status") != "complete" or args.force_discovery or getattr(args, "protocol_bootstrap", False)):
        discover_catalogues(target, manifest, output_dir, fetcher, args)
    if not args.discovery_only:
        materialize_program_pages(manifest)
        capture_pages(target, manifest, output_dir, fetcher, args)
    finalize(manifest)
    write_json_atomic(manifest_file, manifest)
    return {"universityId": target["universityId"], "name": target["name"], "skipped": False, "counts": manifest["counts"], "status": manifest["status"], "discovery": manifest["discovery"].get("status"), "stoppedReason": manifest["discovery"].get("stoppedReason")}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--university", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--worker-index", type=int, default=0)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--university-workers", type=int, default=10)
    parser.add_argument("--detail-workers", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--host-delay", type=float, default=0.15)
    parser.add_argument("--max-catalog-pages", type=int, default=350)
    parser.add_argument("--max-catalog-pages-per-run", type=int, default=80)
    parser.add_argument("--max-detail-pages-per-run", type=int, default=200)
    parser.add_argument("--max-candidates", type=int, default=2500)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--max-sitemap-depth", type=int, default=3)
    parser.add_argument(
        "--protocol-bootstrap", action="store_true",
        help="probe robots.txt and common sitemap roots for verified officialDomains",
    )
    parser.add_argument("--max-evidence-links", type=int, default=4)
    parser.add_argument("--discovery-only", action="store_true")
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--only-unstarted", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument(
        "--retry-transient-only", action="store_true",
        help="retry only transport failures, HTTP 408/425/429, and 5xx page records",
    )
    parser.add_argument("--force-discovery", action="store_true")
    return parser.parse_args(argv)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parse_args()
    if args.discovery_only and args.capture_only:
        raise SystemExit("--discovery-only and --capture-only are mutually exclusive")
    if args.retry_errors and args.retry_transient_only:
        raise SystemExit("--retry-errors and --retry-transient-only are mutually exclusive")
    if args.worker_count < 1 or args.worker_index < 0 or args.worker_index >= args.worker_count:
        raise SystemExit("worker index must be in [0, worker-count)")
    targets = load_json(args.targets.resolve(), [])
    if args.university:
        selected = set(args.university)
        targets = [target for target in targets if target["universityId"] in selected]
    targets = [target for index, target in enumerate(targets) if index % args.worker_count == args.worker_index]
    targets = targets[args.offset:]
    if args.limit is not None:
        targets = targets[:args.limit]
    if not targets:
        raise SystemExit("no targets selected")
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if args.only_unstarted:
        def is_unstarted(target):
            manifest_file = output_root / safe_id(target["universityId"]) / "manifest.json"
            manifest = load_json(manifest_file, None)
            if not manifest:
                return True
            discovery = manifest.get("discovery") or {}
            return not discovery.get("visited") and not discovery.get("programCandidates") and not manifest.get("pages")

        targets = [target for target in targets if is_unstarted(target)]
    if not targets:
        print("[static-raw] no unstarted targets", flush=True)
        return
    fetcher = Fetcher(args.timeout, args.retries, args.host_delay)
    started = time.monotonic()
    print("[static-raw] selected=%d university-workers=%d detail-workers=%d" % (len(targets), args.university_workers, args.detail_workers), flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=args.university_workers) as pool:
        futures = {pool.submit(crawl_university, target, output_root, fetcher, args, index + 1, len(targets)): target for index, target in enumerate(targets)}
        for completed, future in enumerate(as_completed(futures), 1):
            target = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"universityId": target["universityId"], "name": target["name"], "status": "fatal", "error": repr(exc)}
            results.append(result)
            counts = result.get("counts", {})
            print("[static-raw] %d/%d %s status=%s catalog=%s candidates=%s captured=%s pending=%s error=%s" % (
                completed, len(targets), result["name"], result.get("status"), counts.get("catalogsVisited", 0),
                counts.get("programCandidates", 0), counts.get("captured", 0), counts.get("pending", 0),
                result.get("error", ""),
            ), flush=True)
    summary = {
        "generatedAt": utc_now(), "elapsedSeconds": round(time.monotonic() - started, 1),
        "selected": len(targets), "statuses": dict(Counter(result.get("status") for result in results)),
        "results": sorted(results, key=lambda item: item["name"]),
    }
    write_json_atomic(output_root / ("_static_run_worker_%d.json" % args.worker_index), summary)
    print("[static-raw] done elapsed=%.1fs statuses=%s" % (summary["elapsedSeconds"], summary["statuses"]), flush=True)


if __name__ == "__main__":
    main()
