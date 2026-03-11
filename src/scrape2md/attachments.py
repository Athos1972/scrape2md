from __future__ import annotations

import logging
from pathlib import Path

import httpx

from scrape2md.models import AssetRecord, CrawlConfig, ErrorRecord
from scrape2md.url_mapper import asset_rel_path

logger = logging.getLogger(__name__)


class AttachmentDownloader:
    def __init__(self, config: CrawlConfig) -> None:
        self._config = config
        self._downloaded: set[str] = set()

    def download(self, url: str, output_dir: Path, discovered_from: str | None) -> tuple[AssetRecord | None, ErrorRecord | None]:
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
