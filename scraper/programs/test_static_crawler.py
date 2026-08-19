import gzip
from urllib.error import HTTPError
from argparse import Namespace
from email.message import Message
from pathlib import Path
from tempfile import TemporaryDirectory

from scraper.programs.scrape_programs_static import (
    CatalogueParser, classify_link, classify_sitemap_program_url, decode_html,
    Fetcher, capture_pages, discover_catalogues, initial_manifest, materialize_program_pages,
    has_verified_official_domains, is_transient_retryable, normalize_url, parse_args,
    parse_robots_sitemaps, parse_sitemap, program_prefixes, protocol_bootstrap_urls,
    response_record,
)


class FakeFetcher:
    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def fetch(self, url):
        self.requested.append(url)
        data = self.responses[url]
        headers = Message()
        headers["Content-Type"] = "application/xml; charset=utf-8"
        return {
            "ok": True, "status": 200, "url": url,
            "headers": {"Content-Type": headers["Content-Type"]},
            "messageHeaders": headers, "data": data, "elapsedMs": 1,
            "attempts": 1,
        }


class TypedFakeFetcher(FakeFetcher):
    def fetch(self, url):
        self.requested.append(url)
        value = self.responses[url]
        if isinstance(value, tuple):
            data, content_type = value
        else:
            data, content_type = value, "application/xml; charset=utf-8"
        headers = Message()
        headers["Content-Type"] = content_type
        return {
            "ok": True, "status": 200, "url": url,
            "headers": {"Content-Type": content_type},
            "messageHeaders": headers, "data": data, "elapsedMs": 1,
            "attempts": 1,
        }


class RedirectingFakeFetcher(TypedFakeFetcher):
    def __init__(self, responses, redirects):
        super().__init__(responses)
        self.redirects = redirects

    def fetch(self, url):
        response = super().fetch(url)
        response["url"] = self.redirects.get(url, url)
        return response


class ErrorResponse:
    def __init__(self, status, body=b""):
        self.status = status
        self.body = body

    def read(self):
        return self.body

    def geturl(self):
        return "https://example.edu/program"

    def __enter__(self):
        raise HTTPError(self.geturl(), self.status, "failure", Message(), self)

    def __exit__(self, *_args):
        return False


class ErrorOpener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def open(self, _request, timeout=None):
        self.calls += 1
        return next(self.responses)


def test():
    assert normalize_url("https://example.edu/a/?utm_source=x#part") == "https://example.edu/a"
    assert normalize_url("https://example.edu/fr/programme/formation-des-enseignant·es") == "https://example.edu/fr/programme/formation-des-enseignant%C2%B7es"
    html = b"""<html><head><title>Masters</title><link rel='next' href='?page=2'></head><body>
    <a href='/study/master/computer-science'>MSc Computer Science programme</a>
    <a href='/events/open-day'>Master open day</a></body></html>"""
    headers = Message()
    headers["Content-Type"] = "text/html; charset=utf-8"
    parser = CatalogueParser()
    parser.feed(decode_html(html, headers))
    links = [classify_link(link, "https://example.edu/study/masters", ["example.edu"], []) for link in parser.links]
    links = [link for link in links if link]
    assert any(link["kind"] == "program" and "computer-science" in link["url"] for link in links)
    assert any(link["kind"] == "pagination" for link in links)
    assert not any("open-day" in link["url"] for link in links)
    nullable = classify_link(
        {"href": "/study/master/data-science", "text": "MSc Data Science programme", "title": None, "aria": None, "rel": None},
        "https://example.edu/study/masters", ["example.edu"], [],
    )
    assert nullable and nullable["kind"] == "program"
    manifest = {
        "discovery": {"programCandidates": {
            "https://example.edu/study/master/data-science": nullable,
        }},
        "pages": {},
    }
    materialize_program_pages(manifest)
    assert manifest["pages"][nullable["url"]]["status"] == "pending"

    retryable = [
        {"status": "error", "statusCode": None, "error": "timed out"},
        {"status": "error", "httpStatus": None, "error": "SSL: CERTIFICATE_VERIFY_FAILED"},
        {"status": "error", "statusCode": None, "error": "connection reset by peer"},
        {"status": "error", "statusCode": None, "error": "socket closed"},
        {"status": "error", "statusCode": None, "error": "DNS lookup failed"},
    ] + [
        {"status": "error", "statusCode": code, "error": "HTTP Error %d" % code}
        for code in (408, 425, 429, 500, 502, 503, 599)
    ]
    assert all(is_transient_retryable(record) for record in retryable)
    terminal = [
        {"status": "error", "statusCode": code, "error": "HTTP Error %d" % code}
        for code in (301, 302, 307, 400, 401, 403, 404, 405, 410, 422)
    ] + [
        {"status": "blocked", "statusCode": 503, "blocked": True, "error": "HTTP Error 503"},
        {"status": "error", "statusCode": None, "error": "Cloudflare captcha"},
        {"status": "error", "statusCode": None, "error": "redirect loop"},
        {"status": "captured", "statusCode": 200, "error": None},
        {"status": "pending", "statusCode": None, "error": None},
    ]
    assert not any(is_transient_retryable(record) for record in terminal)
    parsed = parse_args(["--retry-transient-only"])
    assert parsed.retry_transient_only and not parsed.retry_errors
    assert not parse_args([]).protocol_bootstrap
    assert parse_args(["--protocol-bootstrap"]).protocol_bootstrap

    blocked_response = {
        "ok": False, "status": 503, "url": "https://example.edu/program",
        "headers": {}, "data": b"", "elapsedMs": 1, "attempts": 1,
        "error": "HTTP Error 503",
    }
    transient_record = response_record(blocked_response, None, "", None, "program")
    assert transient_record["status"] == "error"
    assert is_transient_retryable(transient_record)
    waf_parser = CatalogueParser()
    waf_parser.feed("<html><body>Cloudflare: verify you are human</body></html>")
    waf_record = response_record(blocked_response, None, "", waf_parser, "program")
    assert waf_record["status"] == "blocked"
    assert not is_transient_retryable(waf_record)

    retry_manifest = initial_manifest({
        "universityId": "u_retry", "name": "Retry University",
        "officialDomains": ["example.edu"],
    })
    retry_manifest["discovery"]["status"] = "complete"
    retry_manifest["pages"] = {
        "https://example.edu/timeout": retryable[0].copy(),
        "https://example.edu/503": retryable[-2].copy(),
        "https://example.edu/pending": {"status": "pending", "kind": "program"},
        "https://example.edu/404": terminal[6].copy(),
        "https://example.edu/redirect": terminal[-3].copy(),
        "https://example.edu/waf": terminal[-5].copy(),
    }
    retry_fetcher = FakeFetcher({
        "https://example.edu/timeout": b"<html><body>Recovered timeout</body></html>",
        "https://example.edu/503": b"<html><body>Recovered service</body></html>",
    })
    retry_args = Namespace(
        retry_transient_only=True, retry_errors=False,
        max_detail_pages_per_run=20, detail_workers=1, max_evidence_links=0,
    )
    with TemporaryDirectory() as temporary:
        capture_pages(
            {"officialDomains": ["example.edu"]}, retry_manifest,
            Path(temporary), retry_fetcher, retry_args,
        )
    assert retry_fetcher.requested == [
        "https://example.edu/timeout", "https://example.edu/503",
    ]
    assert retry_manifest["pages"]["https://example.edu/pending"]["status"] == "pending"
    assert retry_manifest["pages"]["https://example.edu/404"]["status"] == "error"

    fetcher = Fetcher(timeout=1, retries=1, delay=0)
    retrying_opener = ErrorOpener([ErrorResponse(501), ErrorResponse(501)])
    fetcher.opener = lambda: retrying_opener
    response = fetcher.fetch("https://example.edu/program")
    assert response["status"] == 501 and response["attempts"] == 2
    assert retrying_opener.calls == 2
    waf_opener = ErrorOpener([
        ErrorResponse(503, b"<html>Cloudflare captcha: verify you are human</html>"),
        ErrorResponse(503),
    ])
    fetcher.opener = lambda: waf_opener
    response = fetcher.fetch("https://example.edu/program")
    assert response["status"] == 503 and response["attempts"] == 1
    assert waf_opener.calls == 1
    prefixes = program_prefixes([
        "https://example.edu/study/master/a", "https://example.edu/study/master/b",
    ])
    assert prefixes == ["https://example.edu/study/master/"]

    goethe = classify_sitemap_program_url(
        "https://www.uni-frankfurt.de/studium/studiengaenge/data-science-master/",
        "https://www.uni-frankfurt.de/sitemap.xml", ["uni-frankfurt.de"],
    )
    assert goethe and goethe["source"] == "sitemap"
    for suffix in ("m-sc", "m-a", "mba", "ll-m", "mhba", "llm-magister"):
        fau = classify_sitemap_program_url(
            "https://www.fau.eu/degree-program/example-" + suffix + "/",
            "https://www.fau.eu/sitemap.xml", ["fau.eu"],
        )
        assert fau and fau["kind"] == "program"
    assert not classify_sitemap_program_url(
        "https://www.fau.eu/news/example-m-sc/", "https://www.fau.eu/sitemap.xml", ["fau.eu"],
    )
    assert not classify_sitemap_program_url(
        "https://foreign.example/degree-program/example-m-sc/", "https://www.fau.eu/sitemap.xml", ["fau.eu"],
    )

    verified_target = {
        "universityId": "u_protocol", "name": "Protocol University",
        "officialDomains": ["example.edu"], "verificationStatus": "verified",
        "indexUrl": "", "catalogPages": [], "programUrls": [],
    }
    assert has_verified_official_domains(verified_target)
    assert has_verified_official_domains({
        **verified_target,
        "verificationStatus": None,
        "officialVerificationStatus": "verified",
    })
    assert not has_verified_official_domains({**verified_target, "verificationStatus": "review"})
    bootstrap = protocol_bootstrap_urls(verified_target)
    assert bootstrap[0] == "https://example.edu/robots.txt"
    assert len(bootstrap) == len(set(bootstrap)) == 5
    assert not protocol_bootstrap_urls({**verified_target, "verificationStatus": "review"})
    robots = b"""User-agent: *
    Disallow: /private
    Sitemap: https://example.edu/robots-index.xml
    sitemap: https://catalog.example.edu/courses.xml # official child
    Sitemap: https://example.edu/robots-index.xml
    Sitemap: https://example.edu.attacker.test/steal.xml
    Sitemap: https://edu/parent.xml
    Allow: https://example.edu/not-a-sitemap.xml
    """
    assert parse_robots_sitemaps(robots, "https://example.edu/robots.txt", ["example.edu"]) == [
        "https://example.edu/robots-index.xml",
        "https://catalog.example.edu/courses.xml",
    ]

    index_url = "https://example.edu/sitemap.xml"
    child_url = "https://example.edu/programmes.xml"
    nested_url = "https://example.edu/nested-index.xml"
    too_deep_url = "https://example.edu/too-deep.xml"
    index_xml = b"""<?xml version='1.0'?>
    <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>https://example.edu/programmes.xml</loc></sitemap>
      <sitemap><loc>https://example.edu/nested-index.xml</loc></sitemap>
      <sitemap><loc>https://example.edu/sitemap.xml</loc></sitemap>
      <sitemap><loc>https://foreign.example/off-domain.xml</loc></sitemap>
    </sitemapindex>"""
    child_xml = b"""<?xml version='1.0'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>https://example.edu/degree-program/data-science-m-sc/</loc></url>
      <url><loc>https://example.edu/news/master-announcement</loc></url>
      <url><loc>https://foreign.example/degree-program/foreign-m-sc</loc></url>
    </urlset>"""
    nested_xml = b"""<?xml version='1.0'?>
    <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>https://example.edu/too-deep.xml</loc></sitemap>
    </sitemapindex>"""
    assert parse_sitemap(index_xml, "application/xml", index_url)["type"] == "sitemapindex"
    assert parse_sitemap(gzip.compress(child_xml), "application/gzip", child_url + ".gz")["type"] == "urlset"
    target = {
        "universityId": "u_example", "name": "Example University",
        "officialDomains": ["example.edu"], "indexUrl": index_url,
        "catalogPages": [], "programUrls": [],
    }
    fetcher = FakeFetcher({index_url: index_xml, child_url: child_xml, nested_url: nested_xml})
    args = Namespace(
        max_catalog_pages=10, max_catalog_pages_per_run=10, max_candidates=20,
        max_depth=2, max_sitemap_depth=1,
    )
    with TemporaryDirectory() as temporary:
        output = Path(temporary)
        manifest = initial_manifest(target)
        discover_catalogues(target, manifest, output, fetcher, args)
        candidate = "https://example.edu/degree-program/data-science-m-sc"
        assert candidate in manifest["discovery"]["programCandidates"]
        assert len(manifest["discovery"]["programCandidates"]) == 1
        assert fetcher.requested == [index_url, child_url, nested_url]
        assert too_deep_url not in fetcher.requested
        index_record = manifest["discovery"]["visited"][index_url]
        child_record = manifest["discovery"]["visited"][child_url]
        assert index_record["sitemapType"] == "sitemapindex"
        assert child_record["sitemapType"] == "urlset"
        raw_path = output / child_record["file"]
        with gzip.open(raw_path, "rb") as handle:
            assert handle.read() == child_xml

    robots_url = "https://example.edu/robots.txt"
    common_sitemaps = bootstrap[1:]
    robots_index = "https://example.edu/robots-index.xml"
    child_sitemap = "https://catalog.example.edu/courses.xml"
    duplicate_common = "https://example.edu/sitemap.xml"
    protocol_program = "https://example.edu/degree-program/protocol-m-sc"
    robots_index_xml = ("""<?xml version='1.0'?>
    <sitemapindex xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <sitemap><loc>%s</loc></sitemap>
      <sitemap><loc>https://outside.test/courses.xml</loc></sitemap>
    </sitemapindex>""" % duplicate_common).encode("utf-8")
    common_urlset = ("""<?xml version='1.0'?>
    <urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'>
      <url><loc>%s/</loc></url>
    </urlset>""" % protocol_program).encode("utf-8")
    empty_urlset = b"<?xml version='1.0'?><urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'></urlset>"
    protocol_responses = {
        robots_url: (robots, "text/plain; charset=utf-8"),
        robots_index: (robots_index_xml, "application/xml"),
        child_sitemap: (empty_urlset, "application/xml"),
    }
    for common in common_sitemaps:
        protocol_responses[common] = (
            common_urlset if common == duplicate_common else empty_urlset,
            "application/xml",
        )
    protocol_args = Namespace(
        max_catalog_pages=20, max_catalog_pages_per_run=20, max_candidates=20,
        max_depth=2, max_sitemap_depth=2, protocol_bootstrap=True,
    )
    with TemporaryDirectory() as temporary:
        output = Path(temporary)
        manifest = initial_manifest(verified_target)
        protocol_fetcher = TypedFakeFetcher(protocol_responses)
        discover_catalogues(verified_target, manifest, output, protocol_fetcher, protocol_args)
        assert set(protocol_fetcher.requested) == set(bootstrap + [robots_index, child_sitemap])
        assert len(protocol_fetcher.requested) == len(set(protocol_fetcher.requested))
        assert "https://outside.test/courses.xml" not in protocol_fetcher.requested
        assert protocol_program in manifest["discovery"]["programCandidates"]
        protocol_candidate = manifest["discovery"]["programCandidates"][protocol_program]
        assert protocol_candidate["sourceUrlRole"] == "discovery-only"
        assert protocol_candidate["eligibleAsProgramEvidence"] is False
        assert robots_index in manifest["discovery"]["protocolBootstrap"]["robotsSitemaps"]
        robots_record = manifest["discovery"]["visited"][robots_url]
        assert robots_record["kind"] == "robots"
        assert robots_record["protocolProbe"] is True
        assert robots_record["eligibleAsProgramEvidence"] is False
        assert robots_record["file"]
        with gzip.open(output / robots_record["file"], "rb") as handle:
            assert handle.read() == robots
        first_requests = list(protocol_fetcher.requested)
        discover_catalogues(verified_target, manifest, output, protocol_fetcher, protocol_args)
        assert protocol_fetcher.requested == first_requests

    # The flag alone cannot bootstrap an unverified target.
    with TemporaryDirectory() as temporary:
        review_target = {**verified_target, "verificationStatus": "review"}
        review_manifest = initial_manifest(review_target)
        review_fetcher = TypedFakeFetcher({})
        discover_catalogues(review_target, review_manifest, Path(temporary), review_fetcher, protocol_args)
        assert review_fetcher.requested == []
        assert review_manifest["discovery"]["programCandidates"] == {}

    # Raw is retained for an off-domain redirect, but its body is not parsed.
    redirect_responses = {
        url: ((robots if url == robots_url else empty_urlset),
              ("text/plain" if url == robots_url else "application/xml"))
        for url in bootstrap
    }
    redirected_robots = b"Sitemap: https://example.edu/redirect-leak.xml\n"
    redirect_responses[robots_url] = (redirected_robots, "text/plain")
    with TemporaryDirectory() as temporary:
        output = Path(temporary)
        redirect_manifest = initial_manifest(verified_target)
        redirect_fetcher = RedirectingFakeFetcher(
            redirect_responses, {robots_url: "https://attacker.test/robots.txt"},
        )
        discover_catalogues(verified_target, redirect_manifest, output, redirect_fetcher, protocol_args)
        assert "https://example.edu/redirect-leak.xml" not in redirect_fetcher.requested
        record = redirect_manifest["discovery"]["visited"][robots_url]
        assert record["protocolResponseAllowed"] is False
        assert record["bytes"] == len(redirected_robots) and record["file"]
    print("[static-crawler-test] passed")


if __name__ == "__main__":
    test()
