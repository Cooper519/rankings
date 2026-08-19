import urllib.request, gzip, io, re, json, sys
sys.stdout.reconfigure(encoding='utf-8')
proxy = urllib.request.ProxyHandler({'http':'http://127.0.0.1:7897','https':'http://127.0.0.1:7897'})
op = urllib.request.build_opener(proxy)
hdr = {'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36','Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8','Accept-Language':'en-US,en;q=0.9','Accept-Encoding':'gzip, deflate'}

def get(url, timeout=40):
    req = urllib.request.Request(url, headers=hdr)
    r = op.open(req, timeout=timeout)
    raw = r.read()
    if raw[:2]==b'\x1f\x8b': raw = gzip.decompress(raw)
    elif raw[:2]==b'\x78\x9c': import zlib; raw=zlib.decompress(raw)
    return r.status, raw.decode('utf-8','replace')

# USNews live page 1
try:
    s,html = get('https://www.usnews.com/education/best-global-universities/rankings?page=1')
    has_state = "__PAGE_CONTEXT_QUERY_STATE__" in html
    m = re.search(r'"total_count"\s*:\s*(\d+)', html)
    print(f'USNews p1: status={s} len={len(html)} has_state={has_state} total_count={m.group(1) if m else "NA"}')
except Exception as e:
    print(f'USNews p1 ERROR: {type(e).__name__}: {e}')

# QS live
try:
    s,html = get('https://www.topuniversities.com/world-university-rankings')
    cf = 'cf-' in html.lower() or 'cloudflare' in html.lower() or 'challenge' in html.lower()
    print(f'QS live: status={s} len={len(html)} cf_marker={cf}')
    # look for ranking data endpoints
    ends = re.findall(r'/sites/default/files/qs-rankings-data/[^\s"<>]+', html)
    print(f'  data endpoints found: {ends[:3]}')
except Exception as e:
    print(f'QS live ERROR: {type(e).__name__}: {e}')
