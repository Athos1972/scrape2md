from pathlib import Path

from scrape2md.crawl_engine import CrawlResult
from scrape2md.exporter import SiteExporter
from scrape2md.models import CrawlConfig
from scrape2md.discovery import DiscoveryStats


def _build_result(url: str, content_type: str, markdown: str, html: str = "<html><body>ok</body></html>") -> CrawlResult:
    return CrawlResult(
        url=url,
        html=html,
        cleaned_html=html,
        markdown=markdown,
        title="Title",
        status_code=200,
        content_type=content_type,
        internal_links=[],
        asset_links=[],
        fetch_mode="httpx",
        discovery_stats=DiscoveryStats(0, 0, 0, 0),
        link_debug=None,
    )


def _run_export(monkeypatch, tmp_path: Path, result: CrawlResult) -> Path:
    config = CrawlConfig(
        start_url=result.url,
        output_root=str(tmp_path),
        max_pages=1,
        max_depth=0,
        save_html=False,
        save_markdown=True,
        download_attachments=False,
    )
    exporter = SiteExporter(config)
    monkeypatch.setattr(exporter.engine, "fetch_page", lambda *args, **kwargs: result)
    manifest, export_root = exporter.run()
    assert len(manifest.pages) == 1
    return export_root


def test_exporter_writes_markdown_for_html(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/page", "text/html; charset=utf-8", "# Hello")
    export_root = _run_export(monkeypatch, tmp_path, result)

    md_path = export_root / "pages" / "page.md"
    assert md_path.exists()
    assert md_path.read_text(encoding="utf-8") == "# Hello"


def test_exporter_skips_markdown_for_png(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/image.png", "image/png", "", html="")
    export_root = _run_export(monkeypatch, tmp_path, result)

    assert not (export_root / "pages" / "image.md").exists()


def test_exporter_skips_markdown_for_pdf(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/file.pdf", "application/pdf", "", html="")
    export_root = _run_export(monkeypatch, tmp_path, result)

    assert not (export_root / "pages" / "file.md").exists()


def test_exporter_skips_markdown_for_extensionless_image_content_type(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/download", "image/png", "", html="")
    export_root = _run_export(monkeypatch, tmp_path, result)

    assert not (export_root / "pages" / "download.md").exists()


def test_exporter_skips_empty_markdown_output(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/empty", "text/html", "   ")
    export_root = _run_export(monkeypatch, tmp_path, result)

    assert not (export_root / "pages" / "empty.md").exists()
