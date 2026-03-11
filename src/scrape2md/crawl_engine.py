from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CrawlResult:
    url: str
    html: str
    markdown: str
    title: str | None
    status_code: int | None
    content_type: str | None
    internal_links: list[str]
    asset_links: list[str]
    fetch_mode: str


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
    ) -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}
        self._attachment_extensions = tuple(ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in attachment_extensions)
        self._render_js = render_js
        self._wait_for_selector = wait_for_selector
        self._wait_time_ms = wait_time_ms
        self._wait_until = wait_until

    def fetch_page(self, url: str) -> CrawlResult:
        try:
            return self._fetch_with_crawl4ai(url)
        except Exception as exc:
            logger.warning("crawl4ai failed for %s, falling back to httpx: %s", url, exc)
            return self._fetch_with_httpx(url)

    def _fetch_with_crawl4ai(self, url: str) -> CrawlResult:
        from crawl4ai import AsyncWebCrawler

        async def _run() -> Any:
            async with AsyncWebCrawler() as crawler:
                crawl_args: dict[str, Any] = {"url": url}
                if self._render_js:
                    crawl_args["js"] = True
                if self._wait_for_selector:
                    crawl_args["wait_for"] = self._wait_for_selector
                if self._wait_time_ms > 0:
                    crawl_args["delay_before_return_html"] = self._wait_time_ms / 1000
                if self._wait_until:
                    crawl_args["wait_until"] = self._wait_until

                try:
                    return await crawler.arun(**crawl_args)
                except TypeError:
                    return await crawler.arun(url=url)

        result = asyncio.run(_run())
        html = getattr(result, "html", "") or ""
        markdown = getattr(result, "markdown", "") or md(html)
        title, links, assets = _extract_links(url, html, self._attachment_extensions)
        c4_links, c4_assets = _extract_links_from_crawl4ai_result(url, result, self._attachment_extensions)
        links = sorted(set(links + c4_links))
        assets = sorted(set(assets + c4_assets))
        status = getattr(result, "status_code", None)
        ctype = getattr(result, "response_headers", {}).get("content-type") if getattr(result, "response_headers", None) else None
        return CrawlResult(
            url=url,
            html=html,
            markdown=markdown,
            title=getattr(result, "title", None) or title,
            status_code=status,
            content_type=ctype,
            internal_links=links,
            asset_links=assets,
            fetch_mode="crawl4ai",
        )

    def _fetch_with_httpx(self, url: str) -> CrawlResult:
        with httpx.Client(timeout=self._timeout, follow_redirects=True, headers=self._headers) as client:
            response = client.get(url)
            response.raise_for_status()
        html = response.text
        title, links, assets = _extract_links(url, html, self._attachment_extensions)
        return CrawlResult(
            url=str(response.url),
            html=html,
            markdown=md(html),
            title=title,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            internal_links=links,
            asset_links=assets,
            fetch_mode="httpx",
        )


def _extract_links(base_url: str, html: str, attachment_extensions: tuple[str, ...]) -> tuple[str | None, list[str], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.text.strip() if soup.title and soup.title.text else None
    links: list[str] = []
    assets: list[str] = []

    for node in soup.select("a[href]"):
        href = node.get("href")
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if absolute.lower().endswith(attachment_extensions):
            assets.append(absolute)
        else:
            links.append(absolute)

    for node in soup.select("img[src],source[src],video[src],audio[src],link[href]"):
        href = node.get("href") or node.get("src")
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if absolute.lower().endswith(attachment_extensions):
            assets.append(absolute)

    return title, sorted(set(links)), sorted(set(assets))


def _extract_links_from_crawl4ai_result(
    base_url: str,
    result: Any,
    attachment_extensions: tuple[str, ...],
) -> tuple[list[str], list[str]]:
    payload = getattr(result, "links", None)
    if not isinstance(payload, dict):
        return [], []

    links: list[str] = []
    assets: list[str] = []

    for bucket_items in payload.values():
        if not isinstance(bucket_items, list):
            continue
        for item in bucket_items:
            href = None
            if isinstance(item, str):
                href = item
            elif isinstance(item, dict):
                href = item.get("href") or item.get("url")

            if not href or str(href).startswith(("mailto:", "javascript:", "#")):
                continue

            absolute = urljoin(base_url, str(href))
            if absolute.lower().endswith(attachment_extensions):
                assets.append(absolute)
            else:
                links.append(absolute)

    return sorted(set(links)), sorted(set(assets))
