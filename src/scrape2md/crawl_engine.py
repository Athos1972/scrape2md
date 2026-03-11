from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from markdownify import markdownify as md

from scrape2md.discovery import DiscoveryStats, discover_links

logger = logging.getLogger(__name__)

_GENERIC_MENU_JS = """
(() => {
  const selectors = [
    'button[aria-label*="menu" i]',
    '[class*="menu"] button',
    '[class*="nav"] button',
    '.hamburger',
    '.menu-toggle',
    '.navbar-toggle',
    'button[aria-expanded="false"]'
  ];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      try { el.click(); } catch (e) {}
    }
  }
  for (const details of document.querySelectorAll('details:not([open])')) {
    try { details.open = true; } catch (e) {}
  }
})();
"""

_GENERIC_DISCOVERY_JS = """
(async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let i = 0; i < 3; i += 1) {
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(250);
    window.scrollTo(0, 0);
    await sleep(200);
  }
})();
"""


@dataclass(slots=True)
class CrawlResult:
    url: str
    html: str
    cleaned_html: str
    markdown: str
    title: str | None
    status_code: int | None
    content_type: str | None
    internal_links: list[str]
    asset_links: list[str]
    fetch_mode: str
    discovery_stats: DiscoveryStats


class CrawlEngine:
    """Thin wrapper around crawl4ai with httpx fallback."""

    def __init__(
        self,
        timeout: float,
        user_agent: str,
        attachment_extensions: list[str],
        render_js: bool,
        wait_for_selector: str | None,
        wait_time_ms: int,
        wait_until: str | None,
        dynamic_mode: bool,
        scan_full_page: bool,
        scroll_delay: float,
        delay_before_return_html: float,
        remove_consent_popups: bool,
        remove_overlay_elements: bool,
        process_iframes: bool,
        flatten_shadow_dom: bool,
        enable_menu_clicks: bool,
        wait_for: str | None,
        js_code_before_wait: str | None,
        js_code: str | None,
        headless: bool,
        java_script_enabled: bool,
        crawl4ai_verbose: bool,
    ) -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}
        self._attachment_extensions = tuple(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in attachment_extensions)
        self._render_js = render_js
        self._wait_for_selector = wait_for_selector
        self._wait_time_ms = wait_time_ms
        self._wait_until = wait_until
        self._dynamic_mode = dynamic_mode
        self._scan_full_page = scan_full_page
        self._scroll_delay = scroll_delay
        self._delay_before_return_html = delay_before_return_html
        self._remove_consent_popups = remove_consent_popups
        self._remove_overlay_elements = remove_overlay_elements
        self._process_iframes = process_iframes
        self._flatten_shadow_dom = flatten_shadow_dom
        self._enable_menu_clicks = enable_menu_clicks
        self._wait_for = wait_for
        self._js_code_before_wait = js_code_before_wait
        self._js_code = js_code
        self._headless = headless
        self._java_script_enabled = java_script_enabled
        self._crawl4ai_verbose = crawl4ai_verbose

    def fetch_page(
        self,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
        exclude_patterns: list[str],
    ) -> CrawlResult:
        try:
            return self._fetch_with_crawl4ai(url, allowed_domains, include_patterns, exclude_patterns)
        except Exception as exc:
            logger.warning("crawl4ai failed for %s, falling back to httpx: %s", url, exc)
            return self._fetch_with_httpx(url, allowed_domains, include_patterns, exclude_patterns)

    def _fetch_with_crawl4ai(
        self,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
        exclude_patterns: list[str],
    ) -> CrawlResult:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

        browser_payload = _build_browser_config_payload(
            user_agent=self._headers["User-Agent"],
            headless=self._headless,
            java_script_enabled=self._java_script_enabled,
            verbose=self._crawl4ai_verbose,
        )
        run_payload = _build_run_config_payload(
            render_js=self._render_js,
            wait_for_selector=self._wait_for_selector,
            wait_time_ms=self._wait_time_ms,
            wait_until=self._wait_until,
            dynamic_mode=self._dynamic_mode,
            scan_full_page=self._scan_full_page,
            scroll_delay=self._scroll_delay,
            delay_before_return_html=self._delay_before_return_html,
            remove_consent_popups=self._remove_consent_popups,
            remove_overlay_elements=self._remove_overlay_elements,
            process_iframes=self._process_iframes,
            flatten_shadow_dom=self._flatten_shadow_dom,
            wait_for=self._wait_for,
            js_code_before_wait=self._build_js_code_before_wait(),
            js_code=self._js_code,
        )

        browser_config = _build_dataclass_from_payload(BrowserConfig, browser_payload)
        run_config = _build_dataclass_from_payload(CrawlerRunConfig, run_payload)

        async def _run() -> Any:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                return await crawler.arun(url=url, config=run_config)

        result = asyncio.run(_run())
        raw_html = getattr(result, "html", "") or ""
        cleaned_html = getattr(result, "cleaned_html", "") or ""
        markdown = getattr(result, "markdown", "") or md(raw_html)
        title = getattr(result, "title", None) or _extract_title(raw_html)

        internal_links, asset_links, stats = discover_links(
            page_url=getattr(result, "url", url) or url,
            html=raw_html,
            crawl4ai_links_payload=getattr(result, "links", None),
            attachment_extensions=self._attachment_extensions,
            allowed_domains=allowed_domains,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )

        status = getattr(result, "status_code", None)
        ctype = getattr(result, "response_headers", {}).get("content-type") if getattr(result, "response_headers", None) else None
        return CrawlResult(
            url=getattr(result, "url", url) or url,
            html=raw_html,
            cleaned_html=cleaned_html,
            markdown=markdown,
            title=title,
            status_code=status,
            content_type=ctype,
            internal_links=internal_links,
            asset_links=asset_links,
            fetch_mode="crawl4ai",
            discovery_stats=stats,
        )

    def _build_js_code_before_wait(self) -> str | None:
        chunks: list[str] = []
        if self._enable_menu_clicks:
            chunks.append(_GENERIC_MENU_JS)
            chunks.append(_GENERIC_DISCOVERY_JS)
        if self._js_code_before_wait:
            chunks.append(self._js_code_before_wait)
        return "\n".join(chunks) if chunks else None

    def _fetch_with_httpx(
        self,
        url: str,
        allowed_domains: list[str],
        include_patterns: list[str],
        exclude_patterns: list[str],
    ) -> CrawlResult:
        with httpx.Client(timeout=self._timeout, follow_redirects=True, headers=self._headers) as client:
            response = client.get(url)
            response.raise_for_status()
        html = response.text
        title = _extract_title(html)
        internal_links, asset_links, stats = discover_links(
            page_url=str(response.url),
            html=html,
            crawl4ai_links_payload=None,
            attachment_extensions=self._attachment_extensions,
            allowed_domains=allowed_domains,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
        )
        return CrawlResult(
            url=str(response.url),
            html=html,
            cleaned_html="",
            markdown=md(html),
            title=title,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            internal_links=internal_links,
            asset_links=asset_links,
            fetch_mode="httpx",
            discovery_stats=stats,
        )


def _extract_title(html: str) -> str | None:
    start_tag = html.lower().find("<title")
    if start_tag < 0:
        return None
    start = html.find(">", start_tag)
    end = html.lower().find("</title>", start + 1)
    if start < 0 or end < 0:
        return None
    title = html[start + 1 : end].strip()
    return title or None


def _build_browser_config_payload(*, user_agent: str, headless: bool, java_script_enabled: bool, verbose: bool) -> dict[str, Any]:
    return {
        "headless": headless,
        "user_agent": user_agent,
        "java_script_enabled": java_script_enabled,
        "verbose": verbose,
    }


def _build_run_config_payload(
    *,
    render_js: bool,
    wait_for_selector: str | None,
    wait_time_ms: int,
    wait_until: str | None,
    dynamic_mode: bool,
    scan_full_page: bool,
    scroll_delay: float,
    delay_before_return_html: float,
    remove_consent_popups: bool,
    remove_overlay_elements: bool,
    process_iframes: bool,
    flatten_shadow_dom: bool,
    wait_for: str | None,
    js_code_before_wait: str | None,
    js_code: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if render_js:
        payload["js"] = True
    if wait_for_selector:
        payload["wait_for"] = wait_for_selector
    if wait_time_ms > 0:
        payload["delay_before_return_html"] = wait_time_ms / 1000
    if wait_until:
        payload["wait_until"] = wait_until

    if dynamic_mode:
        payload.update(
            {
                "scan_full_page": scan_full_page,
                "scroll_delay": scroll_delay,
                "delay_before_return_html": delay_before_return_html,
                "remove_consent_popups": remove_consent_popups,
                "remove_overlay_elements": remove_overlay_elements,
                "process_iframes": process_iframes,
                "flatten_shadow_dom": flatten_shadow_dom,
            }
        )
        if wait_for:
            payload["wait_for"] = wait_for

    if js_code_before_wait:
        payload["js_code_before_wait"] = js_code_before_wait
    if js_code:
        payload["js_code"] = js_code

    return payload


def _build_dataclass_from_payload(cls: Any, payload: dict[str, Any]) -> Any:
    sig = inspect.signature(cls)
    accepted = set(sig.parameters.keys())
    filtered = {key: value for key, value in payload.items() if key in accepted and value is not None}
    unknown = [key for key in payload.keys() if key not in accepted]
    if unknown:
        logger.debug("Ignoring unsupported %s fields: %s", cls.__name__, ", ".join(sorted(unknown)))
    return cls(**filtered)
