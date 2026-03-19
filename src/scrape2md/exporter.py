from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from scrape2md import __version__
from scrape2md.attachments import AttachmentDownloader
from scrape2md.crawl_engine import CrawlEngine
from scrape2md.discovery import discover_urls_from_sitemaps
from scrape2md.manifest import read_manifest, write_manifest
from scrape2md.models import CrawlConfig, ErrorRecord, Manifest, PageRecord
from scrape2md.page_metadata import extract_page_metadata
from scrape2md.url_mapper import normalize_url, url_to_rel_path
from scrape2md.utils import is_binary_content_type, is_same_domain, looks_like_html_document, matches_patterns, sha256_text

logger = logging.getLogger(__name__)

_FRONTMATTER_PRIORITY_FIELDS = [
    "title",
    "url",
    "canonical_url",
    "page_id",
    "created_at",
    "published_at",
    "updated_at",
    "last_modified",
    "authors",
    "language",
    "content_type",
    "page_type",
    "site_name",
    "version",
    "visibility",
    "tags",
    "aliases",
    "entities",
    "labels",
    "breadcrumbs",
    "section_path",
    "etag",
    "last_modified_header",
    "status_code",
    "content_length",
]


def _is_error_status(status_code: int | None) -> bool:
    return status_code is not None and status_code >= 400


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
            content_extraction=config.content_extraction,
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
        previous_manifest = read_manifest(export_root / "manifest.json")
        previous_pages_by_url = {
            page.normalized_url: page
            for page in (previous_manifest.pages if previous_manifest else [])
        }

        manifest = Manifest.started(
            source_url=self.config.start_url,
            tool_name="scrape2md",
            tool_version=__version__,
            config_snapshot=self.config.to_dict(),
        )

        queue: deque[tuple[str, int, str | None]] = deque([(normalize_url(self.config.start_url), 0, None)])
        visited: set[str] = set()
        crawled_count = 0
        skipped_visited = 0
        skipped_depth = 0
        skipped_domain = 0
        skipped_pattern = 0

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

        try:
            while queue and len(manifest.pages) < self.config.max_pages:
                url, depth, discovered_from = queue.popleft()
                if url in visited or depth > self.config.max_depth:
                    if url in visited:
                        skipped_visited += 1
                    else:
                        skipped_depth += 1
                    logger.debug(
                        "Skipping url=%s reason=%s",
                        url,
                        "visited" if url in visited else f"max_depth_exceeded({depth}>{self.config.max_depth})",
                    )
                    continue
                visited.add(url)

                if not is_same_domain(url, self.config.allowed_domains or [domain]):
                    skipped_domain += 1
                    logger.debug("Skipping url=%s reason=domain_filter", url)
                    continue
                if not matches_patterns(url, self.config.include_patterns, self.config.exclude_patterns):
                    skipped_pattern += 1
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
                    previous_page = previous_pages_by_url.get(normalized_url)
                    content_hash = sha256_text(result.html)
                    is_unchanged = previous_page is not None and previous_page.content_hash == content_hash
                    metadata_result = extract_page_metadata(
                        html=result.html,
                        url=result.url,
                        title=result.title,
                        content_type=result.content_type,
                        status_code=result.status_code,
                        response_headers=result.response_headers,
                    )
                    is_error_page = _is_error_status(result.status_code)

                    content_type = result.content_type or ""
                    is_html_resource = looks_like_html_document(content_type, normalized_url, result.html)
                    markdown_content = (result.markdown or "").strip()
                    should_write_markdown = (
                        self.config.save_markdown
                        and not is_error_page
                        and is_html_resource
                        and bool(markdown_content)
                    )
                    markdown_skip_reason: str | None = None
                    if is_error_page:
                        markdown_skip_reason = f"skip_markdown_error_status_{result.status_code}"
                        logger.info("%s url=%s", markdown_skip_reason, normalized_url)
                    if self.config.save_html and not is_error_page and (not is_unchanged or not html_path.exists()):
                        html_path.write_text(result.html, encoding="utf-8")
                    if self.config.save_markdown:
                        if is_error_page:
                            pass
                        elif not is_html_resource:
                            markdown_skip_reason = "skip_markdown_non_html"
                            logger.info("%s url=%s content_type=%s", markdown_skip_reason, normalized_url, content_type or "-")
                            if is_binary_content_type(content_type):
                                logger.debug("classified_as_asset_by_content_type url=%s content_type=%s", normalized_url, content_type or "-")
                        elif not markdown_content:
                            markdown_skip_reason = "skip_markdown_empty_content"
                            logger.info("%s url=%s", markdown_skip_reason, normalized_url)
                        else:
                            if not is_unchanged or not md_path.exists():
                                markdown_with_frontmatter = _render_markdown_document(
                                    metadata_result.metadata,
                                    result.markdown,
                                )
                                md_path.write_text(markdown_with_frontmatter, encoding="utf-8")

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

                    if is_error_page:
                        manifest.errors.append(
                            ErrorRecord(
                                url=result.url,
                                stage="page_response",
                                error_type="HttpStatusError",
                                message=f"HTTP status {result.status_code}",
                            )
                        )

                    manifest.pages.append(
                        PageRecord(
                            url=result.url,
                            normalized_url=normalized_url,
                            local_html_path=str(html_path) if self.config.save_html and not is_error_page else None,
                            local_markdown_path=str(md_path) if should_write_markdown else None,
                            title=result.title,
                            status_code=result.status_code,
                            content_type=result.content_type,
                            depth=depth,
                            discovered_from=discovered_from,
                            internal_links=result.internal_links,
                            asset_links=result.asset_links,
                            content_hash=content_hash,
                            fetch_mode=result.fetch_mode,
                            links_from_result=result.discovery_stats.crawl4ai_link_count,
                            links_from_html_fallback=result.discovery_stats.html_href_count,
                            filtered_links_count=result.discovery_stats.filtered_internal_count,
                            filtered_assets_count=result.discovery_stats.filtered_asset_count,
                            html_length=len(result.html),
                            screenshot_path=screenshot_path,
                            success=not is_error_page,
                            change_status="unchanged" if is_unchanged else ("updated" if previous_page else "new"),
                            page_metadata=metadata_result.metadata,
                            page_metadata_raw=metadata_result.raw,
                        )
                    )

                    for link in result.internal_links if is_html_resource and not is_error_page else []:
                        n_link = normalize_url(link)
                        if n_link not in visited:
                            queue.append((n_link, depth + 1, normalized_url))

                    if depth == 0 and is_html_resource and not is_error_page and not result.internal_links:
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
                    queue_size = len(queue)
                    discovered = len(visited) + queue_size
                    skipped_total = skipped_visited + skipped_depth + skipped_domain + skipped_pattern
                    if self.config.max_pages > 0:
                        progress = crawled_count / self.config.max_pages * 100
                        logger.info(
                            "CRAWL_PROGRESS crawled=%d queue_size=%d discovered=%d skipped=%d progress=%.0f%%",
                            crawled_count,
                            queue_size,
                            discovered,
                            skipped_total,
                            progress,
                        )
                    else:
                        logger.info(
                            "CRAWL_PROGRESS crawled=%d queue_size=%d discovered=%d skipped=%d",
                            crawled_count,
                            queue_size,
                            discovered,
                            skipped_total,
                        )

                    if self.config.rate_limit_seconds > 0:
                        time.sleep(self.config.rate_limit_seconds)

                    logger.info(
                        "Crawled page %s mode=%s change_status=%s title=%s raw_html_len=%s cleaned_html_len=%s result.links internal count=%s html fallback href count=%s after filtering count=%s assets=%s html_path=%s",
                        normalized_url,
                        result.fetch_mode,
                        manifest.pages[-1].change_status,
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
        finally:
            self.engine.close()
            self.downloader.close()

        manifest.finish()
        remaining_queue = len(queue)
        skipped_total = skipped_visited + skipped_depth + skipped_domain + skipped_pattern
        if len(manifest.pages) >= self.config.max_pages:
            stop_reason = "max_pages_reached"
        elif remaining_queue == 0:
            stop_reason = "queue_exhausted"
        else:
            stop_reason = "stopped_early"
        logger.info(
            "CRAWL_DONE pages=%d assets=%d errors=%d queue_remaining=%d skipped_total=%d skipped_visited=%d skipped_depth=%d skipped_domain=%d skipped_pattern=%d stop_reason=%s",
            len(manifest.pages),
            len(manifest.assets),
            len(manifest.errors),
            remaining_queue,
            skipped_total,
            skipped_visited,
            skipped_depth,
            skipped_domain,
            skipped_pattern,
            stop_reason,
        )
        write_manifest(manifest, export_root / "manifest.json")
        return manifest, export_root


def _render_markdown_document(metadata: dict[str, Any], markdown_body: str) -> str:
    body = markdown_body.strip()
    frontmatter = _render_yaml_frontmatter(metadata)
    if frontmatter:
        return f"{frontmatter}\n\n{body}\n"
    return f"{body}\n"


def _render_yaml_frontmatter(metadata: dict[str, Any]) -> str:
    if not metadata:
        return ""
    ordered_keys = [
        key for key in _FRONTMATTER_PRIORITY_FIELDS if key in metadata
    ] + sorted(key for key in metadata if key not in _FRONTMATTER_PRIORITY_FIELDS)
    lines = ["---"]
    for key in ordered_keys:
        value = metadata[key]
        rendered = _render_yaml_value(value, indent=0)
        if rendered is None:
            continue
        if "\n" in rendered:
            lines.append(f"{key}:")
            for line in rendered.splitlines():
                lines.append(f"  {line}")
        else:
            lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines)


def _render_yaml_value(value: Any, *, indent: int) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        if not value:
            return "[]"
        lines: list[str] = []
        child_prefix = "  " * indent
        for item in value:
            rendered_item = _render_yaml_value(item, indent=indent + 1)
            if rendered_item is None:
                continue
            if "\n" in rendered_item:
                parts = rendered_item.splitlines()
                lines.append(f"{child_prefix}- {parts[0]}")
                lines.extend(f"{child_prefix}  {part}" for part in parts[1:])
            else:
                lines.append(f"{child_prefix}- {rendered_item}")
        return "\n".join(lines)
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines: list[str] = []
        child_prefix = "  " * indent
        for key in sorted(value):
            rendered_item = _render_yaml_value(value[key], indent=indent + 1)
            if rendered_item is None:
                continue
            if "\n" in rendered_item:
                lines.append(f"{child_prefix}{key}:")
                lines.extend(f"{child_prefix}  {part}" for part in rendered_item.splitlines())
            else:
                lines.append(f"{child_prefix}{key}: {rendered_item}")
        return "\n".join(lines)
    return json.dumps(str(value), ensure_ascii=False)
