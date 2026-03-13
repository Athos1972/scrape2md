from __future__ import annotations

import fnmatch
import hashlib
from urllib.parse import urlparse


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


def is_binary_content_type(content_type: str | None) -> bool:
    normalized = normalize_content_type(content_type)
    if not normalized:
        return False
    return normalized.startswith(_BINARY_CONTENT_TYPE_PREFIXES)
