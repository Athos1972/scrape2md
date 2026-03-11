from types import SimpleNamespace

from scrape2md.crawl_engine import (
    _build_browser_config_payload,
    _build_run_config_payload,
    _extract_title,
)
from scrape2md.discovery import discover_links


def test_extract_title() -> None:
    assert _extract_title("<html><head><title> Hello </title></head></html>") == "Hello"
    assert _extract_title("<html><body>No title</body></html>") is None


def test_build_browser_config_payload() -> None:
    payload = _build_browser_config_payload(
        user_agent="ua",
        headless=True,
        java_script_enabled=True,
        verbose=False,
    )
    assert payload["user_agent"] == "ua"
    assert payload["headless"] is True
    assert payload["java_script_enabled"] is True


def test_build_run_config_payload_prefers_dynamic_wait_for() -> None:
    payload = _build_run_config_payload(
        render_js=True,
        wait_for_selector="main",
        wait_time_ms=1000,
        wait_until="networkidle",
        dynamic_mode=True,
        scan_full_page=True,
        scroll_delay=0.5,
        delay_before_return_html=1.2,
        remove_consent_popups=True,
        remove_overlay_elements=True,
        process_iframes=True,
        flatten_shadow_dom=True,
        wait_for="js:document.querySelectorAll('a[href]').length > 0",
        js_code_before_wait="console.log('x')",
        js_code="console.log('y')",
    )

    assert payload["js"] is True
    assert payload["wait_for"].startswith("js:")
    assert payload["scan_full_page"] is True
    assert payload["delay_before_return_html"] == 1.2


def test_discovery_uses_raw_html_source() -> None:
    result = SimpleNamespace(
        url="https://example.com",
        html='<a href="/real">real</a>',
        cleaned_html="<div>clean</div>",
        links=None,
    )
    internal, assets, stats = discover_links(
        page_url=result.url,
        html=result.html,
        crawl4ai_links_payload=result.links,
        attachment_extensions=(".pdf",),
        allowed_domains=["example.com"],
        include_patterns=[],
        exclude_patterns=[],
    )

    assert internal == ["https://example.com/real"]
    assert assets == []
    assert stats.html_href_count == 1
