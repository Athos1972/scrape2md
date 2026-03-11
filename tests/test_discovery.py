from scrape2md.discovery import (
    discover_links,
    discover_urls_from_sitemaps,
    extract_links_from_crawl4ai_payload,
    extract_links_from_html,
    extract_sitemap_locs,
    normalize_discovered_url,
)


def test_extract_links_from_crawl4ai_payload_handles_common_shapes() -> None:
    links = extract_links_from_crawl4ai_payload(
        base_url="https://example.com/",
        payload={
            "internal": [
                {"href": "/about"},
                {"url": "https://example.com/contact?utm_source=a"},
                "https://example.com/docs/guide",
            ],
            "external": [
                {"href": "mailto:test@example.com"},
                {"href": "javascript:void(0)"},
                {"href": "#section"},
            ],
        },
    )

    assert links == [
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/docs/guide",
    ]


def test_extract_links_from_html_fallback() -> None:
    html = """
    <html><body>
      <a href="/a">A</a>
      <a href="mailto:x@y.z">mail</a>
      <a href="https://example.com/b#x">B</a>
      <img src="/files/doc.pdf" />
    </body></html>
    """
    links, assets = extract_links_from_html("https://example.com/root", html)
    assert links == ["https://example.com/a", "https://example.com/b"]
    assert assets == ["https://example.com/files/doc.pdf"]


def test_normalize_discovered_url_filters_non_http() -> None:
    assert normalize_discovered_url("tel:+43123", "https://example.com") is None
    assert normalize_discovered_url("/x?b=2&a=1&utm_source=t", "https://example.com") == "https://example.com/x?a=1&b=2"


def test_extract_sitemap_locs_with_namespaces() -> None:
    xml = """
    <urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
      <url><loc>https://example.com/page-a</loc></url>
      <url><loc>https://example.com/page-b</loc></url>
    </urlset>
    """
    assert extract_sitemap_locs(xml) == ["https://example.com/page-a", "https://example.com/page-b"]


def test_discover_links_applies_filters() -> None:
    internal, assets, stats = discover_links(
        page_url="https://example.com",
        html='<a href="/a">A</a><a href="https://other.com/x">X</a><a href="/f.pdf">F</a>',
        crawl4ai_links_payload={"internal": [{"href": "/b"}]},
        attachment_extensions=(".pdf",),
        allowed_domains=["example.com"],
        include_patterns=[],
        exclude_patterns=["*b"],
    )

    assert internal == ["https://example.com/a"]
    assert assets == ["https://example.com/f.pdf"]
    assert stats.crawl4ai_link_count == 1
    assert stats.html_href_count == 3


def test_discover_urls_from_sitemaps(monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, text: str, code: int = 200) -> None:
            self.text = text
            self.status_code = code

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError("bad")

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            if url.endswith("robots.txt"):
                return DummyResponse("Sitemap: https://example.com/custom-sitemap.xml")
            if url.endswith("custom-sitemap.xml"):
                return DummyResponse("<sitemapindex><sitemap><loc>https://example.com/sitemap-pages.xml</loc></sitemap></sitemapindex>")
            if url.endswith("sitemap-pages.xml"):
                return DummyResponse("<urlset><url><loc>https://example.com/a</loc></url><url><loc>https://example.com/file.pdf</loc></url></urlset>")
            return DummyResponse("", 404)

    monkeypatch.setattr("scrape2md.discovery.httpx.Client", DummyClient)

    pages, assets = discover_urls_from_sitemaps(
        page_url="https://example.com",
        request_timeout=5,
        user_agent="ua",
        allowed_domains=["example.com"],
        include_patterns=[],
        exclude_patterns=[],
        attachment_extensions=(".pdf",),
    )

    assert pages == ["https://example.com/a"]
    assert assets == ["https://example.com/file.pdf"]
