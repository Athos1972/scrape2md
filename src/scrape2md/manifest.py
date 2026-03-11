from __future__ import annotations

import json
from pathlib import Path

from scrape2md.models import Manifest


def write_manifest(manifest: Manifest, path: Path) -> None:
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
