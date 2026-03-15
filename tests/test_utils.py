from scrape2md.utils import extract_content_html, is_binary_content_type, is_html_content_type


def test_is_html_content_type() -> None:
    assert is_html_content_type("text/html; charset=utf-8")
    assert is_html_content_type("application/xhtml+xml")
    assert not is_html_content_type("image/png")


def test_is_binary_content_type() -> None:
    assert is_binary_content_type("image/png")
    assert is_binary_content_type("application/pdf")
    assert is_binary_content_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert not is_binary_content_type("text/html")


def test_extract_content_html_prefers_main_and_removes_navigation() -> None:
    html = """
    <html><body>
      <header><a href="/a">Start</a><a href="/b">Docs</a></header>
      <main>
        <h1>Guide</h1>
        <p>This is the important content with enough text to be kept in the extracted output.</p>
      </main>
      <footer><a href="/c">Imprint</a></footer>
    </body></html>
    """
    extracted = extract_content_html(html, "main")
    assert "important content" in extracted
    assert "Imprint" not in extracted
    assert "Start" not in extracted


def test_extract_content_html_raw_keeps_navigation() -> None:
    html = """
    <html><body>
      <nav><a href="/a">Start</a></nav>
      <main><p>Main text with enough content to stay visible either way.</p></main>
    </body></html>
    """
    extracted = extract_content_html(html, "raw")
    assert "Start" in extracted


def test_extract_content_html_aggressive_removes_related_blocks() -> None:
    html = """
    <html><body>
      <div class="content">
        <p>This is the article body with enough text to count as substantial content in extraction.</p>
        <div class="related">Related links that should disappear.</div>
      </div>
    </body></html>
    """
    extracted = extract_content_html(html, "aggressive")
    assert "article body" in extracted
    assert "Related links" not in extracted
