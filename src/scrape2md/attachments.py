from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from scrape2md.models import AssetRecord, CrawlConfig, ErrorRecord
from scrape2md.url_mapper import asset_rel_path

logger = logging.getLogger(__name__)


class AttachmentDownloader:
    def __init__(self, config: CrawlConfig) -> None:
        self._config = config
        self._downloaded: set[str] = set()
        self._attachment_extensions = tuple(
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in config.attachment_extensions
        )

    def _is_configured_attachment_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return bool(path) and path.endswith(self._attachment_extensions)

    def download(self, url: str, output_dir: Path, discovered_from: str | None) -> tuple[AssetRecord | None, ErrorRecord | None]:
        if not self._is_configured_attachment_url(url):
            logger.debug("skip_attachment_unconfigured_extension url=%s", url)
            return None, None

        if url in self._downloaded:
            return None, None
        self._downloaded.add(url)

        local_path = output_dir / asset_rel_path(url)
        local_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with httpx.Client(timeout=self._config.request_timeout, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
            local_path.write_bytes(response.content)
            return AssetRecord(
                url=url,
                local_path=str(local_path),
                content_type=response.headers.get("content-type"),
                discovered_from=discovered_from,
                file_size=len(response.content),
                success=True,
            ), None
        except Exception as exc:
            logger.warning("Asset download failed for %s: %s", url, exc)
            return None, ErrorRecord(
                url=url,
                stage="asset_download",
                error_type=type(exc).__name__,
                message=str(exc),
            )
