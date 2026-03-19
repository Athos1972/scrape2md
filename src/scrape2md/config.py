from __future__ import annotations

from dataclasses import fields
import tomllib
from pathlib import Path

from scrape2md.models import CrawlConfig, EdgeConfig


DEFAULT_CRAWL_PROFILE = "conservative"

CRAWL_PROFILES: dict[str, dict[str, object]] = {
    "conservative": {
        "content_extraction": "main",
        "render_js": True,
        "wait_for_selector": None,
        "wait_time_ms": 1500,
        "wait_until": None,
        "dynamic_mode": False,
        "scan_full_page": False,
        "scroll_delay": 0.3,
        "delay_before_return_html": 0.8,
        "remove_consent_popups": True,
        "remove_overlay_elements": True,
        "process_iframes": False,
        "flatten_shadow_dom": False,
        "enable_menu_clicks": False,
        "wait_for": "js:() => document.readyState === 'complete'",
    },
    "balanced": {
        "content_extraction": "main",
        "render_js": True,
        "wait_for_selector": None,
        "wait_time_ms": 2000,
        "wait_until": "networkidle",
        "dynamic_mode": True,
        "scan_full_page": False,
        "scroll_delay": 0.4,
        "delay_before_return_html": 1.0,
        "remove_consent_popups": True,
        "remove_overlay_elements": True,
        "process_iframes": False,
        "flatten_shadow_dom": False,
        "enable_menu_clicks": True,
        "wait_for": "js:document.querySelectorAll('a[href]').length > 0 || document.readyState === 'complete'",
    },
    "dynamic": {
        "content_extraction": "main",
        "render_js": True,
        "wait_for_selector": "main",
        "wait_time_ms": 2500,
        "wait_until": "networkidle",
        "dynamic_mode": True,
        "scan_full_page": True,
        "scroll_delay": 0.5,
        "delay_before_return_html": 1.5,
        "remove_consent_popups": True,
        "remove_overlay_elements": True,
        "process_iframes": True,
        "flatten_shadow_dom": True,
        "enable_menu_clicks": True,
        "wait_for": "css:a[href]",
    },
}


def _apply_profile_defaults(data: dict[str, object]) -> dict[str, object]:
    profile = str(data.get("crawl_profile") or DEFAULT_CRAWL_PROFILE)
    if profile not in CRAWL_PROFILES:
        supported = ", ".join(sorted(CRAWL_PROFILES))
        raise ValueError(f"Unknown crawl_profile '{profile}'. Supported profiles: {supported}")
    return {"crawl_profile": profile, **CRAWL_PROFILES[profile], **data}


def load_config(path: str | Path) -> CrawlConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    data = _apply_profile_defaults(data)
    allowed_keys = {f.name for f in fields(CrawlConfig)}
    filtered = {key: value for key, value in data.items() if key in allowed_keys}
    return CrawlConfig(**filtered)


def load_edge_config(path: str | Path) -> EdgeConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    edge_data = data.get("edge", data)
    allowed_keys = {f.name for f in fields(EdgeConfig)}
    filtered = {key: value for key, value in edge_data.items() if key in allowed_keys}
    return EdgeConfig(**filtered)


def merge_config(base: CrawlConfig, **overrides: object) -> CrawlConfig:
    payload = base.to_dict()
    for key, value in overrides.items():
        if value is not None:
            payload[key] = value
    return CrawlConfig(**payload)
