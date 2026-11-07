"""Win32 control of the Google Play Games window running Clash of Clans.

Capture: PrintWindow(flag 2), works with the window behind others.
Input: PostMessage mouse events with client coordinates; the target is first marked as the active
instance with WM_ACTIVATE (activate_instance), because the host only forwards input to the active one.
A minimized window has a 0x0 client area and cannot be captured, so it is restored without
activating it and sent to the bottom of the z-order (restore_if_minimized).
"""
import contextlib
import ctypes
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Literal

import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
user32.SetProcessDPIAware()

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEWHEEL = 0x0200, 0x0201, 0x0202, 0x020A
MK_LBUTTON = 1
SW_SHOWNOACTIVATE = 4
HWND_BOTTOM = 1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
TITLE_PREFIX = "Clash of Clans"
PROCESS_NAME = "crosvm"


class WindowNotFound(Exception):
    pass


class AmbiguousWindow(WindowNotFound):
    pass


class WindowMinimized(Exception):
    pass


@dataclass(frozen=True)
class GameWindow:
    hwnd: int
    client_w: int
    client_h: int


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
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


def _enum_game_windows() -> list[WindowInfo]:
    found: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _title(hwnd).startswith(TITLE_PREFIX) \
                and _process_name(hwnd).startswith(PROCESS_NAME):
            w, h = _client_size(hwnd)
            found.append(WindowInfo(hwnd, _title(hwnd), w, h))
        return True

    user32.EnumWindows(cb, 0)
    return found


def list_game_windows() -> list[WindowInfo]:
    return _enum_game_windows()


def pick_window(windows: list[WindowInfo], title: str = "") -> WindowInfo:
    """Select a game window by title, or the single open window when title is blank."""
    clean = title.strip()
    if not clean:
        if len(windows) == 1:
            return windows[0]
        if not windows:
            raise WindowNotFound("Ventana de Clash of Clans no encontrada")
        raise AmbiguousWindow("Hay varias ventanas de Clash of Clans: elige una")

    # Exact match beats a partial/prefix substring match
    exact = [w for w in windows if w.title == title or w.title == clean]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousWindow(f"Hay varias ventanas de Clash of Clans con el titulo '{title}'")

    needle = clean.lower()
    matches = [w for w in windows if needle in w.title.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise AmbiguousWindow(f"Hay varias ventanas de Clash of Clans que coinciden con '{title}'")
    raise WindowNotFound(f"Ventana de Clash of Clans no encontrada: '{title}'")


def find_game_window(title: str = "") -> GameWindow:
    w = pick_window(list_game_windows(), title)
    return GameWindow(w.hwnd, w.client_w, w.client_h)


def is_foreground(win: GameWindow) -> bool:
    return user32.GetForegroundWindow() == win.hwnd


# All Play Games windows of the account are displays of ONE crosvm virtual machine and share one input channel.
# Two things measured live on 2026-11-07 (two windows side by side, no overlap):
#  1. a drag posted to a window while another window is also being driven gets mixed up with it, so every posted
#     input goes through this lock; a deployment holds it for its whole replay and the accounts take turns.
#     Re-entrant: a routine that holds it can still click.
#  2. the host forwards posted mouse input only to the ACTIVE instance, whatever window it was posted to (a tap
#     posted to the inactive window was received by the active one). The active instance follows WM_ACTIVATE,
#     so before each burst the target is marked active (and the others inactive) with WM_ACTIVATE messages,
#     which does not touch the user's real keyboard focus.
_input_lock = threading.RLock()

_GAMES_TTL = 3.0
_games_cache: tuple[float, list[int]] = (0.0, [])

GAME_WINDOW_CLASS = "CROSVM_1"


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _game_hwnds() -> list[int]:
    """Visible Play Games game windows (class CROSVM_1), whatever the game. Identified by CLASS, not by title:
    GetWindowText on a window owned by a thread that does not pump messages (the app's own Tk window while a
    test or a busy thread is blocked) blocks the caller. Cached for a few seconds."""
    global _games_cache
    now = time.monotonic()
    if now - _games_cache[0] > _GAMES_TTL:
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and _class_name(hwnd) == GAME_WINDOW_CLASS:
                found.append(hwnd)
            return True

        user32.EnumWindows(cb, 0)
        _games_cache = (now, found)
    return _games_cache[1]


@contextlib.contextmanager
def exclusive_input(stop: threading.Event | None = None, poll: float = 0.2):
    """Hold the input channel. Yields True once it is held, or False if `stop` was set while waiting (the
    caller must then do nothing)."""
    got = False
    while not got:
        got = _input_lock.acquire(timeout=poll)
        if not got and stop is not None and stop.is_set():
            break
    try:
        yield got
    finally:
        if got:
            _input_lock.release()


WM_ACTIVATE, WA_INACTIVE, WA_ACTIVE = 0x0006, 0, 1
SMTO_ABORTIFHUNG = 0x0002
ACTIVATE_SETTLE_S = 0.1
ACTIVATE_REPEAT_S = 1.0        # the same instance asked again within this time needs no new pause
_last_active_hwnd = 0
_last_active_at = 0.0
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                       wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM


def _send_activate(hwnd: int, state: int, other: int) -> None:
    res = ctypes.c_size_t()
    user32.SendMessageTimeoutW(hwnd, WM_ACTIVATE, state, other, SMTO_ABORTIFHUNG, 500, ctypes.byref(res))


def activate_instance(win: GameWindow) -> bool:
    """Mark `win` as the active Play Games instance (and every other game window as inactive) so that the
    input posted next reaches it. True if messages were sent; False when `win` is not a game window or is the
    only one (nothing to arbitrate). Call it inside the input lock."""
    global _games_cache, _last_active_hwnd, _last_active_at
    hwnd = getattr(win, "hwnd", None)
    if hwnd is None:
        return False
    games = _game_hwnds()
    if hwnd not in games:                  # a window opened or re-created within the cache time: look again once
        _games_cache = (0.0, [])
        games = _game_hwnds()
        if hwnd not in games:
            return False
    others = [h for h in games if h != hwnd]
    if not others:
        return False
    _send_activate(hwnd, WA_ACTIVE, 0)
    for h in others:
        _send_activate(h, WA_INACTIVE, hwnd)
    now = time.monotonic()
    if _last_active_hwnd != hwnd or now - _last_active_at > ACTIVATE_REPEAT_S:
        time.sleep(ACTIVATE_SETTLE_S)      # the host needs a moment to switch (the user may have clicked a window)
    _last_active_hwnd, _last_active_at = hwnd, time.monotonic()
    return True


def restore_if_minimized(win: GameWindow, api=None, sleep=time.sleep) -> bool:
    """Bring a minimized window back without stealing focus. True if it had to be restored."""
    api = api or user32
    if not api.IsIconic(win.hwnd):
        return False
    api.ShowWindow(win.hwnd, SW_SHOWNOACTIVATE)
    api.SetWindowPos(win.hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    for _ in range(10):
        sleep(0.2)
        if not api.IsIconic(win.hwnd):
            return True
    raise WindowMinimized("La ventana esta minimizada y no se pudo restaurar")


def capture(win: GameWindow) -> np.ndarray:
    """BGR image of the client area (no title bar), shape (client_h, client_w, 3)."""
    if not user32.IsWindow(win.hwnd):
        raise WindowNotFound("La ventana del juego se cerro")
    restore_if_minimized(win)
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


def post_wheel(win: GameWindow, x: float, y: float, delta: int) -> None:
    """Send a wheel turn at relative (0-1) client coords. WM_MOUSEWHEEL carries SCREEN coordinates."""
    if not user32.IsWindow(win.hwnd):
        raise WindowNotFound("La ventana del juego se cerro")
    ox, oy, cw, ch = client_screen_rect(win)
    sx, sy = ox + round(x * cw), oy + round(y * ch)
    wparam = ((delta & 0xFFFF) << 16)
    lparam = ((sy & 0xFFFF) << 16) | (sx & 0xFFFF)
    with _input_lock:
        activate_instance(win)
        user32.PostMessageW(win.hwnd, WM_MOUSEWHEEL, wparam, lparam)


def click(win: GameWindow, x: float, y: float, hold_s: float = 0.08) -> None:
    with _input_lock:                  # the press and the release of a tap must not be split by another window
        activate_instance(win)
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
