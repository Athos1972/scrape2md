from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class CrawlConfig:
    start_url: str
    output_root: str = "exports"
    crawl_profile: str = "conservative"
    content_extraction: str = "main"
    allowed_domains: list[str] = field(default_factory=list)
    include_patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    max_pages: int = 100
    max_depth: int = 2
    download_attachments: bool = True
    attachment_extensions: list[str] = field(default_factory=lambda: [".pdf", ".zip", ".png", ".jpg", ".jpeg"])
    request_timeout: float = 20.0
    rate_limit_seconds: float = 0.0
    save_html: bool = True
    save_markdown: bool = True
    user_agent: str = "scrape2md/0.1.0"
    render_js: bool = True
    dynamic_mode: bool = False
    scan_full_page: bool = False
    scroll_delay: float = 0.5
    delay_before_return_html: float = 1.0
    remove_consent_popups: bool = True
    remove_overlay_elements: bool = True
    process_iframes: bool = False
    flatten_shadow_dom: bool = False
    enable_menu_clicks: bool = False
    wait_for: str = "js:() => document.readyState === 'complete'"
    js_code_before_wait: str | None = None
    js_code: str | None = None
    debug_mode: bool = False
    debug_save_screenshot: bool = False
    headless: bool = True
    java_script_enabled: bool = True
    crawl4ai_verbose: bool = False
    wait_for_selector: str | None = None
    wait_time_ms: int = 1500
    wait_until: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class PageRecord:
    url: str
    normalized_url: str
    local_html_path: str | None
    local_markdown_path: str | None
    title: str | None
    status_code: int | None
    content_type: str | None
    depth: int
    discovered_from: str | None
    internal_links: list[str]
    asset_links: list[str]
    content_hash: str | None
    fetch_mode: str
    links_from_result: int = 0
    links_from_html_fallback: int = 0
    filtered_links_count: int = 0
    filtered_assets_count: int = 0
    html_length: int = 0
    screenshot_path: str | None = None
    success: bool = True


@dataclass(slots=True)
class AssetRecord:
    url: str
    local_path: str | None
    content_type: str | None
    discovered_from: str | None
    file_size: int | None
    success: bool


@dataclass(slots=True)
class ErrorRecord:
    url: str
    stage: str
    error_type: str
    message: str


@dataclass(slots=True)
class Manifest:
    source_url: str
    crawl_started_at: str
    crawl_finished_at: str
    tool_name: str
    tool_version: str
    config_snapshot: dict
    pages: list[PageRecord] = field(default_factory=list)
    assets: list[AssetRecord] = field(default_factory=list)
    errors: list[ErrorRecord] = field(default_factory=list)

    @classmethod
    def started(cls, source_url: str, tool_name: str, tool_version: str, config_snapshot: dict) -> "Manifest":
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return cls(
            source_url=source_url,
            crawl_started_at=now,
            crawl_finished_at=now,
            tool_name=tool_name,
            tool_version=tool_version,
            config_snapshot=config_snapshot,
        )

    def finish(self) -> None:
        self.crawl_finished_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def to_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "crawl_started_at": self.crawl_started_at,
            "crawl_finished_at": self.crawl_finished_at,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version,
            "config_snapshot": self.config_snapshot,
            "pages": [asdict(p) for p in self.pages],
            "assets": [asdict(a) for a in self.assets],
            "errors": [asdict(e) for e in self.errors],
        }
