from scrape2md.utils import is_binary_content_type, is_html_content_type


def test_is_html_content_type() -> None:
    assert is_html_content_type("text/html; charset=utf-8")
    assert is_html_content_type("application/xhtml+xml")
    assert not is_html_content_type("image/png")


def test_is_binary_content_type() -> None:
    assert is_binary_content_type("image/png")
    assert is_binary_content_type("application/pdf")
    assert is_binary_content_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert not is_binary_content_type("text/html")
