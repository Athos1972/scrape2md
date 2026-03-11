from scrape2md.crawl_engine import _extract_title


def test_extract_title() -> None:
    assert _extract_title("<html><head><title> Hello </title></head></html>") == "Hello"
    assert _extract_title("<html><body>No title</body></html>") is None
