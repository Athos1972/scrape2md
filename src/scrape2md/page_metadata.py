from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from scrape2md.utils import normalize_content_type


@dataclass(slots=True)
class PageMetadataResult:
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def extract_page_metadata(
    *,
    html: str,
    url: str,
    title: str | None,
    content_type: str | None,
    status_code: int | None,
    response_headers: dict[str, str] | None,
) -> PageMetadataResult:
    soup = BeautifulSoup(html or "", "html.parser")
    headers = {str(k).lower(): str(v) for k, v in (response_headers or {}).items() if k and v is not None}
    json_ld_nodes = _extract_json_ld_nodes(soup)

    metadata: dict[str, Any] = {"url": url}
    raw: dict[str, Any] = {}

    extracted_title = _extract_title_metadata(soup, json_ld_nodes, title)
    if extracted_title:
        metadata["title"] = extracted_title

    canonical_url = _first_non_empty(
        _canonical_from_links(soup, url),
        _meta_content(soup, property_name="og:url"),
        _json_ld_value(json_ld_nodes, "@id"),
    )
    if canonical_url:
        metadata["canonical_url"] = canonical_url

    page_id, page_id_raw = _extract_page_id(soup, json_ld_nodes)
    if page_id:
        metadata["page_id"] = page_id
    if page_id_raw:
        raw["page_id"] = page_id_raw

    authors = _unique_strings(_extract_authors(soup, json_ld_nodes))
    if authors:
        metadata["authors"] = authors

    language = _extract_language(soup, json_ld_nodes)
    if language:
        metadata["language"] = language

    normalized_content_type = normalize_content_type(content_type)
    if normalized_content_type:
        metadata["content_type"] = normalized_content_type
        if content_type and content_type != normalized_content_type:
            raw["content_type"] = content_type

    site_name = _first_non_empty(
        _meta_content(soup, property_name="og:site_name"),
        _meta_content(soup, name="application-name"),
        _json_ld_value(json_ld_nodes, "publisher.name"),
        _json_ld_value(json_ld_nodes, "isPartOf.name"),
    )
    if site_name:
        metadata["site_name"] = site_name

    version = _extract_version(soup, json_ld_nodes, url)
    if version:
        metadata["version"] = version

    visibility = _extract_visibility(soup, headers)
    if visibility:
        metadata["visibility"] = visibility

    tags = _unique_strings(_extract_tags(soup, json_ld_nodes))
    if tags:
        metadata["tags"] = tags

    aliases = _unique_strings(_extract_aliases(soup, url, metadata.get("canonical_url")))
    if aliases:
        metadata["aliases"] = aliases

    entities = _unique_strings(_extract_entities(json_ld_nodes))
    if entities:
        metadata["entities"] = entities

    labels = _unique_strings(_extract_labels(soup, json_ld_nodes))
    if labels:
        metadata["labels"] = labels

    breadcrumbs = _unique_strings(_extract_breadcrumbs(soup, json_ld_nodes))
    if breadcrumbs:
        metadata["breadcrumbs"] = breadcrumbs

    section_path = _extract_section_path(breadcrumbs, labels)
    if section_path:
        metadata["section_path"] = section_path

    page_type, page_type_raw = _classify_page_type(url, extracted_title, breadcrumbs, labels, json_ld_nodes)
    if page_type:
        metadata["page_type"] = page_type
    if page_type_raw:
        raw["page_type"] = page_type_raw

    for field_name, raw_values in _extract_date_candidates(soup, json_ld_nodes).items():
        normalized = _first_iso_datetime(raw_values)
        if normalized:
            metadata[field_name] = normalized
            source_raw = [value for value in raw_values if value]
            if source_raw and source_raw[0] != normalized:
                raw[field_name] = source_raw

    etag = headers.get("etag")
    if etag:
        metadata["etag"] = etag

    last_modified_header = _normalize_http_datetime(headers.get("last-modified"))
    if last_modified_header:
        metadata["last_modified_header"] = last_modified_header
        if headers.get("last-modified") != last_modified_header:
            raw["last_modified_header"] = headers.get("last-modified")

    if status_code is not None:
        metadata["status_code"] = status_code

    content_length = _parse_int(headers.get("content-length"))
    if content_length is not None:
        metadata["content_length"] = content_length

    return PageMetadataResult(metadata=metadata, raw=raw)


def _extract_title_metadata(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]], title: str | None) -> str | None:
    return _first_non_empty(
        _meta_content(soup, property_name="og:title"),
        _meta_content(soup, name="twitter:title"),
        _json_ld_value(json_ld_nodes, "headline"),
        _json_ld_value(json_ld_nodes, "name"),
        _node_text(soup.find("h1")),
        _title_tag_text(soup),
        title,
    )


def _extract_page_id(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> tuple[str | None, list[str]]:
    candidates = _collect_meta_values(
        soup,
        "name",
        ["page_id", "page-id", "pageid", "page.id", "id", "article:id", "article_id", "document_id", "doc-id", "content_id"],
    )
    candidates.extend(_collect_meta_values(soup, "property", ["article:id"]))
    candidates.extend(_json_ld_values(json_ld_nodes, "identifier"))
    candidates.extend(_json_ld_values(json_ld_nodes, "@id"))
    candidates.extend(_extract_element_ids(soup))
    return _first_non_empty(*candidates), _unique_strings(candidates)


def _extract_language(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> str | None:
    html_tag = soup.find("html")
    return _first_non_empty(
        html_tag.get("lang").strip() if isinstance(html_tag, Tag) and html_tag.get("lang") else None,
        _meta_content(soup, name="language"),
        _json_ld_value(json_ld_nodes, "inLanguage"),
    )


def _extract_tags(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    for value in _collect_meta_values(soup, "name", ["keywords", "news_keywords"]):
        tags.extend(_split_keywords(value))
    tags.extend(_collect_meta_values(soup, "property", ["article:tag"]))
    for value in _json_ld_values(json_ld_nodes, "keywords"):
        if isinstance(value, str):
            tags.extend(_split_keywords(value))
    return tags


def _extract_aliases(soup: BeautifulSoup, url: str, canonical_url: str | None) -> list[str]:
    aliases: list[str] = []
    for link in soup.find_all("link"):
        if not isinstance(link, Tag):
            continue
        rels = [rel.lower() for rel in (link.get("rel") or [])]
        href = link.get("href")
        if not href:
            continue
        if any(rel in {"alternate", "amphtml", "shortlink"} for rel in rels):
            aliases.append(urljoin(url, href))
    if canonical_url and canonical_url != url:
        aliases.append(canonical_url)
    return [alias for alias in _unique_strings(aliases) if alias != url]


def _extract_labels(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    labels.extend(_collect_meta_values(soup, "property", ["article:section"]))
    labels.extend(_collect_meta_values(soup, "name", ["section", "category"]))
    labels.extend(_json_ld_values(json_ld_nodes, "articleSection"))
    labels.extend(_json_ld_values(json_ld_nodes, "genre"))
    return labels


def _extract_authors(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> list[str]:
    authors: list[str] = []
    authors.extend(_collect_meta_values(soup, "name", ["author"]))
    authors.extend(_collect_meta_values(soup, "property", ["article:author"]))
    authors.extend(_extract_person_names(_json_ld_values(json_ld_nodes, "author")))
    authors.extend(_extract_person_names(_json_ld_values(json_ld_nodes, "creator")))
    return authors


def _extract_entities(json_ld_nodes: list[dict[str, Any]]) -> list[str]:
    entities: list[str] = []
    entities.extend(_extract_person_names(_json_ld_values(json_ld_nodes, "about")))
    entities.extend(_extract_person_names(_json_ld_values(json_ld_nodes, "mentions")))
    return entities


def _extract_breadcrumbs(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> list[str]:
    breadcrumb_items = _extract_breadcrumbs_from_json_ld(json_ld_nodes)
    if breadcrumb_items:
        return breadcrumb_items

    for selector in [
        'nav[aria-label*="breadcrumb" i]',
        '[role="navigation"][aria-label*="breadcrumb" i]',
        ".breadcrumb",
        ".breadcrumbs",
        '[data-testid*="breadcrumb" i]',
    ]:
        node = soup.select_one(selector)
        if not isinstance(node, Tag):
            continue
        items = [_node_text(item) for item in node.select("a, span, li")]
        filtered = _unique_strings(items)
        if filtered:
            return filtered
    return []


def _extract_section_path(breadcrumbs: list[str], labels: list[str]) -> list[str]:
    if len(breadcrumbs) > 1:
        return breadcrumbs[:-1]
    return labels[:1] if labels else []


def _extract_version(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]], url: str) -> str | None:
    explicit = _first_non_empty(
        _meta_content(soup, name="version"),
        _meta_content(soup, property_name="version"),
        _json_ld_value(json_ld_nodes, "version"),
    )
    if explicit:
        return explicit
    for segment in [part for part in urlparse(url).path.split("/") if part]:
        if re.fullmatch(r"v\d+(?:\.\d+){0,3}", segment, flags=re.IGNORECASE):
            return segment
    return None


def _extract_visibility(soup: BeautifulSoup, headers: dict[str, str]) -> str | None:
    robots = ",".join(
        value
        for value in [
            _meta_content(soup, name="robots"),
            _meta_content(soup, name="googlebot"),
            headers.get("x-robots-tag"),
        ]
        if value
    ).lower()
    if not robots:
        return None
    if "noindex" in robots:
        return "noindex"
    if "private" in robots:
        return "private"
    if "index" in robots:
        return "index"
    return None


def _classify_page_type(
    url: str,
    title: str | None,
    breadcrumbs: list[str],
    labels: list[str],
    json_ld_nodes: list[dict[str, Any]],
) -> tuple[str | None, list[str]]:
    raw_signals = _unique_strings(_json_ld_type_values(json_ld_nodes))
    combined = " ".join(part.lower() for part in [url, title or "", *breadcrumbs, *labels] if part)

    for schema_type in raw_signals:
        lowered = schema_type.lower()
        if lowered == "faqpage":
            return "faq", raw_signals
        if lowered in {"newsarticle", "reportage"}:
            return "news", raw_signals
        if lowered in {"blogposting", "blog"}:
            return "blog", raw_signals
        if lowered in {"techarticle", "article"} and "/news/" not in url.lower():
            return "blog", raw_signals
    if any(token in combined for token in ["release notes", "release-notes", "changelog", "/releases", "/release-notes", "/changelog"]):
        return "release_notes", raw_signals or ["url/title"]
    if any(token in combined for token in ["faq", "frequently asked questions"]):
        return "faq", raw_signals or ["title/breadcrumbs"]
    if any(token in combined for token in ["meeting", "minutes", "protokoll", "protocol", "sitzung", "agenda"]):
        return "meeting_notes", raw_signals or ["title/breadcrumbs"]
    if any(token in combined for token in ["news", "press release", "newsroom", "/news/", "/press/"]):
        return "news", raw_signals or ["url/title"]
    if any(token in combined for token in ["docs", "documentation", "guide", "reference", "manual", "knowledge base", "help center", "/docs/", "/documentation/"]):
        return "documentation", raw_signals or ["url/title"]
    if any(token in combined for token in ["blog", "/blog/"]):
        return "blog", raw_signals or ["url/title"]
    return None, raw_signals


def _extract_date_candidates(soup: BeautifulSoup, json_ld_nodes: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        "created_at": _merge_values(
            _collect_meta_values(soup, "name", ["created_at", "creation_date", "date.created"]),
            _json_ld_values(json_ld_nodes, "dateCreated"),
        ),
        "published_at": _merge_values(
            _collect_meta_values(soup, "property", ["article:published_time"]),
            _collect_meta_values(soup, "name", ["pubdate", "publishdate", "publish_date", "published_at", "date"]),
            _time_attribute_values(soup, ["pubdate", "published", "entry-date", "article-date"]),
            _json_ld_values(json_ld_nodes, "datePublished"),
        ),
        "updated_at": _merge_values(
            _collect_meta_values(soup, "property", ["article:modified_time"]),
            _collect_meta_values(soup, "name", ["lastmod", "last-modified", "modified", "updated_at", "date.modified"]),
            _time_attribute_values(soup, ["updated", "modified"]),
            _json_ld_values(json_ld_nodes, "dateModified"),
        ),
        "last_modified": _merge_values(
            _collect_meta_values(soup, "name", ["last-modified"]),
            _json_ld_values(json_ld_nodes, "dateModified"),
        ),
    }


def _meta_content(soup: BeautifulSoup, *, name: str | None = None, property_name: str | None = None) -> str | None:
    attrs: dict[str, str] = {}
    if name:
        attrs["name"] = name
    if property_name:
        attrs["property"] = property_name
    node = soup.find("meta", attrs=attrs)
    if not isinstance(node, Tag):
        return None
    content = node.get("content")
    if not isinstance(content, str):
        return None
    content = content.strip()
    return content or None


def _collect_meta_values(soup: BeautifulSoup, attr: str, names: list[str]) -> list[str]:
    lowered_names = {name.lower() for name in names}
    values: list[str] = []
    for node in soup.find_all("meta"):
        if not isinstance(node, Tag):
            continue
        current = node.get(attr)
        content = node.get("content")
        if not isinstance(current, str) or not isinstance(content, str):
            continue
        if current.lower() in lowered_names and content.strip():
            values.append(content.strip())
    return values


def _canonical_from_links(soup: BeautifulSoup, url: str) -> str | None:
    for link in soup.find_all("link"):
        if not isinstance(link, Tag):
            continue
        rels = [rel.lower() for rel in (link.get("rel") or [])]
        href = link.get("href")
        if "canonical" in rels and isinstance(href, str) and href.strip():
            return urljoin(url, href.strip())
    return None


def _extract_json_ld_nodes(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        if not isinstance(script, Tag):
            continue
        raw_text = script.string or script.get_text()
        if not raw_text or not raw_text.strip():
            continue
        try:
            parsed = json.loads(raw_text.strip())
        except json.JSONDecodeError:
            continue
        nodes.extend(_flatten_json_ld(parsed))
    return nodes


def _flatten_json_ld(value: Any) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    if isinstance(value, dict):
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                flattened.extend(_flatten_json_ld(item))
        else:
            flattened.append(value)
    elif isinstance(value, list):
        for item in value:
            flattened.extend(_flatten_json_ld(item))
    return flattened


def _json_ld_values(nodes: list[dict[str, Any]], field_name: str) -> list[Any]:
    values: list[Any] = []
    for node in nodes:
        value = _nested_lookup(node, field_name)
        if value is None:
            continue
        if isinstance(value, list):
            values.extend(value)
        else:
            values.append(value)
    return values


def _json_ld_value(nodes: list[dict[str, Any]], field_name: str) -> str | None:
    for value in _json_ld_values(nodes, field_name):
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def _nested_lookup(payload: dict[str, Any], field_name: str) -> Any:
    current: Any = payload
    for part in field_name.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _extract_person_names(values: list[Any]) -> list[str]:
    names: list[str] = []
    for value in values:
        if isinstance(value, str):
            if value.strip():
                names.append(value.strip())
        elif isinstance(value, dict):
            name = value.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        elif isinstance(value, list):
            names.extend(_extract_person_names(value))
    return names


def _extract_breadcrumbs_from_json_ld(nodes: list[dict[str, Any]]) -> list[str]:
    for node in nodes:
        node_type = node.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if not any(str(item).lower() == "breadcrumblist" for item in types if item):
            continue
        items = node.get("itemListElement")
        if not isinstance(items, list):
            continue
        ordered: list[tuple[int, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            position = item.get("position")
            name = None
            inner_item = item.get("item")
            if isinstance(inner_item, dict):
                name = inner_item.get("name")
            if not name:
                name = item.get("name")
            if isinstance(name, str) and name.strip():
                try:
                    order = int(position)
                except (TypeError, ValueError):
                    order = len(ordered) + 1
                ordered.append((order, name.strip()))
        if ordered:
            return [name for _, name in sorted(ordered, key=lambda item: item[0])]
    return []


def _json_ld_type_values(nodes: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for node in nodes:
        node_type = node.get("@type")
        if isinstance(node_type, str):
            values.append(node_type)
        elif isinstance(node_type, list):
            values.extend(str(item) for item in node_type if item)
    return values


def _time_attribute_values(soup: BeautifulSoup, class_tokens: list[str]) -> list[str]:
    tokens = {token.lower() for token in class_tokens}
    values: list[str] = []
    for node in soup.find_all("time"):
        if not isinstance(node, Tag):
            continue
        classes = {str(item).lower() for item in (node.get("class") or [])}
        if classes and tokens.isdisjoint(classes):
            continue
        datetime_value = node.get("datetime")
        if isinstance(datetime_value, str) and datetime_value.strip():
            values.append(datetime_value.strip())
    return values


def _extract_element_ids(soup: BeautifulSoup) -> list[str]:
    for selector in ["main", "article", "body"]:
        node = soup.select_one(selector)
        if isinstance(node, Tag):
            value = node.get("id")
            if isinstance(value, str) and value.strip():
                return [value.strip()]
    return []


def _title_tag_text(soup: BeautifulSoup) -> str | None:
    if soup.title and soup.title.string:
        text = soup.title.string.strip()
        return text or None
    return None


def _node_text(node: Any) -> str | None:
    if not isinstance(node, Tag):
        return None
    text = node.get_text(" ", strip=True)
    return text or None


def _split_keywords(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]


def _merge_values(*value_lists: list[Any]) -> list[str]:
    merged: list[str] = []
    for values in value_lists:
        for value in values:
            if isinstance(value, str) and value.strip():
                merged.append(value.strip())
    return merged


def _first_iso_datetime(values: list[str]) -> str | None:
    for value in values:
        normalized = _normalize_datetime(value)
        if normalized:
            return normalized
    return None


def _normalize_http_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    return _format_datetime(parsed)


def _normalize_datetime(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
        return candidate

    iso_candidate = candidate.replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2}(?:\.\d+)?)?(?:[+-]\d{2}:\d{2})?", iso_candidate):
        iso_candidate = iso_candidate.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        parsed = None
    if parsed is not None:
        return _format_datetime(parsed)

    try:
        parsed = parsedate_to_datetime(candidate)
    except (TypeError, ValueError, IndexError):
        return None
    return _format_datetime(parsed)


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        unique.append(stripped)
    return unique
