"""Clipboard history window."""

from __future__ import annotations

import json
import os
import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from datetime import datetime

from cliphistory.paths import data_dir
from cliphistory.platform_win import (
    MB_ICONERROR,
    MB_OK,
    Suppress,
    WinBridge,
    can_paste_into,
    cursor_work_area,
    enable_dpi,
    force_foreground,
    hide_native_border,
    log,
    log_exception,
    message_box,
    read_clipboard_text,
    same_top_level,
    send_ctrl_v,
    set_clipboard_text,
    window_title,
    write_ready_marker,
    confirm_clear,
)
from cliphistory.store import ClipItem, HistoryStore

BG = "#1b1d22"
PANEL = "#23262d"
FIELD = "#2c3038"
FG = "#e7e9ee"
MUTED = "#9aa3b2"
ACCENT = "#7eb6ff"
SELECT = "#1d4f91"
BORDER = "#3a404c"
OK = "#8fd0a8"
WARN = "#e3b341"


def configure_scaling(root: tk.Tk) -> None:
    try:
        pixels = float(root.winfo_fpixels("1i"))
        root.tk.call("tk", "scaling", pixels / 72.0)
    except tk.TclError:
        pass


def choose_font(root: tk.Misc, names: tuple[str, ...], size: int, *, bold: bool = False) -> tuple:
    families = set(tkfont.families(root))
    weight = "bold" if bold else "normal"
    for name in names:
        if name in families:
            return (name, size, weight)
    return ("TkDefaultFont", size, weight)


def format_time(iso: str) -> str:
    try:
        stamp = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    now = datetime.now()
    if stamp.date() == now.date():
        return stamp.strftime("%H:%M")
    if stamp.year == now.year:
        return stamp.strftime("%m-%d %H:%M")
    return stamp.strftime("%Y-%m-%d")


def preview(text: str, limit: int = 46) -> str:
    flat = " ".join(text.split())
    if not flat:
        return "空白"
    if len(flat) > limit:
        return flat[: limit - 1] + "…"
    return flat


def row_label(item: ClipItem) -> str:
    return f"{format_time(item.copied_at)}    {preview(item.text)}"


def load_window_size() -> tuple[int, int]:
    path = data_dir() / "window.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        width = max(700, min(int(data["width"]), 1600))
        height = max(620, min(int(data["height"]), 1400))
        return width, height
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return 920, 800


def save_window_size(width: int, height: int) -> None:
    path = data_dir() / "window.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"width": width, "height": height}), encoding="utf-8")


class Popup:
    def __init__(self, root: tk.Tk, store: HistoryStore, on_paste, on_copy, on_quit) -> None:
        self.store = store
        self.on_paste = on_paste
        self.on_copy = on_copy
        self.on_quit = on_quit
        self.visible_items: list[ClipItem] = []
        self._target = 0
        self._refreshing = False
        self._status_token = 0
        self._width, self._height = load_window_size()
        self.query = tk.StringVar()
        self.meta = tk.StringVar()
        self.status = tk.StringVar()
        self.target_hint = tk.StringVar(value="用 Ctrl+Shift+V 打开时，Enter 会贴回刚才的窗口")
        self.hotkey_label = tk.StringVar(value="Ctrl+Shift+V")

        self.ui_font = choose_font(root, ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"), 10)
        self.title_font = choose_font(root, ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"), 15, bold=True)
        self.mono_font = choose_font(root, ("Cascadia Mono", "Cascadia Code", "Consolas"), 11)
        self.small_font = choose_font(root, ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"), 9)

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.title("剪贴板历史")
        self.win.configure(bg=BG, highlightthickness=0, bd=0)
        self.win.minsize(700, 620)
        self.win.geometry(f"{self._width}x{self._height}")
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self.win.bind("<Escape>", lambda _event: self.hide())
        self.win.bind("<Configure>", self._on_configure)
        self._grips: list[tk.Frame] = []

        accent = tk.Frame(self.win, bg=ACCENT, height=3, cursor="fleur")
        accent.pack(fill="x")
        body = tk.Frame(self.win, bg=BG, highlightthickness=0, bd=0)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=3)
        body.grid_rowconfigure(4, weight=2)

        header = tk.Frame(body, bg=BG, cursor="fleur")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        title = tk.Label(header, text="剪贴板历史", bg=BG, fg=FG, font=self.title_font, cursor="fleur")
        title.pack(side="left")
        close = tk.Label(header, text="×", bg=BG, fg=MUTED, font=self.title_font, cursor="hand2", padx=4)
        close.pack(side="right")
        close.bind("<Button-1>", lambda _event: self.hide())
        close.bind("<Enter>", lambda _event: close.configure(fg="#ffffff"))
        close.bind("<Leave>", lambda _event: close.configure(fg=MUTED))
        hotkey = tk.Label(header, textvariable=self.hotkey_label, bg=BG, fg=MUTED, font=self.small_font, cursor="fleur")
        hotkey.pack(side="right", padx=(0, 12))
        for widget in (accent, header, title, hotkey):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag_window)

        self.search = tk.Entry(
            body,
            textvariable=self.query,
            bg=FIELD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=self.ui_font,
            exportselection=False,
        )
        self.search.grid(row=1, column=0, sticky="ew", ipady=6, pady=(0, 10))
        self.placeholder = tk.Label(
            self.search,
            text="筛选路径、报错、SQL…",
            bg=FIELD,
            fg=MUTED,
            font=self.ui_font,
        )
        self.placeholder.place(x=10, y=7)
        self.placeholder.bind("<Button-1>", lambda _event: self.search.focus_set())
        self.search.bind("<Down>", self._focus_list)
        self.search.bind("<Return>", self.paste_current)
        self.search.bind("<Control-c>", self.copy_current)
        self.search.bind("<Control-C>", self.copy_current)
        self.win.bind("<Control-f>", self._focus_search)
        self.win.bind("<Control-F>", self._focus_search)

        list_border = tk.Frame(body, bg=BORDER, padx=1, pady=1)
        list_border.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        list_border.grid_columnconfigure(0, weight=1)
        list_border.grid_rowconfigure(0, weight=1)
        self.list = tk.Listbox(
            list_border,
            bg=PANEL,
            fg=FG,
            selectbackground=SELECT,
            selectforeground="#ffffff",
            activestyle="none",
            exportselection=False,
            borderwidth=0,
            highlightthickness=0,
            font=self.ui_font,
            relief="flat",
            height=8,
        )
        self.list.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_border, orient="vertical", command=self.list.yview, style="Clip.Vertical.TScrollbar")
        scroll.grid(row=0, column=1, sticky="ns")
        self.list.configure(yscrollcommand=scroll.set)
        self.empty = tk.Label(list_border, text="还没有复制过文本", bg=PANEL, fg=MUTED, font=self.ui_font)
        self.list.bind("<<ListboxSelect>>", self._on_select)
        self.list.bind("<Return>", self.paste_current)
        self.list.bind("<Double-Button-1>", self.paste_current)
        self.list.bind("<Delete>", self.delete_current)
        self.list.bind("<Control-c>", self.copy_current)
        self.list.bind("<Control-C>", self.copy_current)
        self.list.bind("<Up>", self._list_up)
        self.list.bind("<Button-3>", self._popup_menu)

        tk.Label(body, textvariable=self.meta, bg=BG, fg=MUTED, font=self.small_font, anchor="w").grid(
            row=3, column=0, sticky="ew", pady=(0, 4)
        )

        detail_border = tk.Frame(body, bg=BORDER, padx=1, pady=1)
        detail_border.grid(row=4, column=0, sticky="nsew")
        detail_border.grid_columnconfigure(0, weight=1)
        detail_border.grid_rowconfigure(0, weight=1)
        self.detail = tk.Text(
            detail_border,
            bg="#17191e",
            fg=FG,
            insertbackground=FG,
            relief="flat",
            highlightthickness=0,
            font=self.mono_font,
            wrap="word",
            width=48,
            undo=False,
            exportselection=False,
            padx=10,
            pady=8,
            height=7,
        )
        self.detail.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(
            detail_border, orient="vertical", command=self.detail.yview, style="Clip.Vertical.TScrollbar"
        )
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.bind("<Key>", self._block_detail_key)
        self.detail.bind("<Return>", self.paste_current)
        self.detail.bind("<<Paste>>", lambda _event: "break")
        self.detail.bind("<Control-v>", lambda _event: "break")
        self.detail.bind("<Control-V>", lambda _event: "break")
        self.detail.bind("<Control-c>", self._copy_from_detail)
        self.detail.bind("<Control-C>", self._copy_from_detail)
        self.detail.bind("<Control-a>", self._select_detail)
        self.detail.bind("<Control-A>", self._select_detail)

        footer = tk.Frame(body, bg=BG)
        footer.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        tk.Label(
            footer,
            text="Enter 粘贴    Ctrl+C 复制    Del 删除    Esc 关闭",
            bg=BG,
            fg=MUTED,
            font=self.small_font,
        ).pack(side="left")
        tk.Label(footer, textvariable=self.status, bg=BG, fg=OK, font=self.small_font).pack(side="right")
        tk.Label(body, textvariable=self.target_hint, bg=BG, fg=ACCENT, font=self.small_font, anchor="w").grid(
            row=6, column=0, sticky="ew", pady=(4, 0)
        )

        self.menu = tk.Menu(self.win, tearoff=0)
        self.menu.add_command(label="粘贴", command=self.paste_current)
        self.menu.add_command(label="复制", command=self.copy_current)
        self.menu.add_command(label="删除", command=self.delete_current)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.on_quit)

        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Clip.Vertical.TScrollbar",
            background=BORDER,
            troughcolor=PANEL,
            bordercolor=PANEL,
            arrowcolor=FG,
            relief="flat",
        )
        style.map("Clip.Vertical.TScrollbar", background=[("active", "#4c5566")])
        self.query.trace_add("write", self._on_query)
        self._install_edge_grips()
        self.win.update_idletasks()
        hide_native_border(self.hwnd())
        self.refresh()

    def hwnd(self) -> int:
        try:
            return int(self.win.winfo_id())
        except tk.TclError:
            return 0

    def is_visible(self) -> bool:
        try:
            return self.win.state() != "withdrawn"
        except tk.TclError:
            return False

    def set_hotkey_available(self, available: bool) -> None:
        self.hotkey_label.set("Ctrl+Shift+V" if available else "快捷键被占用")

    def set_status(self, text: str, *, sticky: bool = False) -> None:
        self.status.set(text)
        self._status_token += 1
        token = self._status_token
        if text and not sticky:
            self.win.after(2600, lambda: self._clear_status(token))

    def _clear_status(self, token: int) -> None:
        if token == self._status_token:
            self.status.set("")

    def _on_query(self, *_args) -> None:
        self._sync_placeholder()
        self.refresh()

    def _sync_placeholder(self) -> None:
        if self.query.get():
            self.placeholder.place_forget()
        else:
            self.placeholder.place(x=10, y=7)

    def _start_drag(self, event) -> None:
        self._drag_dx = event.x_root - self.win.winfo_x()
        self._drag_dy = event.y_root - self.win.winfo_y()

    def _drag_window(self, event) -> None:
        if not hasattr(self, "_drag_dx"):
            return
        x = event.x_root - self._drag_dx
        y = event.y_root - self._drag_dy
        self.win.geometry(f"+{int(x)}+{int(y)}")

    def _install_edge_grips(self) -> None:
        specs = (
            ("n", "size_ns", {"relx": 0, "rely": 0, "relwidth": 1, "height": 5}),
            ("s", "size_ns", {"relx": 0, "rely": 1, "relwidth": 1, "height": 5, "anchor": "sw"}),
            ("w", "size_we", {"relx": 0, "rely": 0, "width": 5, "relheight": 1}),
            ("e", "size_we", {"relx": 1, "rely": 0, "width": 5, "relheight": 1, "anchor": "ne"}),
            ("nw", "size_nw_se", {"x": 0, "y": 0, "width": 12, "height": 12}),
            ("ne", "size_ne_sw", {"relx": 1, "y": 0, "width": 12, "height": 12, "anchor": "ne"}),
            ("sw", "size_ne_sw", {"x": 0, "rely": 1, "width": 12, "height": 12, "anchor": "sw"}),
            ("se", "size_nw_se", {"relx": 1, "rely": 1, "width": 12, "height": 12, "anchor": "se"}),
        )
        for edge, cursor, place in specs:
            grip = tk.Frame(self.win, bg=ACCENT if edge == "n" else BG, cursor=cursor, highlightthickness=0, bd=0)
            grip.place(**place)
            grip.bind("<ButtonPress-1>", lambda event, name=edge: self._begin_resize(event, name))
            grip.bind("<B1-Motion>", self._do_resize)
            self._grips.append(grip)
        self._lift_grips()

    def _lift_grips(self) -> None:
        for grip in self._grips:
            grip.lift()

    def _begin_resize(self, event, edge: str):
        self._resize = (edge, self.win.winfo_x(), self.win.winfo_y(), self.win.winfo_width(), self.win.winfo_height(), event.x_root, event.y_root)
        return "break"

    def _do_resize(self, event):
        if not hasattr(self, "_resize"):
            return "break"
        edge, origin_x, origin_y, origin_w, origin_h, pointer_x, pointer_y = self._resize
        dx = event.x_root - pointer_x
        dy = event.y_root - pointer_y
        x, y, width, height = origin_x, origin_y, origin_w, origin_h
        min_w, min_h = self.win.minsize()
        if "e" in edge:
            width = max(min_w, origin_w + dx)
        if "s" in edge:
            height = max(min_h, origin_h + dy)
        if "w" in edge:
            width = max(min_w, origin_w - dx)
            x = origin_x + origin_w - width
        if "n" in edge:
            height = max(min_h, origin_h - dy)
            y = origin_y + origin_h - height
        self.win.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")
        return "break"

    def _focus_search(self, _event=None):
        self.search.focus_set()
        self.search.select_range(0, "end")
        self.search.icursor("end")
        return "break"

    def show(self, target: int) -> None:
        self._target = int(target or 0) if can_paste_into(int(target or 0)) else 0
        self.target_hint.set(self._hint())
        if self.query.get():
            self.query.set("")
        else:
            self.refresh()
        self.win.overrideredirect(True)
        self.win.deiconify()
        self.win.lift()
        self.win.attributes("-topmost", True)
        hide_native_border(self.hwnd())
        self._lift_grips()
        self._place()
        self.win.focus_force()
        self.search.focus_set()
        hwnd = self.hwnd()
        if hwnd:
            force_foreground(hwnd)

    def hide(self) -> None:
        self._remember_size()
        self.win.withdraw()

    def refresh(self) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            previous = self.current_text()
            items = self.store.search(self.query.get())
            self.visible_items = items
            self.list.delete(0, "end")
            for item in items:
                self.list.insert("end", row_label(item))
            if not items:
                message = "没有匹配的记录" if self.query.get().strip() else "还没有复制过文本"
                self.empty.configure(text=message)
                self.empty.place(relx=0.5, rely=0.5, anchor="center")
                self.empty.lift()
                self._set_detail(None, 0)
                return
            self.empty.place_forget()
            index = 0
            if previous:
                for position, item in enumerate(items):
                    if item.text == previous:
                        index = position
                        break
            self.list.selection_clear(0, "end")
            self.list.selection_set(index)
            self.list.activate(index)
            self.list.see(index)
            self._set_detail(items[index], index)
        finally:
            self._refreshing = False

    def current_item(self) -> ClipItem | None:
        if not self.visible_items:
            return None
        selected = self.list.curselection()
        index = selected[0] if selected else 0
        if index < 0 or index >= len(self.visible_items):
            return None
        return self.visible_items[index]

    def current_text(self) -> str | None:
        item = self.current_item()
        return item.text if item else None

    def paste_current(self, _event=None):
        item = self.current_item()
        if item is None:
            return "break"
        text = item.text
        target = self._target
        if not target:
            self.on_copy(text)
            self.set_status("已复制，到目标窗口粘贴")
            return "break"
        self.hide()
        self.on_paste(text, target)
        return "break"

    def copy_current(self, _event=None):
        item = self.current_item()
        if item is None:
            return "break"
        self.on_copy(item.text)
        return "break"

    def delete_current(self, _event=None):
        item = self.current_item()
        if item is None:
            return "break"
        self.store.remove(item.text)
        self.refresh()
        self.set_status("已删除")
        return "break"

    def save_geometry(self) -> None:
        self._remember_size()
        save_window_size(self._width, self._height)

    def _set_detail(self, item: ClipItem | None, index: int) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if item is None:
            self.meta.set("")
            return
        lines = item.text.count("\n") + 1
        label = f"{format_time(item.copied_at)}    {lines} 行 · {len(item.text)} 字符    {index + 1}/{len(self.visible_items)}"
        if item.truncated:
            label += "    已截断"
        self.meta.set(label)
        self.detail.insert("1.0", item.text)
        self.detail.mark_set("insert", "1.0")
        self.detail.see("1.0")

    def _hint(self) -> str:
        if not self._target:
            return "Enter 复制到剪贴板。用 Ctrl+Shift+V 打开时，会直接贴回刚才的窗口"
        title = window_title(self._target).strip() or "上一个窗口"
        if len(title) > 42:
            title = title[:41] + "…"
        return f"Enter 粘贴到：{title}"

    def _place(self) -> None:
        x, y, area = cursor_work_area()
        width, height = self._width, self._height
        x -= width // 2
        y -= 28
        x = max(area.left + 8, min(x, area.right - width - 8))
        y = max(area.top + 8, min(y, area.bottom - height - 8))
        self.win.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

    def _remember_size(self) -> None:
        if not self.is_visible():
            return
        width = int(self.win.winfo_width())
        height = int(self.win.winfo_height())
        if width >= 700 and height >= 620:
            self._width, self._height = width, height

    def _on_configure(self, event) -> None:
        if event.widget is self.win and self.is_visible() and event.width >= 700 and event.height >= 620:
            self._width, self._height = int(event.width), int(event.height)

    def _on_select(self, _event=None) -> None:
        selected = self.list.curselection()
        if not selected:
            return
        index = selected[0]
        if 0 <= index < len(self.visible_items):
            self._set_detail(self.visible_items[index], index)

    def _focus_list(self, _event=None):
        if not self.visible_items:
            return "break"
        self.list.focus_set()
        self.list.selection_clear(0, "end")
        self.list.selection_set(0)
        self.list.activate(0)
        self._on_select()
        return "break"

    def _list_up(self, _event=None):
        selected = self.list.curselection()
        if not selected or selected[0] == 0:
            self.search.focus_set()
            self.search.icursor("end")
            return "break"
        return None

    def _popup_menu(self, event) -> str:
        if self.visible_items:
            index = self.list.nearest(event.y)
            if 0 <= index < len(self.visible_items):
                self.list.selection_clear(0, "end")
                self.list.selection_set(index)
                self.list.activate(index)
                self._on_select()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return "break"

    def _block_detail_key(self, event) -> str | None:
        if event.state & 0x4:
            return None
        if event.keysym in {
            "Left",
            "Right",
            "Up",
            "Down",
            "Home",
            "End",
            "Prior",
            "Next",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Tab",
        }:
            return None
        return "break"

    def _copy_from_detail(self, _event=None):
        try:
            if self.detail.get("sel.first", "sel.last"):
                return None
        except tk.TclError:
            pass
        return self.copy_current()

    def _select_detail(self, _event=None):
        self.detail.tag_add("sel", "1.0", "end-1c")
        return "break"


class App:
    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self.suppress = Suppress()
        self.store = HistoryStore(data_dir() / "history.json")
        self.root = tk.Tk()
        self.root.withdraw()
        configure_scaling(self.root)
        self.popup = Popup(self.root, self.store, self._paste, self._copy, self._quit)
        self.bridge = WinBridge(self.events, self.suppress)
        self._closing = False
        self.already_running = False
        if not self.bridge.start():
            self.already_running = True
            self.root.destroy()
            if os.environ.get("CLIPHISTORY_QUIET") != "1":
                message_box("剪贴板历史已经在运行。\n按 Ctrl+Shift+V 打开，或单击托盘图标。")
            return
        self.root.after(40, self._poll)

    def run(self) -> None:
        if self.already_running:
            return
        try:
            self.root.mainloop()
        finally:
            try:
                self.popup.save_geometry()
            except Exception:
                pass
            self.bridge.stop()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._dispatch(kind, payload)
        except queue.Empty:
            pass
        except Exception:
            log_exception("poll failed")
        if not self._closing:
            self.root.after(40, self._poll)

    def _dispatch(self, kind: str, payload) -> None:
        if kind == "clipboard":
            self._remember(payload)
        elif kind == "clipboard_retry":
            self._retry_clipboard(int(payload))
        elif kind == "hotkey":
            self._on_hotkey(int(payload or 0))
        elif kind == "toggle":
            self._toggle()
        elif kind == "clear":
            self._clear()
        elif kind == "quit":
            self._quit()
        elif kind == "ready":
            self._on_ready(payload)
        elif kind == "fatal":
            message_box(str(payload), flags=MB_OK | MB_ICONERROR)
            self._quit()

    def _remember(self, text: str) -> None:
        result = self.store.add(text)
        if result in {"new", "moved"} and self.popup.is_visible():
            self.popup.refresh()

    def _retry_clipboard(self, attempt: int) -> None:
        if attempt > 10:
            return
        status, text = read_clipboard_text()
        if status == "busy":
            self.root.after(50, lambda: self._retry_clipboard(attempt + 1))
            return
        if text and not self.suppress.matches(text):
            self._remember(text)

    def _on_hotkey(self, hwnd: int) -> None:
        if self.popup.is_visible():
            self.popup.hide()
            return
        target = 0 if self._is_ours(hwnd) else hwnd
        self.popup.show(target)

    def _toggle(self) -> None:
        if self.popup.is_visible():
            self.popup.hide()
        else:
            self.popup.show(0)

    def _clear(self) -> None:
        if not confirm_clear():
            return
        self.store.clear()
        self.popup.refresh()
        self.popup.set_status("历史已清空")

    def _quit(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            self.popup.save_geometry()
        except Exception:
            pass
        self.root.quit()

    def _on_ready(self, info: dict) -> None:
        write_ready_marker()
        hotkey_ok = bool(info.get("hotkey"))
        tray_ok = bool(info.get("tray"))
        self.popup.set_hotkey_available(hotkey_ok)
        log(f"ready hotkey={hotkey_ok} tray={tray_ok}")
        if os.environ.get("CLIPHISTORY_QUIET") != "1" and (not tray_ok or not hotkey_ok):
            self.popup.show(0)
        if not hotkey_ok:
            self.popup.set_status("Ctrl+Shift+V 已被其他程序占用", sticky=True)
        elif not tray_ok:
            self.popup.set_status("没有托盘图标，右键列表可以退出", sticky=True)
        if os.environ.get("CLIPHISTORY_EXIT_AFTER_READY") == "1":
            self.root.after(300, self._quit)

    def _paste(self, text: str, target: int) -> None:
        self.suppress.arm(text)
        if not set_clipboard_text(text):
            log("set clipboard failed during paste")
            self.popup.show(target)
            self.popup.set_status("写回剪贴板失败")
            return
        if not target:
            return
        self.root.after(60, lambda: self._finish_paste(target))

    def _finish_paste(self, target: int) -> None:
        if not force_foreground(target):
            log(f"focus restore failed target={target}")
            self.popup.show(target)
            self.popup.set_status("已放回剪贴板，但没能切回上一个窗口")
            return
        self.root.after(40, self._send_paste)

    def _send_paste(self) -> None:
        if not send_ctrl_v():
            log("SendInput Ctrl+V failed")

    def _copy(self, text: str) -> None:
        self.suppress.arm(text)
        if set_clipboard_text(text):
            self.popup.set_status("已复制")
        else:
            self.popup.set_status("复制失败")

    def _is_ours(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        return same_top_level(hwnd, self.popup.hwnd()) or same_top_level(hwnd, self.bridge.hwnd)


def main() -> None:
    enable_dpi()
    if "--self-test" in sys.argv:
        from cliphistory.selftest import run_self_test

        raise SystemExit(run_self_test())
    try:
        App().run()
    except Exception as exc:
        log_exception("startup failed")
        message_box(f"启动失败：{exc}\n详情已写入日志。", flags=MB_OK | MB_ICONERROR)
