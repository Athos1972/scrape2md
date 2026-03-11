from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from scrape2md import __version__
from scrape2md.attachments import AttachmentDownloader
from scrape2md.crawl_engine import CrawlEngine
from scrape2md.manifest import write_manifest
from scrape2md.models import CrawlConfig, ErrorRecord, Manifest, PageRecord
from scrape2md.url_mapper import normalize_url, url_to_rel_path
from scrape2md.utils import is_same_domain, matches_patterns, sha256_text

logger = logging.getLogger(__name__)


class SiteExporter:
    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.engine = CrawlEngine(
            timeout=config.request_timeout,
            user_agent=config.user_agent,
            attachment_extensions=config.attachment_extensions,
            render_js=config.render_js,
            wait_for_selector=config.wait_for_selector,
            wait_time_ms=config.wait_time_ms,
            wait_until=config.wait_until,
        )
        self.downloader = AttachmentDownloader(config)

    def run(self) -> tuple[Manifest, Path]:
        domain = normalize_url(self.config.start_url).split("/")[2]
        export_root = Path(self.config.output_root) / domain
        html_dir = export_root / "html"
        pages_dir = export_root / "pages"
        assets_dir = export_root / "assets"
        for path in (html_dir, pages_dir, assets_dir):
            path.mkdir(parents=True, exist_ok=True)

        manifest = Manifest.started(
            source_url=self.config.start_url,
            tool_name="scrape2md",
            tool_version=__version__,
            config_snapshot=self.config.to_dict(),
        )

        queue: deque[tuple[str, int, str | None]] = deque([(normalize_url(self.config.start_url), 0, None)])
        visited: set[str] = set()

        logger.info(
            "Starting crawl start_url=%s allowed_domains=%s include_patterns=%s exclude_patterns=%s max_depth=%s max_pages=%s",
            self.config.start_url,
            self.config.allowed_domains,
            self.config.include_patterns,
            self.config.exclude_patterns,
            self.config.max_depth,
            self.config.max_pages,
        )

        while queue and len(manifest.pages) < self.config.max_pages:
            url, depth, discovered_from = queue.popleft()
            if url in visited or depth > self.config.max_depth:
                logger.debug(
                    "Skipping url=%s reason=%s",
                    url,
                    "visited" if url in visited else f"max_depth_exceeded({depth}>{self.config.max_depth})",
                )
                continue
            visited.add(url)

            if not is_same_domain(url, self.config.allowed_domains or [domain]):
                logger.debug("Skipping url=%s reason=domain_filter", url)
                continue
            if not matches_patterns(url, self.config.include_patterns, self.config.exclude_patterns):
                logger.debug("Skipping url=%s reason=pattern_filter", url)
                continue

            try:
                result = self.engine.fetch_page(url)
                normalized_url = normalize_url(result.url)
                html_rel = url_to_rel_path(normalized_url, ".html")
                md_rel = url_to_rel_path(normalized_url, ".md")
                html_path = html_dir / html_rel
                md_path = pages_dir / md_rel
                html_path.parent.mkdir(parents=True, exist_ok=True)
                md_path.parent.mkdir(parents=True, exist_ok=True)

                if self.config.save_html:
                    html_path.write_text(result.html, encoding="utf-8")
                if self.config.save_markdown:
                    md_path.write_text(result.markdown, encoding="utf-8")

                manifest.pages.append(
                    PageRecord(
                        url=result.url,
                        normalized_url=normalized_url,
                        local_html_path=str(html_path) if self.config.save_html else None,
                        local_markdown_path=str(md_path) if self.config.save_markdown else None,
                        title=result.title,
                        status_code=result.status_code,
                        content_type=result.content_type,
                        depth=depth,
                        discovered_from=discovered_from,
                        internal_links=result.internal_links,
                        asset_links=result.asset_links,
                        content_hash=sha256_text(result.html),
                        fetch_mode=result.fetch_mode,
                        success=True,
                    )
                )

                for link in result.internal_links:
                    n_link = normalize_url(link)
                    if n_link not in visited:
                        queue.append((n_link, depth + 1, normalized_url))

                if depth == 0 and not result.internal_links:
                    for sitemap_link in self._discover_from_sitemap(normalized_url):
                        n_link = normalize_url(sitemap_link)
                        if n_link not in visited:
                            queue.append((n_link, depth + 1, normalized_url))

                if self.config.download_attachments:
                    for asset_url in result.asset_links:
                        asset, error = self.downloader.download(asset_url, assets_dir, normalized_url)
                        if asset:
                            manifest.assets.append(asset)
                        if error:
                            manifest.errors.append(error)

                if self.config.rate_limit_seconds > 0:
                    time.sleep(self.config.rate_limit_seconds)

                logger.info(
                    "Crawled page %s mode=%s discovered_links=%s discovered_assets=%s",
                    normalized_url,
                    result.fetch_mode,
                    len(result.internal_links),
                    len(result.asset_links),
                )
            except Exception as exc:
                logger.error("Failed page %s: %s", url, exc)
                manifest.errors.append(
                    ErrorRecord(
                        url=url,
                        stage="page_crawl",
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )

        manifest.finish()
        write_manifest(manifest, export_root / "manifest.json")
        return manifest, export_root

    def _discover_from_sitemap(self, page_url: str) -> list[str]:
        sitemap_url = urljoin(page_url, "/sitemap.xml")
        try:
            with httpx.Client(timeout=self.config.request_timeout, follow_redirects=True, headers={"User-Agent": self.config.user_agent}) as client:
                response = client.get(sitemap_url)
                response.raise_for_status()
            soup = BeautifulSoup(response.text, "xml")
            discovered = sorted(
                {
                    normalize_url(loc.text.strip())
                    for loc in soup.find_all("loc")
                    if loc.text and is_same_domain(loc.text.strip(), self.config.allowed_domains or [normalize_url(self.config.start_url).split('/')[2]])
                }
            )
            if discovered:
                logger.info("No links on root page; discovered %s urls via %s", len(discovered), sitemap_url)
            return discovered
        except Exception as exc:
            logger.debug("Sitemap discovery failed at %s: %s", sitemap_url, exc)
            return []
