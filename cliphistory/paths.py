"""Local data directory for history, settings, and logs."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("CLIPHISTORY_HOME")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home()
    return base / "ClipHistory"
