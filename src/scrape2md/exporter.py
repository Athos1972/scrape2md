from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path

from scrape2md import __version__
from scrape2md.attachments import AttachmentDownloader
from scrape2md.crawl_engine import CrawlEngine
from scrape2md.discovery import discover_urls_from_sitemaps
from scrape2md.manifest import write_manifest
from scrape2md.models import CrawlConfig, ErrorRecord, Manifest, PageRecord
from scrape2md.url_mapper import normalize_url, url_to_rel_path
from scrape2md.utils import is_binary_content_type, is_html_content_type, is_same_domain, matches_patterns, sha256_text

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
            dynamic_mode=config.dynamic_mode,
            scan_full_page=config.scan_full_page,
            scroll_delay=config.scroll_delay,
            delay_before_return_html=config.delay_before_return_html,
            remove_consent_popups=config.remove_consent_popups,
            remove_overlay_elements=config.remove_overlay_elements,
            process_iframes=config.process_iframes,
            flatten_shadow_dom=config.flatten_shadow_dom,
            enable_menu_clicks=config.enable_menu_clicks,
            wait_for=config.wait_for,
            js_code_before_wait=config.js_code_before_wait,
            js_code=config.js_code,
            headless=config.headless,
            java_script_enabled=config.java_script_enabled,
            crawl4ai_verbose=config.crawl4ai_verbose,
        )
        self.downloader = AttachmentDownloader(config)

    def run(self) -> tuple[Manifest, Path]:
        domain = normalize_url(self.config.start_url).split("/")[2]
        export_root = Path(self.config.output_root) / domain
        html_dir = export_root / "html"
        pages_dir = export_root / "pages"
        assets_dir = export_root / "assets"
        debug_dir = export_root / "debug"
        for path in (html_dir, pages_dir, assets_dir):
            path.mkdir(parents=True, exist_ok=True)
        if self.config.debug_mode:
            debug_dir.mkdir(parents=True, exist_ok=True)

        manifest = Manifest.started(
            source_url=self.config.start_url,
            tool_name="scrape2md",
            tool_version=__version__,
            config_snapshot=self.config.to_dict(),
        )

        queue: deque[tuple[str, int, str | None]] = deque([(normalize_url(self.config.start_url), 0, None)])
        visited: set[str] = set()
        crawled_count = 0

        logger.info(
            "Starting crawl start_url=%s allowed_domains=%s include_patterns=%s exclude_patterns=%s max_depth=%s max_pages=%s dynamic_mode=%s",
            self.config.start_url,
            self.config.allowed_domains,
            self.config.include_patterns,
            self.config.exclude_patterns,
            self.config.max_depth,
            self.config.max_pages,
            self.config.dynamic_mode,
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
                result = self.engine.fetch_page(
                    url,
                    allowed_domains=self.config.allowed_domains or [domain],
                    include_patterns=self.config.include_patterns,
                    exclude_patterns=self.config.exclude_patterns,
                )
                normalized_url = normalize_url(result.url)
                html_rel = url_to_rel_path(normalized_url, ".html")
                md_rel = url_to_rel_path(normalized_url, ".md")
                html_path = html_dir / html_rel
                md_path = pages_dir / md_rel
                html_path.parent.mkdir(parents=True, exist_ok=True)
                md_path.parent.mkdir(parents=True, exist_ok=True)

                content_type = result.content_type or ""
                is_html_resource = is_html_content_type(content_type)
                markdown_content = (result.markdown or "").strip()
                should_write_markdown = self.config.save_markdown and is_html_resource and bool(markdown_content)
                markdown_skip_reason: str | None = None
                if self.config.save_html:
                    html_path.write_text(result.html, encoding="utf-8")
                if self.config.save_markdown:
                    if not is_html_resource:
                        markdown_skip_reason = "skip_markdown_non_html"
                        logger.info("%s url=%s content_type=%s", markdown_skip_reason, normalized_url, content_type or "-")
                        if is_binary_content_type(content_type):
                            logger.debug("classified_as_asset_by_content_type url=%s content_type=%s", normalized_url, content_type or "-")
                    elif not markdown_content:
                        markdown_skip_reason = "skip_markdown_empty_content"
                        logger.info("%s url=%s", markdown_skip_reason, normalized_url)
                    else:
                        md_path.write_text(result.markdown, encoding="utf-8")

                screenshot_path: str | None = None
                if self.config.debug_mode:
                    raw_debug_path = debug_dir / f"{md_rel.as_posix().replace('/', '__')}.raw.html"
                    raw_debug_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_debug_path.write_text(result.html, encoding="utf-8")
                    if result.cleaned_html:
                        cleaned_debug_path = debug_dir / f"{md_rel.as_posix().replace('/', '__')}.cleaned.html"
                        cleaned_debug_path.write_text(result.cleaned_html, encoding="utf-8")
                    if result.link_debug is not None:
                        link_debug_path = debug_dir / f"{md_rel.as_posix().replace('/', '__')}.link_analysis.json"
                        link_debug_path.write_text(json.dumps(result.link_debug, ensure_ascii=False, indent=2), encoding="utf-8")
                if self.config.debug_save_screenshot:
                    logger.debug("debug_save_screenshot enabled, but screenshot capture is not supported in this runtime.")

                manifest.pages.append(
                    PageRecord(
                        url=result.url,
                        normalized_url=normalized_url,
                        local_html_path=str(html_path) if self.config.save_html else None,
                        local_markdown_path=str(md_path) if should_write_markdown else None,
                        title=result.title,
                        status_code=result.status_code,
                        content_type=result.content_type,
                        depth=depth,
                        discovered_from=discovered_from,
                        internal_links=result.internal_links,
                        asset_links=result.asset_links,
                        content_hash=sha256_text(result.html),
                        fetch_mode=result.fetch_mode,
                        links_from_result=result.discovery_stats.crawl4ai_link_count,
                        links_from_html_fallback=result.discovery_stats.html_href_count,
                        filtered_links_count=result.discovery_stats.filtered_internal_count,
                        filtered_assets_count=result.discovery_stats.filtered_asset_count,
                        html_length=len(result.html),
                        screenshot_path=screenshot_path,
                        success=True,
                    )
                )

                for link in result.internal_links if is_html_resource else []:
                    n_link = normalize_url(link)
                    if n_link not in visited:
                        queue.append((n_link, depth + 1, normalized_url))

                if depth == 0 and is_html_resource and not result.internal_links:
                    pages, sitemap_assets = discover_urls_from_sitemaps(
                        page_url=normalized_url,
                        request_timeout=self.config.request_timeout,
                        user_agent=self.config.user_agent,
                        allowed_domains=self.config.allowed_domains or [domain],
                        include_patterns=self.config.include_patterns,
                        exclude_patterns=self.config.exclude_patterns,
                        attachment_extensions=tuple(self.config.attachment_extensions),
                    )
                    for sitemap_link in pages:
                        n_link = normalize_url(sitemap_link)
                        if n_link not in visited:
                            queue.append((n_link, depth + 1, normalized_url))

                    if self.config.download_attachments:
                        for asset_url in sitemap_assets:
                            asset, error = self.downloader.download(asset_url, assets_dir, normalized_url)
                            if asset:
                                manifest.assets.append(asset)
                            if error:
                                manifest.errors.append(error)

                if self.config.download_attachments:
                    for asset_url in result.asset_links:
                        asset, error = self.downloader.download(asset_url, assets_dir, normalized_url)
                        if asset:
                            manifest.assets.append(asset)
                        if error:
                            manifest.errors.append(error)

                crawled_count += 1
                backlog = len(queue)
                discovered = len(visited) + len(queue)
                if self.config.max_pages > 0:
                    progress = crawled_count / self.config.max_pages * 100
                    logger.info(
                        "CRAWL_PROGRESS crawled=%d backlog=%d discovered=%d progress=%.0f%%",
                        crawled_count,
                        backlog,
                        discovered,
                        progress,
                    )
                else:
                    logger.info(
                        "CRAWL_PROGRESS crawled=%d backlog=%d discovered=%d",
                        crawled_count,
                        backlog,
                        discovered,
                    )

                if self.config.rate_limit_seconds > 0:
                    time.sleep(self.config.rate_limit_seconds)

                logger.info(
                    "Crawled page %s mode=%s title=%s raw_html_len=%s cleaned_html_len=%s result.links internal count=%s html fallback href count=%s after filtering count=%s assets=%s html_path=%s",
                    normalized_url,
                    result.fetch_mode,
                    result.title,
                    len(result.html),
                    len(result.cleaned_html or ""),
                    result.discovery_stats.crawl4ai_link_count,
                    result.discovery_stats.html_href_count,
                    result.discovery_stats.filtered_internal_count,
                    result.discovery_stats.filtered_asset_count,
                    str(html_path) if self.config.save_html else "-",
                )

                if self.config.debug_mode and result.link_debug is not None:
                    logger.debug(
                        "Link analysis %s: raw_result_links=%s raw_html_links=%s normalized=%s kept=%s dropped=%s",
                        normalized_url,
                        len(result.link_debug.get("raw_result_links", [])),
                        len(result.link_debug.get("raw_html_links", [])),
                        len(result.link_debug.get("normalized_links", [])),
                        len(result.link_debug.get("kept_links", [])),
                        len(result.link_debug.get("dropped_links_with_reason", [])),
                    )
                    for dropped in result.link_debug.get("dropped_links_with_reason", []):
                        logger.debug(
                            "Dropped link url=%s normalized=%s reason=%s source=%s",
                            dropped.get("raw_url"),
                            dropped.get("normalized_url"),
                            dropped.get("reason"),
                            dropped.get("source"),
                        )

                if not result.internal_links:
                    logger.warning(
                        "0 links after discovery for %s: result.links internal count=%s html fallback href count=%s after filtering count=%s",
                        normalized_url,
                        result.discovery_stats.crawl4ai_link_count,
                        result.discovery_stats.html_href_count,
                        result.discovery_stats.filtered_internal_count,
                    )

                if len(result.html.strip()) < 256:
                    logger.warning(
                        "Very small raw HTML for %s (raw_html_len=%s, cleaned_html_len=%s) - page may not be fully rendered",
                        normalized_url,
                        len(result.html),
                        len(result.cleaned_html or ""),
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
