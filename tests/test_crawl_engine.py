from types import SimpleNamespace
import sys
import types

sys.modules.setdefault("httpx", types.SimpleNamespace(Client=object))
sys.modules.setdefault("bs4", types.SimpleNamespace(BeautifulSoup=object))
sys.modules.setdefault("markdownify", types.SimpleNamespace(markdownify=lambda html: html))

from scrape2md.crawl_engine import _extract_links_from_crawl4ai_result


def test_extract_links_from_crawl4ai_result_handles_common_shapes() -> None:
    result = SimpleNamespace(
        links={
            "internal": [
                {"href": "/about"},
                {"url": "https://example.com/contact"},
                "https://example.com/docs/guide",
            ],
            "external": [
                {"href": "mailto:test@example.com"},
                {"href": "javascript:void(0)"},
                {"href": "#section"},
            ],
            "media": [{"href": "/files/report.pdf"}],
        }
    )

    links, assets = _extract_links_from_crawl4ai_result(
        base_url="https://example.com/",
        result=result,
        attachment_extensions=(".pdf", ".zip"),
    )

    assert links == [
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/docs/guide",
    ]
    assert assets == ["https://example.com/files/report.pdf"]


def test_extract_links_from_crawl4ai_result_no_links_payload() -> None:
    links, assets = _extract_links_from_crawl4ai_result(
        base_url="https://example.com/",
        result=SimpleNamespace(links=None),
        attachment_extensions=(".pdf",),
    )

    assert links == []
    assert assets == []
