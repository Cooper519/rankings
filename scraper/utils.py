"""RankingSelect 爬虫共享工具(纯 stdlib,无需 pip 安装)。

使用 urllib 走系统/环境代理;在用户机器直连环境同样可用。
设置 HTTP_PROXY / HTTPS_PROXY 环境变量即可走代理(本机 Clash 在 127.0.0.1:7897)。
"""
from __future__ import annotations
import gzip
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
import zlib
from typing import Any

TOPN = 500

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 RankingSelect/0.1")

SOURCE_YEAR = {"qs": 2026, "the": 2026, "arwu": 2025, "usnews": 2025, "csrankings": 2026}

# gzip magic bytes;部分端点(Wayback id_ 快照)压缩 body 但不回 Content-Encoding,按此兜底识别。
GZIP_MAGIC = bytes([0x1F, 0x8B])


class _Resp:
    """轻量 requests 风格响应封装(自动处理 gzip/deflate 解压)。"""
    def __init__(self, data: bytes, status: int, headers: dict | None = None):
        self._raw = data
        self.status_code = status
        self.headers = headers or {}

    def _decompress(self) -> bytes:
        enc = (self.headers.get("Content-Encoding") or "").lower()
        raw = self._raw
        if enc == "gzip" or raw[:2] == GZIP_MAGIC:
            try:
                return gzip.decompress(raw)
            except OSError:
                return gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        if enc == "deflate":
            try:
                return zlib.decompress(raw)
            except zlib.error:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw

    @property
    def text(self) -> str:
        return self._decompress().decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.text)


def _make_opener() -> urllib.request.OpenerDirector:
    proxies: dict[str, str] = {}
    for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        v = os.environ.get(k)
        if v:
            key = "https" if k.lower().startswith("https") else "http"
            proxies[key] = v
    handler = urllib.request.ProxyHandler(proxies)
    opener = urllib.request.build_opener(handler)
    opener.addheaders = [("User-Agent", UA), ("Accept-Language", "en-US,en;q=0.9")]
    return opener


OPENER = _make_opener()


def fetch(url: str, headers: dict[str, str] | None = None) -> _Resp:
    """带重试与限速的 GET(自动声明可处理 gzip/deflate 并解压)。"""
    base = {"Accept-Encoding": "gzip, deflate"}
    base.update(headers or {})
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=base)
            r = OPENER.open(req, timeout=30)
            data = r.read()
            hdrs = {k: v for k, v in r.headers.items()}
            time.sleep(1.0)  # 限速 1 req/s
            return _Resp(data, r.status, hdrs)
        except urllib.error.HTTPError as e:
            body = e.read()
            hdrs = {k: v for k, v in e.headers.items()}
            time.sleep(1.0)
            return _Resp(body, e.code, hdrs)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            print(f"  retry {attempt + 1}/3: {e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"抓取失败 {url}: {last}")


def write_json(path, data: Any) -> None:
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 用字节写出,确保无 BOM(前端 JSON.parse 对 BOM 敏感)
    n = len(data) if isinstance(data, list) else len(data)
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    print(f"  写出 -> {path}  ({n} 条)")


def slug(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    s = re.sub(r"[\s\-]+", "_", s).strip("_").lower()
    return f"u_{s}"


def first_int(s) -> int | None:
    m = re.search(r"\d+", str(s))
    return int(m.group()) if m else None


def top_n(items: list[dict], key: str = "rank", n: int = TOPN) -> list[dict]:
    def rkey(x: dict) -> tuple:
        v = first_int(x.get(key))
        return (0, v if v is not None else 99999)
    return sorted(items, key=rkey)[:n]
