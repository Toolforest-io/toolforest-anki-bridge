"""Add-on version metadata."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

UNKNOWN_VERSION = "unknown"


@lru_cache(maxsize=1)
def addon_version() -> str:
    """Return the version declared in the packaged add-on manifest."""
    try:
        manifest = json.loads((Path(__file__).with_name("manifest.json")).read_text())
    except Exception:
        return UNKNOWN_VERSION

    value = manifest.get("version")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return UNKNOWN_VERSION
