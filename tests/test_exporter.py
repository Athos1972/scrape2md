from pathlib import Path

from scrape2md.crawl_engine import CrawlResult
from scrape2md.exporter import SiteExporter
from scrape2md.models import CrawlConfig
from scrape2md.discovery import DiscoveryStats
from scrape2md.manifest import read_manifest


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
        response_headers={},
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
    content = md_path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert 'title: "Title"' in content
    assert 'url: "https://example.com/page"' in content
    assert 'content_type: "text/html"' in content
    assert 'status_code: 200' in content
    assert content.rstrip().endswith("# Hello")


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


def test_exporter_writes_markdown_when_html_header_is_missing(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/page", "", "# Hello", html="<html><body>Hello</body></html>")
    export_root = _run_export(monkeypatch, tmp_path, result)

    md_path = export_root / "pages" / "page.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert 'url: "https://example.com/page"' in content
    assert content.rstrip().endswith("# Hello")


def test_exporter_skips_markdown_for_404_page(monkeypatch, tmp_path: Path) -> None:
    result = _build_result(
        "https://example.com/missing",
        "text/html; charset=utf-8",
        "# Not Found",
        html="<html><body><h1>404</h1></body></html>",
    )
    result.status_code = 404
    export_root = _run_export(monkeypatch, tmp_path, result)

    manifest = read_manifest(export_root / "manifest.json")
    assert manifest is not None
    page = manifest.pages[0]

    assert not (export_root / "pages" / "missing.md").exists()
    assert page.local_markdown_path is None
    assert page.local_html_path is None
    assert page.success is False
    assert page.status_code == 404
    assert len(manifest.errors) == 1
    assert manifest.errors[0].stage == "page_response"
    assert manifest.errors[0].error_type == "HttpStatusError"


def test_exporter_marks_new_page_in_manifest(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/page", "text/html", "# Hello")
    export_root = _run_export(monkeypatch, tmp_path, result)

    manifest = read_manifest(export_root / "manifest.json")
    assert manifest is not None
    assert manifest.pages[0].change_status == "new"


def test_exporter_marks_unchanged_page_and_preserves_markdown_mtime(monkeypatch, tmp_path: Path) -> None:
    result = _build_result("https://example.com/page", "text/html", "# Hello")
    export_root = _run_export(monkeypatch, tmp_path, result)
    md_path = export_root / "pages" / "page.md"
    initial_mtime = md_path.stat().st_mtime_ns

    export_root = _run_export(monkeypatch, tmp_path, result)
    manifest = read_manifest(export_root / "manifest.json")

    assert manifest is not None
    assert manifest.pages[0].change_status == "unchanged"
    assert md_path.stat().st_mtime_ns == initial_mtime


def test_exporter_writes_page_metadata_into_manifest(monkeypatch, tmp_path: Path) -> None:
    html = """
    <html lang="en">
      <head>
        <title>Release 2.1.0</title>
        <link rel="canonical" href="https://example.com/releases/2.1.0" />
        <meta property="article:published_time" content="2026-02-01T10:00:00+01:00" />
        <meta property="article:modified_time" content="2026-02-15T12:30:00+01:00" />
        <meta name="author" content="Release Bot" />
        <meta name="keywords" content="release, platform" />
        <meta property="og:site_name" content="Example Docs" />
      </head>
      <body>
        <nav aria-label="Breadcrumb">
          <a href="/">Docs</a>
          <a href="/releases">Releases</a>
          <span>Release 2.1.0</span>
        </nav>
        <main><h1>Release 2.1.0</h1></main>
      </body>
    </html>
    """
    result = _build_result("https://example.com/releases/2.1.0", "text/html; charset=utf-8", "# Release", html=html)
    result.response_headers = {
        "etag": '"abc123"',
        "last-modified": "Sun, 16 Feb 2026 11:45:00 GMT",
        "content-length": "4567",
    }
    export_root = _run_export(monkeypatch, tmp_path, result)

    manifest = read_manifest(export_root / "manifest.json")
    assert manifest is not None
    metadata = manifest.pages[0].page_metadata

    assert metadata["title"] == "Release 2.1.0"
    assert metadata["canonical_url"] == "https://example.com/releases/2.1.0"
    assert metadata["published_at"] == "2026-02-01T09:00:00Z"
    assert metadata["updated_at"] == "2026-02-15T11:30:00Z"
    assert metadata["last_modified_header"] == "2026-02-16T11:45:00Z"
    assert metadata["authors"] == ["Release Bot"]
    assert metadata["tags"] == ["release", "platform"]
    assert metadata["breadcrumbs"] == ["Docs", "Releases", "Release 2.1.0"]
    assert metadata["section_path"] == ["Docs", "Releases"]
    assert metadata["page_type"] == "release_notes"
    assert metadata["content_type"] == "text/html"
    assert metadata["content_length"] == 4567

    markdown_path = Path(manifest.pages[0].local_markdown_path or "")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert 'title: "Release 2.1.0"' in markdown
    assert 'canonical_url: "https://example.com/releases/2.1.0"' in markdown
    assert 'published_at: "2026-02-01T09:00:00Z"' in markdown
    assert 'updated_at: "2026-02-15T11:30:00Z"' in markdown
    assert "authors:" in markdown
    assert '- "Release Bot"' in markdown
    assert "tags:" in markdown
    assert '- "release"' in markdown
    assert '- "platform"' in markdown
    assert "breadcrumbs:" in markdown
    assert '- "Docs"' in markdown
    assert '- "Releases"' in markdown
    assert '- "Release 2.1.0"' in markdown
    assert markdown.rstrip().endswith("# Release")
