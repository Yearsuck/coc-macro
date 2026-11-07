"""Win32 control of the Google Play Games window running Clash of Clans.

Capture: PrintWindow(flag 2), works with the window behind others.
Input: PostMessage mouse events with client coordinates, works without focus.
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
HWND_BOTTOM, HWND_TOP = 1, 0
GW_HWNDNEXT, GW_HWNDPREV = 2, 3
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


VK_MENU, KEYEVENTF_KEYUP = 0x12, 0x0002
_focus_lock = threading.Lock()      # one window at a time takes the focus
# Every Play Games window of the account lives in ONE crosvm process, so they share one input channel: a drag
# posted to a window while another window is also being driven gets mixed up with it (live, two tabs: only one
# of the two accounts managed to deploy its troops at a time). All posted input goes through this lock; a
# deployment holds it for its whole replay, so the accounts take turns. Re-entrant: a routine that holds it
# can still click.
_input_lock = threading.RLock()


# Where a click lands is decided by what is VISIBLE at that screen pixel among the Clash windows, not by the window
# the message is posted to (measured live 2026-11-07: a tap posted to the window behind was received by the window
# in front, at the same screen position; a non-Clash app on top does not matter). So before sending input the
# target window must not be covered by another Clash window.
_GAMES_TTL = 3.0
RAISE_SETTLE_S = 0.05
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


def _zorder_top_first() -> list[int]:
    order, h = [], user32.GetTopWindow(None)
    while h:
        order.append(h)
        h = user32.GetWindow(h, GW_HWNDNEXT)
    return order


def _rect_of(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def _overlap(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def covering_window(order: list[int], rects: dict[int, tuple], hwnd: int) -> int | None:
    """`order`: Clash window handles, top of the z-order first. The highest Clash window that is above `hwnd`
    and overlaps it, or None when `hwnd` is not covered by another Clash window."""
    if hwnd not in order:
        return None
    for other in order[:order.index(hwnd)]:
        if other in rects and hwnd in rects and _overlap(rects[other], rects[hwnd]):
            return other
    return None


def raise_above_overlapping(win: GameWindow) -> bool:
    """Put `win` directly above the highest Clash window that covers it, without activating it and without
    passing over the user's other applications. True if it had to be raised."""
    global _games_cache
    hwnd = getattr(win, "hwnd", None)
    if hwnd is None:
        return False
    games = _game_hwnds()
    if hwnd not in games:                  # a window opened or re-created within the cache time: look again once
        _games_cache = (0.0, [])
        games = _game_hwnds()
        if hwnd not in games:
            return False
    order = [h for h in _zorder_top_first() if h in games]
    rects = {h: _rect_of(h) for h in order}
    top = covering_window(order, rects, hwnd)
    if top is None:
        return False
    above_top = user32.GetWindow(top, GW_HWNDPREV)
    user32.SetWindowPos(hwnd, above_top or HWND_TOP, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
    time.sleep(RAISE_SETTLE_S)             # let the new order be applied before the game hit-tests the click
    return True


def overlapping_titles(win: GameWindow) -> list[str]:
    """Titles of the other Clash windows whose area overlaps `win` (for a warning)."""
    games = _game_hwnds()
    if getattr(win, "hwnd", None) not in games:
        return []
    mine = _rect_of(win.hwnd)
    return [_title(h) for h in games if h != win.hwnd and _overlap(_rect_of(h), mine)]


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


def _foreground(api, hwnd) -> None:
    # a synthetic Alt press lets SetForegroundWindow through when another app owns the focus
    api.keybd_event(VK_MENU, 0, 0, 0)
    api.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    api.SetForegroundWindow(hwnd)


@contextlib.contextmanager
def focused(win: GameWindow, api=None, sleep=time.sleep, settle: float = 0.4):
    """Give the window the focus for a moment and hand it back afterwards. Normal clicks work on a window in
    the background, but some Android dialogs of the game (the inactivity disconnect) ignore clicks while the
    window is not the active one. Measured live 2026-11-07: the same posted click did nothing for minutes and
    closed the dialog in 2 s once the window was active."""
    api = api or user32
    with _focus_lock:
        prev = api.GetForegroundWindow()
        taken = prev != win.hwnd
        try:
            if taken:
                _foreground(api, win.hwnd)
                sleep(settle)
            yield
        finally:
            if taken and prev and api.IsWindow(prev):
                _foreground(api, prev)


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
        raise_above_overlapping(win)
        user32.PostMessageW(win.hwnd, WM_MOUSEWHEEL, wparam, lparam)


def click(win: GameWindow, x: float, y: float, hold_s: float = 0.08) -> None:
    with _input_lock:                  # the press and the release of a tap must not be split by another window
        raise_above_overlapping(win)
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
