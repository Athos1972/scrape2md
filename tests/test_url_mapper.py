from scrape2md.url_mapper import asset_rel_path, normalize_url, url_to_rel_path


def test_normalize_url_sorts_query_and_trims_slash() -> None:
    url = "HTTPS://Docs.Example.com/guide/intro/?b=2&a=1"
    assert normalize_url(url) == "https://docs.example.com/guide/intro?a=1&b=2"


def test_url_to_rel_path_handles_root() -> None:
    assert str(url_to_rel_path("https://docs.example.com", ".md")) == "index.md"


def test_url_to_rel_path_html_suffix_removed() -> None:
    assert str(url_to_rel_path("https://docs.example.com/guide/page.html", ".md")) == "guide/page.md"


def test_asset_path_sanitizes_filename() -> None:
    assert str(asset_rel_path("https://docs.example.com/files/My File(1).PDF")) == "files/My-File-1.pdf"
