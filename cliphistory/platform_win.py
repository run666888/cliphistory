"""Win32 clipboard, global hotkey, tray icon, and paste-back helpers.

Uses ctypes only so the tool does not need third-party packages.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
import traceback
from ctypes import wintypes
from dataclasses import dataclass

from cliphistory.paths import data_dir

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
WM_HOTKEY = 0x0312
WM_CLIPBOARDUPDATE = 0x031D
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_TRAY = WM_APP + 20
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_V = 0x56
VK_CONTROL = 0x11
VK_MENU = 0x12
HOTKEY_ID = 1
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
NIF_INFO = 0x10
NIIF_INFO = 0x1
NIIF_NOSOUND = 0x10
MF_STRING = 0
MF_SEPARATOR = 0x800
TPM_RIGHTBUTTON = 0x0002
TPM_BOTTOMALIGN = 0x0020
TPM_RETURNCMD = 0x0100
SW_RESTORE = 9
GA_ROOT = 2
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
BI_RGB = 0
DIB_RGB_COLORS = 0
IMAGE_ICON = 1
IDI_APPLICATION = 32512
ERROR_ALREADY_EXISTS = 183
MB_OK = 0x0
MB_YESNO = 0x4
MB_ICONINFORMATION = 0x40
MB_ICONQUESTION = 0x20
MB_ICONERROR = 0x10
MB_DEFBUTTON2 = 0x100
IDYES = 6
CMD_OPEN = 1
CMD_CLEAR = 2
CMD_EXIT = 3
_SKIP_PASTE_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd"}

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _bind() -> None:
    user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    user32.RegisterClassExW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.AddClipboardFormatListener.argtypes = [wintypes.HWND]
    user32.AddClipboardFormatListener.restype = wintypes.BOOL
    user32.RemoveClipboardFormatListener.argtypes = [wintypes.HWND]
    user32.RemoveClipboardFormatListener.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
    user32.EnumClipboardFormats.restype = wintypes.UINT
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR]
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = wintypes.UINT
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        ctypes.c_void_p,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
    user32.CreateIconIndirect.restype = wintypes.HICON
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    kernel32.CreateMutexW.argtypes = [wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
    gdi32.CreateBitmap.restype = wintypes.HBITMAP
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT


_bind()

_clip_lock = threading.Lock()
_logger_ready = False


def log(message: str) -> None:
    global _logger_ready
    try:
        directory = data_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "log.txt"
        if path.exists() and path.stat().st_size > 200_000:
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            stamp = time.strftime("%Y-%m-%d %H:%M:%S")
            handle.write(f"{stamp} {message}\n")
        _logger_ready = True
    except OSError:
        return


def log_exception(prefix: str) -> None:
    log(prefix + "\n" + traceback.format_exc())


def enable_dpi() -> None:
    try:
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def message_box(text: str, title: str = "剪贴板历史", flags: int = MB_OK | MB_ICONINFORMATION) -> int:
    return int(user32.MessageBoxW(None, text, title, flags))


def confirm_clear() -> bool:
    result = message_box(
        "清空全部复制记录？此操作不能撤销。",
        flags=MB_YESNO | MB_ICONQUESTION | MB_DEFBUTTON2,
    )
    return result == IDYES


class Suppress:
    """Ignore the clipboard update caused by our own copy or paste."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._text: str | None = None
        self._until = 0.0

    def arm(self, text: str) -> None:
        with self._lock:
            self._text = text
            self._until = time.monotonic() + 0.8

    def matches(self, text: str) -> bool:
        with self._lock:
            if self._text == text and time.monotonic() < self._until:
                self._text = None
                return True
            return False


def _open_clipboard() -> bool:
    for _ in range(10):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.01)
    return False


def read_clipboard_text() -> tuple[str, str | None]:
    """Return (ok|busy, text or None). None text means the clipboard is not plain text."""
    if not _clip_lock.acquire(timeout=0.4):
        return "busy", None
    try:
        if not user32.OpenClipboard(None):
            return "busy", None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return "ok", None
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return "busy", None
            try:
                size = int(kernel32.GlobalSize(handle))
                chars = max(size // 2, 0)
                text = ctypes.wstring_at(pointer, chars) if chars else ""
                return "ok", text.split("\x00", 1)[0]
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    finally:
        _clip_lock.release()


def set_clipboard_text(text: str) -> bool:
    encoded = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(encoded)
    allocated = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not allocated:
        return False
    pointer = kernel32.GlobalLock(allocated)
    if not pointer:
        kernel32.GlobalFree(allocated)
        return False
    try:
        ctypes.memmove(pointer, encoded, size)
    finally:
        kernel32.GlobalUnlock(allocated)
    if not _clip_lock.acquire(timeout=1):
        kernel32.GlobalFree(allocated)
        return False
    try:
        if not _open_clipboard():
            kernel32.GlobalFree(allocated)
            return False
        try:
            if not user32.EmptyClipboard() or not user32.SetClipboardData(CF_UNICODETEXT, allocated):
                kernel32.GlobalFree(allocated)
                return False
            return True
        finally:
            user32.CloseClipboard()
    finally:
        _clip_lock.release()


kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL


@dataclass
class ClipSnapshot:
    """A clipboard we know how to put back.

    restorable is false when formats other than plain text are present.
    Those are left untouched so a test cannot destroy a screenshot or file copy.
    """

    text: str | None
    restorable: bool


def snapshot_clipboard() -> ClipSnapshot | None:
    if not _clip_lock.acquire(timeout=1):
        return None
    try:
        if not user32.OpenClipboard(None):
            return None
        try:
            formats: list[int] = []
            fmt = 0
            while True:
                fmt = int(user32.EnumClipboardFormats(fmt))
                if not fmt:
                    break
                formats.append(fmt)
        finally:
            user32.CloseClipboard()
    finally:
        _clip_lock.release()
    if any(fmt != CF_UNICODETEXT for fmt in formats):
        return ClipSnapshot(text=None, restorable=False)
    if not formats:
        return ClipSnapshot(text=None, restorable=True)
    status, text = read_clipboard_text()
    if status != "ok":
        return None
    return ClipSnapshot(text=text or None, restorable=True)


def restore_clipboard(snapshot: ClipSnapshot) -> bool:
    if not snapshot.restorable:
        return False
    if not snapshot.text:
        if not _clip_lock.acquire(timeout=1):
            return False
        try:
            if not _open_clipboard():
                return False
            try:
                return bool(user32.EmptyClipboard())
            finally:
                user32.CloseClipboard()
        finally:
            _clip_lock.release()
    return set_clipboard_text(snapshot.text)


def window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def window_class(hwnd: int) -> str:
    if not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def root_window(hwnd: int) -> int:
    if not hwnd:
        return 0
    root = user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def same_top_level(left: int, right: int) -> bool:
    if not left or not right:
        return False
    return root_window(left) == root_window(right)


def can_paste_into(hwnd: int) -> bool:
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if window_class(root_window(hwnd)) in _SKIP_PASTE_CLASSES:
        return False
    return True


def force_foreground(hwnd: int) -> bool:
    if not can_paste_into(hwnd):
        return False
    target = root_window(hwnd)
    if user32.IsIconic(target):
        user32.ShowWindow(target, SW_RESTORE)
    user32.SetForegroundWindow(target)
    user32.BringWindowToTop(target)
    if user32.GetForegroundWindow() == target:
        return True
    current = int(user32.GetForegroundWindow() or 0)
    current_thread = user32.GetWindowThreadProcessId(current, None) if current else 0
    target_thread = user32.GetWindowThreadProcessId(target, None)
    this_thread = kernel32.GetCurrentThreadId()
    attached: list[tuple[int, int]] = []

    def attach(source: int, dest: int) -> None:
        if source and dest and source != dest and user32.AttachThreadInput(source, dest, True):
            attached.append((source, dest))

    try:
        attach(this_thread, current_thread)
        attach(this_thread, target_thread)
        user32.SetForegroundWindow(target)
        user32.BringWindowToTop(target)
    finally:
        for source, dest in reversed(attached):
            user32.AttachThreadInput(source, dest, False)
    if user32.GetForegroundWindow() == target:
        return True
    # Last resort. Alt is released before the caller sends Ctrl+V.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.SetForegroundWindow(target)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    return bool(user32.GetForegroundWindow() == target)


def send_ctrl_v() -> bool:
    events = (INPUT * 4)()
    sequence = (
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    )
    for index, (virtual_key, flags) in enumerate(sequence):
        events[index].type = INPUT_KEYBOARD
        events[index].union.ki.wVk = virtual_key
        events[index].union.ki.dwFlags = flags
    sent = user32.SendInput(4, ctypes.byref(events), ctypes.sizeof(INPUT))
    return int(sent) == 4


def cursor_work_area() -> tuple[int, int, RECT]:
    point = POINT()
    user32.GetCursorPos(ctypes.byref(point))
    monitor = user32.MonitorFromPoint(point, 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return int(point.x), int(point.y), info.rcWork
    fallback = RECT(0, 0, 1280, 720)
    return int(point.x), int(point.y), fallback


def create_app_icon(size: int = 32) -> tuple[int, bool]:
    """Return (hicon, should_destroy). Falls back to the shared system icon."""
    try:
        pixels = bytearray(size * size * 4)
        for y in range(size):
            for x in range(size):
                red, green, blue = 43, 127, 255
                on_line = False
                for line_y in (11, 16, 21):
                    if line_y <= y <= line_y + 1 and 7 <= x <= size - 8:
                        on_line = True
                        break
                if on_line:
                    red, green, blue = 255, 255, 255
                offset = ((size - 1 - y) * size + x) * 4
                pixels[offset : offset + 4] = bytes((blue, green, red, 255))
        header = BITMAPINFOHEADER(
            biSize=ctypes.sizeof(BITMAPINFOHEADER),
            biWidth=size,
            biHeight=size,
            biPlanes=1,
            biBitCount=32,
            biCompression=BI_RGB,
        )
        info = BITMAPINFO(bmiHeader=header)
        screen = user32.GetDC(None)
        bits = ctypes.c_void_p()
        color = gdi32.CreateDIBSection(screen, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        user32.ReleaseDC(None, screen)
        if not color or not bits:
            raise OSError("CreateDIBSection failed")
        ctypes.memmove(bits, bytes(pixels), len(pixels))
        mask = gdi32.CreateBitmap(size, size, 1, 1, None)
        icon_info = ICONINFO(True, 0, 0, mask, color)
        icon = user32.CreateIconIndirect(ctypes.byref(icon_info))
        gdi32.DeleteObject(color)
        if mask:
            gdi32.DeleteObject(mask)
        if icon:
            return int(icon), True
    except Exception:
        log_exception("create icon failed")
    fallback = user32.LoadImageW(None, IDI_APPLICATION, IMAGE_ICON, 32, 32, 0)
    return int(fallback or 0), False


def _fill_notify_icon(hwnd: int, icon: int, *, balloon: bool) -> NOTIFYICONDATAW:
    data = NOTIFYICONDATAW()
    data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
    data.hWnd = hwnd
    data.uID = 1
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    data.uCallbackMessage = WM_TRAY
    data.hIcon = icon
    data.szTip = "剪贴板历史  ·  Ctrl+Shift+V"
    if balloon:
        data.uFlags |= NIF_INFO
        data.szInfoTitle = "剪贴板历史在运行"
        data.szInfo = "按 Ctrl+Shift+V 查看最近复制的文本"
        data.dwInfoFlags = NIIF_INFO | NIIF_NOSOUND
    return data


class WinBridge:
    """Hidden window that owns the hotkey, clipboard listener, and tray icon."""

    def __init__(self, events, suppress: Suppress) -> None:
        self.events = events
        self.suppress = suppress
        self.hwnd = 0
        self.thread: threading.Thread | None = None
        self.ready = threading.Event()
        self.hotkey_ok = False
        self.tray_ok = False
        self._mutex = None
        self._wndproc = WNDPROC(self._wndproc_impl)
        self._icon = 0
        self._destroy_icon = False
        self._class_name = "ClipHistoryMessageWindow"
        self.already_running = False
        self._last_tray_click = 0.0

    def start(self) -> bool:
        name = os.environ.get("CLIPHISTORY_MUTEX") or "Local\\ClipHistory.SingleInstance"
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, name)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            if handle:
                kernel32.CloseHandle(handle)
            self.already_running = True
            self.ready.set()
            return False
        self._mutex = handle
        self.thread = threading.Thread(target=self._thread_main, name="cliphistory-win32", daemon=True)
        self.thread.start()
        return True

    def stop(self) -> None:
        self.ready.wait(timeout=2)
        hwnd = self.hwnd
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        thread = self.thread
        if thread and thread.is_alive() and threading.current_thread() is not thread:
            thread.join(timeout=2)
        self._remove_tray()

    def _thread_main(self) -> None:
        try:
            self._create_window()
        except Exception:
            log_exception("win32 window failed")
            self.events.put(("fatal", "后台窗口创建失败，详见日志。"))
            self.ready.set()
            return
        self.ready.set()
        self.events.put(("ready", {"hotkey": self.hotkey_ok, "tray": self.tray_ok}))
        try:
            self._message_loop()
        finally:
            self._remove_tray()

    def _create_window(self) -> None:
        try:
            shell32.SetCurrentProcessExplicitAppUserModelID("ClipHistory.TextHistory")
        except Exception:
            pass
        instance = kernel32.GetModuleHandleW(None)
        self._icon, self._destroy_icon = create_app_icon()
        window_class = WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(WNDCLASSEXW)
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = instance
        window_class.hIcon = self._icon or None
        window_class.lpszClassName = self._class_name
        atom = user32.RegisterClassExW(ctypes.byref(window_class))
        if not atom:
            raise OSError(f"RegisterClassExW failed ({ctypes.get_last_error()})")
        hwnd = user32.CreateWindowExW(0, self._class_name, "剪贴板历史", 0, 0, 0, 0, 0, None, None, instance, None)
        if not hwnd:
            raise OSError(f"CreateWindowExW failed ({ctypes.get_last_error()})")
        self.hwnd = int(hwnd)
        if not user32.AddClipboardFormatListener(self.hwnd):
            log(f"AddClipboardFormatListener failed ({ctypes.get_last_error()})")
        if os.environ.get("CLIPHISTORY_HOTKEY", "1") != "0":
            self.hotkey_ok = bool(
                user32.RegisterHotKey(self.hwnd, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_V)
            )
            if not self.hotkey_ok:
                log(f"RegisterHotKey failed ({ctypes.get_last_error()})")
        if os.environ.get("CLIPHISTORY_NO_TRAY") != "1":
            quiet = os.environ.get("CLIPHISTORY_QUIET") == "1"
            data = _fill_notify_icon(self.hwnd, self._icon, balloon=not quiet)
            self.tray_ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)))
            if not self.tray_ok:
                log(f"Shell_NotifyIcon failed ({ctypes.get_last_error()})")
        status, text = read_clipboard_text()
        if status == "ok" and text and not self.suppress.matches(text):
            self.events.put(("clipboard", text))
        elif status == "busy":
            self.events.put(("clipboard_retry", 0))

    def _message_loop(self) -> None:
        message = wintypes.MSG()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))

    def _wndproc_impl(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        try:
            if msg == WM_HOTKEY and int(wparam) == HOTKEY_ID:
                foreground = int(user32.GetForegroundWindow() or 0)
                self.events.put(("hotkey", root_window(foreground)))
                return 0
            if msg == WM_CLIPBOARDUPDATE:
                self._on_clipboard()
                return 0
            if msg == WM_TRAY:
                self._on_tray(int(lparam), int(hwnd))
                return 0
            if msg == WM_CLOSE:
                self._remove_tray()
                user32.UnregisterHotKey(hwnd, HOTKEY_ID)
                user32.RemoveClipboardFormatListener(hwnd)
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log_exception("wndproc failed")
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

    def _on_clipboard(self) -> None:
        status, text = read_clipboard_text()
        if status == "busy":
            self.events.put(("clipboard_retry", 0))
            return
        if status != "ok" or text is None:
            return
        if self.suppress.matches(text):
            return
        self.events.put(("clipboard", text))

    def _on_tray(self, mouse_message: int, hwnd: int) -> None:
        if mouse_message == WM_LBUTTONUP:
            now = time.monotonic()
            if now - self._last_tray_click < 0.35:
                return
            self._last_tray_click = now
            self.events.put(("toggle", None))
            return
        if mouse_message != WM_RBUTTONUP:
            return
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            user32.AppendMenuW(menu, MF_STRING, CMD_OPEN, "打开")
            user32.AppendMenuW(menu, MF_STRING, CMD_CLEAR, "清空历史")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, CMD_EXIT, "退出")
            user32.SetForegroundWindow(hwnd)
            point = POINT()
            user32.GetCursorPos(ctypes.byref(point))
            command = int(
                user32.TrackPopupMenu(
                    menu,
                    TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD,
                    int(point.x),
                    int(point.y),
                    0,
                    hwnd,
                    None,
                )
            )
            user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        if command == CMD_OPEN:
            self.events.put(("toggle", None))
        elif command == CMD_CLEAR:
            self.events.put(("clear", None))
        elif command == CMD_EXIT:
            self.events.put(("quit", None))

    def _remove_tray(self) -> None:
        hwnd = self.hwnd
        if not hwnd or not self.tray_ok:
            self._destroy_owned_icon()
            return
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = hwnd
        data.uID = 1
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
        self.tray_ok = False
        self._destroy_owned_icon()

    def _destroy_owned_icon(self) -> None:
        if self._icon and self._destroy_icon:
            user32.DestroyIcon(self._icon)
        self._icon = 0
        self._destroy_icon = False


def hide_native_border(hwnd: int) -> None:
    """Remove the light Windows border left around a borderless Tk window."""
    if not hwnd:
        return
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
        color = ctypes.c_uint(0xFFFFFFFE)  # DWMWA_COLOR_NONE
        dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        return


def write_ready_marker() -> None:
    path = data_dir() / "ready"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ok", encoding="ascii")


def input_struct_size() -> int:
    return ctypes.sizeof(INPUT)
