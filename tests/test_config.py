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
                'future_option = "ignored"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(config_path)

    assert cfg.start_url == "https://docs.example.com"
    assert cfg.output_root == "exports"
    assert cfg.render_js is True
