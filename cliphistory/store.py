"""Persistent text-only clipboard history."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ClipItem:
    text: str
    copied_at: str
    truncated: bool = False


class HistoryStore:
    def __init__(self, path: Path, max_items: int = 100, max_chars: int = 100_000) -> None:
        self.path = path
        self.max_items = max_items
        self.max_chars = max_chars
        self._items: list[ClipItem] = []
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        with self._lock:
            self._items = []
            if not self.path.exists():
                return
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                raw_items = payload.get("items", [])
                if not isinstance(raw_items, list):
                    raise ValueError("items is not a list")
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    text = raw.get("text")
                    copied_at = raw.get("copied_at")
                    if not isinstance(text, str) or not isinstance(copied_at, str):
                        continue
                    self._items.append(
                        ClipItem(
                            text=text,
                            copied_at=copied_at,
                            truncated=bool(raw.get("truncated", False)),
                        )
                    )
                del self._items[self.max_items :]
            except (OSError, ValueError, json.JSONDecodeError):
                backup = self.path.with_suffix(".json.bak")
                try:
                    os.replace(self.path, backup)
                except OSError:
                    pass
                self._items = []

    def add(self, text: str | None) -> str:
        """Insert text at the top. Return new, moved, same, or ignored."""
        if text is None:
            return "ignored"
        text = text.replace("\x00", "")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            text = text.encode("utf-8", "replace").decode("utf-8")
        if text.strip() == "":
            return "ignored"
        truncated = False
        if len(text) > self.max_chars:
            text = text[: self.max_chars]
            truncated = True
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            for index, item in enumerate(self._items):
                if item.text == text:
                    if index == 0:
                        return "same"
                    item.copied_at = now
                    item.truncated = item.truncated or truncated
                    self._items.insert(0, self._items.pop(index))
                    self._save_locked()
                    return "moved"
            self._items.insert(0, ClipItem(text=text, copied_at=now, truncated=truncated))
            del self._items[self.max_items :]
            self._save_locked()
            return "new"

    def remove(self, text: str) -> None:
        with self._lock:
            self._items = [item for item in self._items if item.text != text]
            self._save_locked()

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._save_locked()

    def search(self, query: str) -> list[ClipItem]:
        needle = query.strip().lower()
        with self._lock:
            items = list(self._items)
        if not needle:
            return items
        return [item for item in items if needle in item.text.lower()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "items": [asdict(item) for item in self._items],
        }
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)
