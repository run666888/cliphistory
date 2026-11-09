"""Checks history, clipboard restore, and the window without stealing a paste."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

from cliphistory.app import Popup, configure_scaling
from cliphistory.platform_win import (
    create_app_icon,
    cursor_work_area,
    enable_dpi,
    input_struct_size,
    read_clipboard_text,
    restore_clipboard,
    set_clipboard_text,
    snapshot_clipboard,
    user32,
)
from cliphistory.store import HistoryStore


def _check_store(directory: Path) -> None:
    path = directory / "history.json"
    store = HistoryStore(path, max_items=2, max_chars=1000)
    assert store.add("   \n") == "ignored"
    assert store.add("a") == "new"
    assert store.add("b") == "new"
    assert store.add("c") == "new"
    assert [item.text for item in store.search("")] == ["c", "b"]
    assert store.add("b") == "moved"
    assert [item.text for item in store.search("")] == ["b", "c"]
    assert store.add("第一行\nSELECT id FROM t") == "new"
    assert len(store.search("select")) == 1
    store.remove("c")
    reloaded = HistoryStore(path, max_items=2, max_chars=1000)
    texts = [item.text for item in reloaded.search("")]
    assert "c" not in texts
    assert any("SELECT" in item for item in texts)
    path.write_text("{", encoding="utf-8")
    broken = HistoryStore(path)
    assert len(broken) == 0
    assert path.with_suffix(".json.bak").exists()

    tiny = HistoryStore(directory / "tiny.json", max_chars=5)
    assert tiny.add("hello!") == "new"
    newest = tiny.search("")[0]
    assert newest.text == "hello"
    assert newest.truncated


def _check_popup(directory: Path) -> None:
    enable_dpi()
    store = HistoryStore(directory / "ui-history.json")
    store.add("SELECT * FROM users WHERE id = 1")
    store.add("D:\\curfirst\\cliphistory\\app.py")
    root = tk.Tk()
    root.withdraw()
    configure_scaling(root)
    popup = Popup(root, store, lambda *_args: None, lambda *_args: None, lambda: None)
    assert popup.list.size() == 2
    assert "app.py" in popup.list.get(0)
    popup.query.set("select")
    assert popup.list.size() == 1
    popup.query.set("")
    root.destroy()


def _check_clipboard_roundtrip() -> bool:
    snapshot = snapshot_clipboard()
    if snapshot is None:
        raise AssertionError("could not read the clipboard")
    if not snapshot.restorable:
        print("clipboard has non-text data; skipped write test")
        status, _text = read_clipboard_text()
        assert status == "ok"
        return False
    try:
        assert set_clipboard_text("cliphistory-测试")
        status, text = read_clipboard_text()
        assert status == "ok"
        assert text == "cliphistory-测试"
        return True
    finally:
        if not restore_clipboard(snapshot):
            raise AssertionError("failed to restore the clipboard")


def _wait_for(predicate, timeout: float, detail: Path) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    logs = []
    for name in ("log.txt", "stdout.txt", "history.json", "ready"):
        file = detail / name
        if file.exists():
            logs.append(f"----- {name} -----\n{file.read_text(encoding='utf-8', errors='replace')}")
    raise AssertionError("timed out\n" + "\n".join(logs))


def _check_process(project_root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="cliphistory-run-") as temporary:
        home = Path(temporary)
        env = os.environ.copy()
        env["CLIPHISTORY_HOME"] = str(home)
        env["CLIPHISTORY_QUIET"] = "1"
        env["CLIPHISTORY_EXIT_AFTER_READY"] = "1"
        env["CLIPHISTORY_MUTEX"] = f"Local\\ClipHistory.Smoke.{os.getpid()}"
        env["PYTHONUNBUFFERED"] = "1"
        with (home / "stdout.txt").open("w", encoding="utf-8") as stdout:
            process = subprocess.Popen(
                [sys.executable, "-m", "cliphistory"],
                cwd=project_root,
                env=env,
                stdout=stdout,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        try:
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                raise AssertionError((home / "log.txt").read_text(encoding="utf-8", errors="replace") if (home / "log.txt").exists() else "process hung")
            log_text = (home / "log.txt").read_text(encoding="utf-8") if (home / "log.txt").exists() else ""
            stdout_text = (home / "stdout.txt").read_text(encoding="utf-8", errors="replace")
            assert process.returncode == 0, stdout_text + "\n" + log_text
            assert "ready hotkey=True tray=True" in log_text, log_text + "\n" + stdout_text
            assert "AddClipboardFormatListener failed" not in log_text
            assert "RegisterHotKey failed" not in log_text
            assert "Shell_NotifyIcon failed" not in log_text
        finally:
            if process.poll() is None:
                process.kill()


def _check_listener(project_root: Path) -> None:
    snapshot = snapshot_clipboard()
    if snapshot is None or not snapshot.restorable:
        print("skipped listener test to avoid overwriting the clipboard")
        return
    with tempfile.TemporaryDirectory(prefix="cliphistory-") as temporary:
        home = Path(temporary)
        token_1 = "cliphistory-token-one"
        token_2 = "cliphistory-token-two-路径"
        try:
            assert set_clipboard_text(token_1)
            env = os.environ.copy()
            env["CLIPHISTORY_HOME"] = str(home)
            env["CLIPHISTORY_QUIET"] = "1"
            env["CLIPHISTORY_NO_TRAY"] = "1"
            env["CLIPHISTORY_HOTKEY"] = "0"
            env["CLIPHISTORY_MUTEX"] = f"Local\\ClipHistory.SelfTest.{os.getpid()}"
            env["PYTHONUNBUFFERED"] = "1"
            with (home / "stdout.txt").open("w", encoding="utf-8") as stdout:
                process = subprocess.Popen(
                    [sys.executable, "-m", "cliphistory"],
                    cwd=project_root,
                    env=env,
                    stdout=stdout,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            try:
                def history_texts() -> list[str]:
                    path = home / "history.json"
                    if not path.exists():
                        return []
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        return []
                    return [item.get("text", "") for item in payload.get("items", [])]

                _wait_for(lambda: (home / "ready").exists() and token_1 in history_texts(), 12, home)
                assert set_clipboard_text(token_2)
                _wait_for(lambda: token_2 in history_texts(), 8, home)
                texts = history_texts()
                assert texts[0] == token_2
                assert token_1 in texts
            finally:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
        finally:
            if not restore_clipboard(snapshot):
                raise AssertionError("failed to restore the clipboard after listener test")


def run_self_test() -> int:
    print(f"INPUT size {input_struct_size()}")
    if sys.maxsize > 2**32:
        assert input_struct_size() == 40, input_struct_size()
    icon, owned = create_app_icon()
    assert icon, "icon was not created"
    if owned:
        user32.DestroyIcon(icon)
    _x, _y, area = cursor_work_area()
    assert area.right > area.left and area.bottom > area.top
    with tempfile.TemporaryDirectory(prefix="cliphistory-store-") as temporary:
        _check_store(Path(temporary))
    with tempfile.TemporaryDirectory(prefix="cliphistory-ui-") as temporary:
        _check_popup(Path(temporary))
    project_root = Path(__file__).resolve().parents[1]
    _check_process(project_root)
    wrote = _check_clipboard_roundtrip()
    if wrote:
        _check_listener(project_root)
    print("self-test ok")
    return 0
