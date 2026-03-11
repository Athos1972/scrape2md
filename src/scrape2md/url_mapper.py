from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_INVALID_CHARS = re.compile(r"[^a-zA-Z0-9._/-]+")
_MULTI_SEP = re.compile(r"/{2,}")


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = _clean_path(parsed.path)
    query_items = sorted((k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True))
    query = urlencode(query_items)
    return urlunparse((scheme, netloc, path, "", query, ""))


def _clean_path(path: str) -> str:
    path = _MULTI_SEP.sub("/", path or "/")
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def sanitize_segment(segment: str) -> str:
    cleaned = _INVALID_CHARS.sub("-", segment).strip("-._")
    return cleaned or "index"


def url_to_rel_path(url: str, suffix: str) -> Path:
    parsed = urlparse(normalize_url(url))
    raw_parts = [p for p in parsed.path.split("/") if p]
    if not raw_parts:
        return Path(f"index{suffix}")

    parts = [sanitize_segment(part.removesuffix(".html")) for part in raw_parts]
    if parsed.path.endswith("/"):
        return Path(*parts) / f"index{suffix}"

    last = parts[-1]
    if "." in raw_parts[-1]:
        stem = sanitize_segment(raw_parts[-1].rsplit(".", 1)[0])
        parts[-1] = stem

    return Path(*parts).with_suffix(suffix)


def asset_rel_path(url: str) -> Path:
    parsed = urlparse(normalize_url(url))
    raw_parts = [p for p in parsed.path.split("/") if p]
    if not raw_parts:
        return Path("file.bin")

    parts = [sanitize_segment(part) for part in raw_parts[:-1]]
    filename = raw_parts[-1]
    safe_name = sanitize_segment(filename)
    if "." in filename:
        stem, ext = filename.rsplit(".", 1)
        safe_name = f"{sanitize_segment(stem)}.{sanitize_segment(ext).lower()}"
    return Path(*parts, safe_name) if parts else Path(safe_name)
