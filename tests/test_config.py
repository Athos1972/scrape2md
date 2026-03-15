from pathlib import Path

from scrape2md.config import load_config


def test_load_config_ignores_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '\n'.join(
            [
                'start_url = "https://docs.example.com"',
                'output_root = "exports"',
                'render_js = true',
                'dynamic_mode = true',
                'wait_for = "js:document.querySelectorAll(\'a[href]\').length > 5"',
                'headless = true',
                'java_script_enabled = true',
                'crawl4ai_verbose = false',
                'future_option = "ignored"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.start_url == "https://docs.example.com"
    assert cfg.output_root == "exports"
    assert cfg.render_js is True
    assert cfg.dynamic_mode is True
    assert "querySelectorAll" in cfg.wait_for


def test_load_config_applies_crawl_profile_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'start_url = "https://docs.example.com"',
                'crawl_profile = "dynamic"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.crawl_profile == "dynamic"
    assert cfg.dynamic_mode is True
    assert cfg.scan_full_page is True
    assert cfg.enable_menu_clicks is True
    assert cfg.wait_for == "css:a[href]"


def test_load_config_profile_can_be_overridden_per_field(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'start_url = "https://docs.example.com"',
                'crawl_profile = "dynamic"',
                "process_iframes = false",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.crawl_profile == "dynamic"
    assert cfg.process_iframes is False
    assert cfg.flatten_shadow_dom is True


def test_load_config_rejects_unknown_profile(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                'start_url = "https://docs.example.com"',
                'crawl_profile = "wild"',
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_config(config_path)
    except ValueError as exc:
        assert "Unknown crawl_profile" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown crawl profile")



def test_load_config_crawl4ai_browser_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "\n".join([
            "start_url = \"https://docs.example.com\"",
            "headless = false",
            "java_script_enabled = true",
            "crawl4ai_verbose = true",
        ]),
        encoding="utf-8",
    )
    cfg = load_config(config_path)
    assert cfg.headless is False
    assert cfg.java_script_enabled is True
    assert cfg.crawl4ai_verbose is True
