from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
import gzip
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from xml.etree import ElementTree

import httpx

from scrape2md.utils import is_same_domain, matches_patterns

logger = logging.getLogger(__name__)

SKIP_SCHEMES = ("mailto:", "tel:", "javascript:")
ASSET_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".bmp",
    ".ico",
)
SKIP_ASSET_EXTENSIONS = (
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".webmanifest",
)
ASSET_HINT_KEYWORDS = (
    "favicon",
    "apple-touch-icon",
    "android-chrome",
    "logo",
    "sprite",
)


@dataclass(slots=True)
class LinkDecision:
    source: str
    raw_url: str
    normalized_url: str | None
    decision: str
    reason: str


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
        rel = (attr_map.get("rel") or "").lower()
        if tag == "link" and attr_map.get("href") and "stylesheet" not in rel:
            self.assets.append(attr_map["href"] or "")


def _normalize_allowed_domain(domain: str) -> str:
    cleaned = (domain or "").strip().lower()
    if cleaned.startswith("www."):
        return cleaned[4:]
    return cleaned


def _is_internal_domain(url: str, allowed_domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    normalized_host = _normalize_allowed_domain(host)
    normalized_allowed = [_normalize_allowed_domain(domain) for domain in allowed_domains]
    return any(
        normalized_host == domain
        or normalized_host.endswith(f".{domain}")
        or host == domain
        or host.endswith(f".{domain}")
        for domain in normalized_allowed
    )


def normalize_discovered_url(url: str, base_url: str | None = None) -> str | None:
    raw = (url or "").strip()
    if not raw:
        return None
    if raw.startswith("#"):
        return None
    lower_raw = raw.lower()
    if lower_raw.startswith(SKIP_SCHEMES):
        return None

    absolute = urljoin(base_url, raw) if base_url else raw
    parsed = urlparse(absolute)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None

    path = parsed.path or "/"
    while "//" in path:
        path = path.replace("//", "/")
    if not path.startswith("/"):
        path = f"/{path}"

    if path.lower() in {"/index", "/index.html"}:
        path = "/"

    filtered_query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k and not k.lower().startswith(("utm_", "fbclid", "gclid", "msclkid"))
    ]
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
    discovered, _ = extract_raw_links_from_crawl4ai_payload(base_url, payload)
    return sorted(set(discovered))


def extract_raw_links_from_crawl4ai_payload(base_url: str, payload: Any) -> tuple[list[str], list[str]]:
    if not isinstance(payload, dict):
        return [], []
    normalized: list[str] = []
    raw_links: list[str] = []
    for bucket_items in payload.values():
        if not isinstance(bucket_items, list):
            continue
        for item in bucket_items:
            href = item if isinstance(item, str) else item.get("href") or item.get("url") if isinstance(item, dict) else None
            if not href:
                continue
            raw_links.append(str(href))
            normalized_url = normalize_discovered_url(str(href), base_url=base_url)
            if normalized_url:
                normalized.append(normalized_url)
    return normalized, raw_links


def _canonical_dedup_key(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunparse((parsed.scheme, parsed.netloc, path or "/", "", parsed.query, ""))


def _looks_like_asset_url(url: str) -> bool:
    lower_url = url.lower()
    parsed = urlparse(lower_url)
    path = parsed.path or ""
    filename = path.rsplit("/", 1)[-1]
    return path.endswith(ASSET_EXTENSIONS) or any(keyword in filename for keyword in ASSET_HINT_KEYWORDS)


def _classify_link(
    *,
    source: str,
    raw_url: str,
    page_url: str,
    attachment_extensions: tuple[str, ...],
    allowed_domains: list[str],
    include_patterns: list[str],
    exclude_patterns: list[str],
    dedup_seen: set[str],
) -> tuple[str | None, LinkDecision]:
    raw = (raw_url or "").strip()
    if not raw:
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=None, decision="drop", reason="invalid-url")

    lower_raw = raw.lower()
    if raw.startswith("#"):
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=None, decision="drop", reason="anchor-only")
    if lower_raw.startswith(SKIP_SCHEMES):
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=None, decision="drop", reason="mailto/tel/javascript")

    normalized = normalize_discovered_url(raw, base_url=page_url)
    if not normalized:
        reason = "non-http" if ":" in raw and not lower_raw.startswith(("http://", "https://")) else "invalid-url"
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=None, decision="drop", reason=reason)

    if normalized.lower().endswith(attachment_extensions):
        return normalized, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="asset", reason="attachment")

    if normalized.lower().endswith(SKIP_ASSET_EXTENSIONS):
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="drop", reason="ignored-static-asset")

    if _looks_like_asset_url(normalized):
        return normalized, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="asset", reason="asset-like-url")

    if not _is_internal_domain(normalized, allowed_domains):
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="drop", reason="external-domain")
    if not matches_patterns(normalized, include_patterns, exclude_patterns):
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="drop", reason="excluded-by-pattern")

    dedup_key = _canonical_dedup_key(normalized)
    if dedup_key in dedup_seen:
        return None, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="drop", reason="duplicate-after-normalization")
    dedup_seen.add(dedup_key)
    return normalized, LinkDecision(source=source, raw_url=raw_url, normalized_url=normalized, decision="keep", reason="kept")


def discover_links(
    *,
    page_url: str,
    html: str,
    crawl4ai_links_payload: Any,
    attachment_extensions: tuple[str, ...],
    allowed_domains: list[str],
    include_patterns: list[str],
    exclude_patterns: list[str],
    return_debug: bool = False,
) -> tuple[list[str], list[str], DiscoveryStats] | tuple[list[str], list[str], DiscoveryStats, dict[str, Any]]:
    parser = _HTMLLinkParser()
    if html.strip():
        parser.feed(html)

    _, raw_c4_links = extract_raw_links_from_crawl4ai_payload(page_url, crawl4ai_links_payload)
    raw_html_links = parser.hrefs
    raw_html_assets = parser.assets

    kept_internal: list[str] = []
    kept_assets: list[str] = []
    decisions: list[LinkDecision] = []
    dedup_seen: set[str] = set()

    for source, raw_candidates in (("result.links", raw_c4_links), ("html-fallback", raw_html_links), ("html-assets", raw_html_assets)):
        for raw in raw_candidates:
            normalized, decision = _classify_link(
                source=source,
                raw_url=raw,
                page_url=page_url,
                attachment_extensions=attachment_extensions,
                allowed_domains=allowed_domains,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
                dedup_seen=dedup_seen,
            )
            decisions.append(decision)
            if not normalized:
                continue
            if decision.decision == "asset":
                kept_assets.append(normalized)
            elif decision.decision == "keep":
                kept_internal.append(normalized)

    internal = sorted(set(kept_internal))
    assets = sorted(set(kept_assets))

    stats = DiscoveryStats(
        crawl4ai_link_count=len(raw_c4_links),
        html_href_count=len(raw_html_links),
        filtered_internal_count=len(internal),
        filtered_asset_count=len(assets),
    )

    if not return_debug:
        return internal, assets, stats

    debug_payload = {
        "raw_result_links": raw_c4_links,
        "raw_html_links": raw_html_links,
        "normalized_links": sorted({d.normalized_url for d in decisions if d.normalized_url}),
        "kept_links": internal,
        "kept_assets": assets,
        "dropped_links_with_reason": [
            {
                "source": d.source,
                "raw_url": d.raw_url,
                "normalized_url": d.normalized_url,
                "reason": d.reason,
            }
            for d in decisions
            if d.decision == "drop"
        ],
    }
    return internal, assets, stats, debug_payload


def split_internal_and_assets(links: list[str], attachment_extensions: tuple[str, ...], allowed_domains: list[str], include_patterns: list[str], exclude_patterns: list[str]) -> tuple[list[str], list[str]]:
    internal: list[str] = []
    assets: list[str] = []
    for link in links:
        if link.lower().endswith(attachment_extensions) or _looks_like_asset_url(link):
            assets.append(link)
            continue
        if not is_same_domain(link, allowed_domains):
            continue
        if not matches_patterns(link, include_patterns, exclude_patterns):
            continue
        internal.append(link)
    return sorted(set(internal)), sorted(set(assets))


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
                if normalized.lower().endswith(attachment_extensions) or _looks_like_asset_url(normalized):
                    discovered_assets.add(normalized)
                    continue
                if matches_patterns(normalized, include_patterns, exclude_patterns):
                    discovered_pages.add(normalized)

    return sorted(discovered_pages), sorted(discovered_assets)
