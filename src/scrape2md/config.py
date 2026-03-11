from __future__ import annotations

from dataclasses import fields
import tomllib
from pathlib import Path

from scrape2md.models import CrawlConfig


def load_config(path: str | Path) -> CrawlConfig:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    allowed_keys = {f.name for f in fields(CrawlConfig)}
    filtered = {key: value for key, value in data.items() if key in allowed_keys}
    return CrawlConfig(**filtered)


def merge_config(base: CrawlConfig, **overrides: object) -> CrawlConfig:
    payload = base.to_dict()
    for key, value in overrides.items():
        if value is not None:
            payload[key] = value
    return CrawlConfig(**payload)
