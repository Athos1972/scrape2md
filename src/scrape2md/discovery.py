from __future__ import annotations

import logging
from collections import deque
import gzip
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from scrape2md.utils import is_same_domain, matches_patterns

logger = logging.getLogger(__name__)

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "#")


class DiscoveryStats:
    def __init__(self, crawl4ai_link_count: int, html_href_count: int, filtered_internal_count: int, filtered_asset_count: int) -> None:
        self.crawl4ai_link_count = crawl4ai_link_count
        self.html_href_count = html_href_count
        self.filtered_internal_count = filtered_internal_count
        self.filtered_asset_count = filtered_asset_count


class _HTMLLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []
        self.assets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: v for k, v in attrs}
        if tag == "a" and attr_map.get("href"):
            self.hrefs.append(attr_map["href"] or "")
        for attr in ("data-href", "data-url"):
            if attr_map.get(attr):
                self.hrefs.append(attr_map[attr] or "")
        if tag in {"img", "source", "video", "audio"} and attr_map.get("src"):
            self.assets.append(attr_map["src"] or "")
        if tag == "link" and attr_map.get("href"):
            self.assets.append(attr_map["href"] or "")


def normalize_discovered_url(url: str, base_url: str | None = None) -> str | None:
    raw = (url or "").strip()
    if not raw or raw.lower().startswith(SKIP_SCHEMES):
        return None

    absolute = urljoin(base_url, raw) if base_url else raw
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None

    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if not path.startswith("/"):
        path = f"/{path}"
    path = path.rstrip("/") or "/"

    filtered_query = sorted(
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "fbclid", "gclid", "msclkid"))
    )
    query = urlencode(filtered_query)

    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))


def extract_links_from_html(base_url: str, html: str) -> tuple[list[str], list[str]]:
    if not html.strip():
        return [], []

    parser = _HTMLLinkParser()
    parser.feed(html)

    hrefs = [normalize_discovered_url(href, base_url=base_url) for href in parser.hrefs]
    assets = [normalize_discovered_url(src, base_url=base_url) for src in parser.assets]

    return sorted({x for x in hrefs if x}), sorted({x for x in assets if x})


def extract_links_from_crawl4ai_payload(base_url: str, payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    discovered: list[str] = []
    for bucket_items in payload.values():
        if not isinstance(bucket_items, list):
            continue
        for item in bucket_items:
            href = item if isinstance(item, str) else item.get("href") or item.get("url") if isinstance(item, dict) else None
            if not href:
                continue
            normalized = normalize_discovered_url(str(href), base_url=base_url)
            if normalized:
                discovered.append(normalized)
    return sorted(set(discovered))


def split_internal_and_assets(links: list[str], attachment_extensions: tuple[str, ...], allowed_domains: list[str], include_patterns: list[str], exclude_patterns: list[str]) -> tuple[list[str], list[str]]:
    internal: list[str] = []
    assets: list[str] = []
    for link in links:
        if link.lower().endswith(attachment_extensions):
            assets.append(link)
            continue
        if not is_same_domain(link, allowed_domains):
            continue
        if not matches_patterns(link, include_patterns, exclude_patterns):
            continue
        internal.append(link)
    return sorted(set(internal)), sorted(set(assets))


def discover_links(*, page_url: str, html: str, crawl4ai_links_payload: Any, attachment_extensions: tuple[str, ...], allowed_domains: list[str], include_patterns: list[str], exclude_patterns: list[str]) -> tuple[list[str], list[str], DiscoveryStats]:
    c4_links = extract_links_from_crawl4ai_payload(page_url, crawl4ai_links_payload)
    html_links, html_assets = extract_links_from_html(page_url, html)

    internal, assets = split_internal_and_assets(
        links=sorted(set(c4_links + html_links)),
        attachment_extensions=attachment_extensions,
        allowed_domains=allowed_domains,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )
    for item in html_assets:
        if item.lower().endswith(attachment_extensions):
            assets.append(item)

    stats = DiscoveryStats(len(c4_links), len(html_links), len(set(internal)), len(set(assets)))
    return sorted(set(internal)), sorted(set(assets)), stats


def extract_sitemap_locs(xml_text: str) -> list[str]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    locs: list[str] = []
    for elem in root.iter():
        if elem.tag.lower().endswith("loc") and elem.text and elem.text.strip():
            locs.append(elem.text.strip())
    return locs


def discover_urls_from_sitemaps(*, page_url: str, request_timeout: float, user_agent: str, allowed_domains: list[str], include_patterns: list[str], exclude_patterns: list[str], attachment_extensions: tuple[str, ...]) -> tuple[list[str], list[str]]:
    candidates = [urljoin(page_url, "/sitemap.xml")]
    discovered_pages: set[str] = set()
    discovered_assets: set[str] = set()

    with httpx.Client(timeout=request_timeout, follow_redirects=True, headers={"User-Agent": user_agent}) as client:
        robots_url = urljoin(page_url, "/robots.txt")
        try:
            robots_response = client.get(robots_url)
            if robots_response.status_code < 400:
                for line in robots_response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        normalized = normalize_discovered_url(sitemap_url, base_url=page_url)
                        if normalized:
                            candidates.append(normalized)
        except Exception as exc:
            logger.debug("robots.txt discovery failed at %s: %s", robots_url, exc)

        queue: deque[str] = deque(candidates)
        seen_sitemaps: set[str] = set()

        while queue:
            sitemap_url = normalize_discovered_url(queue.popleft(), base_url=page_url)
            if not sitemap_url or sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)
            try:
                response = client.get(sitemap_url)
                response.raise_for_status()
            except Exception as exc:
                logger.debug("Sitemap request failed at %s: %s", sitemap_url, exc)
                continue

            xml_text = response.text
            if sitemap_url.endswith(".xml.gz"):
                try:
                    xml_text = gzip.decompress(response.content).decode("utf-8", errors="ignore")
                except Exception as exc:
                    logger.debug("Failed to gunzip sitemap %s: %s", sitemap_url, exc)

            for loc in extract_sitemap_locs(xml_text):
                normalized = normalize_discovered_url(loc, base_url=sitemap_url)
                if not normalized or not is_same_domain(normalized, allowed_domains):
                    continue
                if normalized.endswith((".xml", ".xml.gz")):
                    queue.append(normalized)
                    continue
                if normalized.lower().endswith(attachment_extensions):
                    discovered_assets.add(normalized)
                    continue
                if matches_patterns(normalized, include_patterns, exclude_patterns):
                    discovered_pages.add(normalized)

    return sorted(discovered_pages), sorted(discovered_assets)
