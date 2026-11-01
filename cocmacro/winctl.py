"""Win32 control of the Google Play Games window running Clash of Clans.

Capture: PrintWindow(flag 2), works with the window behind others.
Input: PostMessage mouse events with client coordinates, works without focus.
A minimized window cannot be captured (raises WindowMinimized); verify by hand.
"""
import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Literal

import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
MK_LBUTTON = 1
TITLE_PREFIX = "Clash of Clans"
PROCESS_NAME = "crosvm"


class WindowNotFound(Exception):
    pass


class WindowMinimized(Exception):
    pass


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    client_w: int
    client_h: int


def _title(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _process_name(hwnd) -> str:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        n = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return buf.value.rsplit("\\", 1)[-1].lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


def _client_size(hwnd) -> tuple[int, int]:
    r = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(r))
    return r.right, r.bottom


def find_game_window() -> GameWindow:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _title(hwnd).startswith(TITLE_PREFIX) \
                and _process_name(hwnd).startswith(PROCESS_NAME):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        raise WindowNotFound("Ventana de Clash of Clans no encontrada")
    w, h = _client_size(found[0])
    return GameWindow(found[0], w, h)


def is_foreground(win: GameWindow) -> bool:
    return user32.GetForegroundWindow() == win.hwnd


def capture(win: GameWindow) -> np.ndarray:
    """BGR image of the client area (no title bar), shape (client_h, client_w, 3)."""
    if not user32.IsWindow(win.hwnd):
        raise WindowNotFound("La ventana del juego se cerro")
    if user32.IsIconic(win.hwnd):
        raise WindowMinimized("La ventana esta minimizada; no se puede capturar")
    wr = wintypes.RECT()
    user32.GetWindowRect(win.hwnd, ctypes.byref(wr))
    ww, wh = wr.right - wr.left, wr.bottom - wr.top
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(win.hwnd, ctypes.byref(pt))
    ox, oy = pt.x - wr.left, pt.y - wr.top
    cw, ch = _client_size(win.hwnd)

    hdc = user32.GetWindowDC(win.hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, ww, wh)
    old = gdi32.SelectObject(mem, bmp)
    try:
        user32.PrintWindow(win.hwnd, mem, 2)

        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        bih = BIH(ctypes.sizeof(BIH), ww, -wh, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(ww * wh * 4)
        gdi32.GetDIBits(mem, bmp, 0, wh, buf, ctypes.byref(bih), 0)
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(win.hwnd, hdc)
    img = np.frombuffer(buf, dtype=np.uint8).reshape(wh, ww, 4)
    return np.ascontiguousarray(img[oy:oy + ch, ox:ox + cw, :3])


def post_mouse(win: GameWindow, kind: Literal["down", "up", "move"], x: float, y: float) -> None:
    """Send a mouse event with relative (0-1) client coordinates."""
    if not user32.IsWindow(win.hwnd):
        raise WindowNotFound("La ventana del juego se cerro")
    cw, ch = _client_size(win.hwnd)
    px, py = round(x * cw), round(y * ch)
    lparam = ((py & 0xFFFF) << 16) | (px & 0xFFFF)
    msg, wparam = {"down": (WM_LBUTTONDOWN, MK_LBUTTON),
                   "up": (WM_LBUTTONUP, 0),
                   "move": (WM_MOUSEMOVE, MK_LBUTTON)}[kind]
    user32.PostMessageW(win.hwnd, msg, wparam, lparam)


def click(win: GameWindow, x: float, y: float, hold_s: float = 0.08) -> None:
    post_mouse(win, "down", x, y)
    time.sleep(hold_s)
    post_mouse(win, "up", x, y)


def screen_to_rel(win: GameWindow, sx: int, sy: int) -> tuple[float, float] | None:
    """Screen pixel -> relative client coords, None if outside the client area."""
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(win.hwnd, ctypes.byref(pt))
    cw, ch = _client_size(win.hwnd)
    x, y = sx - pt.x, sy - pt.y
    if 0 <= x < cw and 0 <= y < ch:
        return x / cw, y / ch
    return None


def client_screen_rect(win: GameWindow) -> tuple[int, int, int, int]:
    """(x, y, width, height) of the client area in screen pixels."""
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(win.hwnd, ctypes.byref(pt))
    cw, ch = _client_size(win.hwnd)
    return pt.x, pt.y, cw, ch
