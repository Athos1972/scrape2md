from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md


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


class CrawlEngine:
    """Thin wrapper around crawl4ai with httpx fallback."""

    def __init__(self, timeout: float, user_agent: str) -> None:
        self._timeout = timeout
        self._headers = {"User-Agent": user_agent}

    def fetch_page(self, url: str) -> CrawlResult:
        try:
            return self._fetch_with_crawl4ai(url)
        except Exception:
            return self._fetch_with_httpx(url)

    def _fetch_with_crawl4ai(self, url: str) -> CrawlResult:
        from crawl4ai import AsyncWebCrawler

        async def _run() -> Any:
            async with AsyncWebCrawler() as crawler:
                return await crawler.arun(url=url)

        result = asyncio.run(_run())
        html = getattr(result, "html", "") or ""
        markdown = getattr(result, "markdown", "") or md(html)
        title, links, assets = _extract_links(url, html)
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
        )

    def _fetch_with_httpx(self, url: str) -> CrawlResult:
        with httpx.Client(timeout=self._timeout, follow_redirects=True, headers=self._headers) as client:
            response = client.get(url)
            response.raise_for_status()
        html = response.text
        title, links, assets = _extract_links(url, html)
        return CrawlResult(
            url=str(response.url),
            html=html,
            markdown=md(html),
            title=title,
            status_code=response.status_code,
            content_type=response.headers.get("content-type"),
            internal_links=links,
            asset_links=assets,
        )


def _extract_links(base_url: str, html: str) -> tuple[str | None, list[str], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.text.strip() if soup.title and soup.title.text else None
    links: list[str] = []
    assets: list[str] = []
    for node in soup.select("a[href],img[src],script[src],link[href]"):
        href = node.get("href") or node.get("src")
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        absolute = urljoin(base_url, href)
        if any(absolute.lower().endswith(ext) for ext in (".pdf", ".zip", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xlsx")):
            assets.append(absolute)
        else:
            links.append(absolute)
    return title, sorted(set(links)), sorted(set(assets))
