from pathlib import Path

from scrape2md.attachments import AttachmentDownloader
from scrape2md.models import CrawlConfig


def _config(tmp_path: Path) -> CrawlConfig:
    return CrawlConfig(
        start_url="https://example.com",
        output_root=str(tmp_path),
        attachment_extensions=[".pdf", ".docx"],
    )


def test_download_skips_unconfigured_extension_without_http_call(monkeypatch, tmp_path: Path) -> None:
    calls = {"count": 0}

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            calls["count"] += 1
            raise AssertionError("must not be called for .png")

    monkeypatch.setattr("scrape2md.attachments.httpx.Client", DummyClient)
    downloader = AttachmentDownloader(_config(tmp_path))

    asset, error = downloader.download("https://example.com/image.png", tmp_path / "assets", None)

    assert asset is None
    assert error is None
    assert calls["count"] == 0


def test_download_allows_configured_extension(monkeypatch, tmp_path: Path) -> None:
    class DummyResponse:
        headers = {"content-type": "application/pdf"}
        content = b"pdf"

        def raise_for_status(self) -> None:
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            return DummyResponse()

    monkeypatch.setattr("scrape2md.attachments.httpx.Client", DummyClient)
    downloader = AttachmentDownloader(_config(tmp_path))

    asset, error = downloader.download("https://example.com/file.pdf", tmp_path / "assets", "https://example.com")

    assert error is None
    assert asset is not None
    assert asset.url.endswith("file.pdf")
    assert asset.local_path is not None
