#!/usr/bin/env python3
"""Minimal scraper-to-markdown CLI.

The output path is read from TOML config (`output_path`).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import tomllib


def load_config(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def write_markdown(output_path: Path, title: str, content: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate markdown output based on config")
    parser.add_argument("--config", required=True, help="Path to TOML config file")
    parser.add_argument("--title", default="Scrape2MD Output", help="Document title")
    parser.add_argument("--content", default="Generated content.", help="Document body")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    output_path_raw = config.get("output_path")

    if not output_path_raw:
        raise SystemExit("Missing required config key in TOML: output_path")

    output_path = Path(output_path_raw)
    write_markdown(output_path, args.title, args.content)
    print(f"Markdown written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
