import re
p = "scraper/utils.py"
src = open(p, encoding="utf-8").read()
old = '''    def _decompress(self) -> bytes:
        enc = (self.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            try:
                return gzip.decompress(self._raw)
            except OSError:
                return gzip.GzipFile(fileobj=io.BytesIO(self._raw)).read()
        if enc == "deflate":
            try:
                return zlib.decompress(self._raw)
            except zlib.error:
                return zlib.decompress(self._raw, -zlib.MAX_WBITS)
        return self._raw'''
new = (
"    def _decompress(self) -> bytes:\n"
"        enc = (self.headers.get('Content-Encoding') or '').lower()\n"
"        raw = self._raw\n"
"        # 部分端点(如 Wayback Machine id_ 快照)压缩 body 但不回 Content-Encoding,按 magic bytes 兜底识别 gzip。\n"
"        gz_magic = b'" + "\\x1f\\x8b" + "'\n"
"        if enc == 'gzip' or raw[:2] == gz_magic:\n"
"            try:\n"
"                return gzip.decompress(raw)\n"
"            except OSError:\n"
"                return gzip.GzipFile(fileobj=io.BytesIO(raw)).read()\n"
"        if enc == 'deflate':\n"
"            try:\n"
"                return zlib.decompress(raw)\n"
"            except zlib.error:\n"
"                return zlib.decompress(raw, -zlib.MAX_WBITS)\n"
"        return raw"
)
assert old in src, "anchor not found"
src = src.replace(old, new)
open(p, "w", encoding="utf-8").write(src)
print("patched utils.py _decompress")
