from __future__ import annotations

import fnmatch
import hashlib
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag


HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
_BINARY_CONTENT_TYPE_PREFIXES = (
    "image/",
    "audio/",
    "video/",
    "application/pdf",
    "application/octet-stream",
    "application/zip",
    "application/x-zip",
    "application/x-rar",
    "application/x-7z-compressed",
    "application/msword",
    "application/vnd.ms-",
    "application/vnd.openxmlformats-officedocument.",
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_same_domain(url: str, allowed_domains: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain.lower() or host.endswith(f".{domain.lower()}") for domain in allowed_domains)


def matches_patterns(url: str, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    if include_patterns and not any(fnmatch.fnmatch(url, pattern) for pattern in include_patterns):
        return False
    if exclude_patterns and any(fnmatch.fnmatch(url, pattern) for pattern in exclude_patterns):
        return False
    return True


def normalize_content_type(content_type: str | None) -> str:
    if not content_type:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def is_html_content_type(content_type: str | None) -> bool:
    normalized = normalize_content_type(content_type)
    return normalized in HTML_CONTENT_TYPES


def looks_like_html_document(content_type: str | None, url: str, html: str) -> bool:
    if is_html_content_type(content_type):
        return True

    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    if path.endswith((".pdf", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp", ".ico", ".css", ".js")):
        return False

    sample = (html or "").lstrip()[:256].lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<body" in sample or "<head" in sample


def is_binary_content_type(content_type: str | None) -> bool:
    normalized = normalize_content_type(content_type)
    if not normalized:
        return False
    return normalized.startswith(_BINARY_CONTENT_TYPE_PREFIXES)


_MAIN_CANDIDATE_SELECTORS = (
    "main",
    "article",
    '[role="main"]',
    ".main-content",
    ".maincontent",
    ".page-content",
    ".pagecontent",
    ".content",
    ".content-area",
    ".entry-content",
    ".post-content",
    ".article-content",
    "#main",
    "#content",
)

_BOILERPLATE_SELECTORS = (
    "nav",
    "header",
    "footer",
    "aside",
    '[role="navigation"]',
    '[aria-label*="breadcrumb" i]',
    ".breadcrumb",
    ".breadcrumbs",
    ".toc",
    ".table-of-contents",
    ".sidebar",
    ".side-nav",
    ".sidenav",
    ".nav",
    ".navbar",
    ".menu",
    ".pagination",
    ".pager",
    ".social-share",
    ".related-posts",
    ".cookie",
    ".consent",
)


def extract_content_html(html: str, mode: str) -> str:
    normalized_mode = (mode or "main").strip().lower()
    if normalized_mode == "raw" or not html.strip():
        return html
    if normalized_mode not in {"main", "aggressive"}:
        raise ValueError(f"Unknown content_extraction '{mode}'. Supported: raw, main, aggressive")

    soup = BeautifulSoup(html, "html.parser")
    _remove_boilerplate(soup, aggressive=normalized_mode == "aggressive")
    container = _select_primary_container(soup)
    if container is None:
        body = soup.body
        if body is None:
            return html
        container = body
    return str(container)


def _remove_boilerplate(soup: BeautifulSoup, aggressive: bool) -> None:
    selectors = list(_BOILERPLATE_SELECTORS)
    if aggressive:
        selectors.extend(
            [
                ".share",
                ".newsletter",
                ".cta",
                ".promo",
                ".teaser",
                ".recommendation",
                ".recommendations",
                ".related",
            ]
        )

    for selector in selectors:
        for node in soup.select(selector):
            node.decompose()


def _select_primary_container(soup: BeautifulSoup) -> Tag | None:
    for selector in _MAIN_CANDIDATE_SELECTORS:
        node = soup.select_one(selector)
        if _looks_substantial(node):
            return node

    best: Tag | None = None
    best_score = 0
    for node in soup.find_all(["div", "section"]):
        if not _looks_substantial(node):
            continue
        score = len(node.get_text(" ", strip=True))
        if score > best_score:
            best = node
            best_score = score
    return best


def _looks_substantial(node: Tag | None) -> bool:
    if node is None:
        return False
    text = node.get_text(" ", strip=True)
    if len(text) < 120:
        return False
    return bool(node.find(["p", "h1", "h2", "h3", "li"]))
