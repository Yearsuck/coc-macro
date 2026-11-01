"""Click-through overlay drawn over the game window while calibrating.

A borderless, always-on-top Tk window with a transparent background covers the game's client
area. It shows the current step, the rectangle being dragged, where you clicked and the zones
already saved. Mouse clicks pass through it to the game (WS_EX_TRANSPARENT), so you keep playing.
"""
import ctypes
import tkinter as tk
from typing import Callable

from cocmacro import geometry, winctl

TRANSPARENT = "#010101"
GOLD, GREEN, INK, PAPER = "#f2c14e", "#3fb950", "#14181f", "#ffffff"

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x20, 0x80000, 0x80, 0x08000000


def banner_box(size: tuple[int, int], banner_h: int, banner_w: int,
               avoid: tuple[float, float, float, float] | None,
               order: tuple[str, ...] = ("top", "middle", "bottom"), margin: int = 24
               ) -> tuple[int, int, int, int]:
    """Pixel box (x0, y0, x1, y1) for the banner: the first slot, in `order`, that stays clear of
    `avoid` (a pixel rect). Falls back to the first slot when nothing is clear."""
    w, h = size
    x0 = max(0, (w - banner_w) // 2)
    x1 = min(w, x0 + banner_w)
    ys = {"top": 14, "middle": max(14, int(h * 0.38) - banner_h // 2), "bottom": max(14, h - banner_h - 14)}
    boxes = [(x0, ys[slot], x1, ys[slot] + banner_h) for slot in order]
    for box in boxes:
        if avoid is None or (box[2] <= avoid[0] - margin or avoid[2] + margin <= box[0]
                             or box[3] <= avoid[1] - margin or avoid[3] + margin <= box[1]):
            return box
    return boxes[0]


class Overlay:
    def __init__(self, root: tk.Tk, find_window: Callable[[], winctl.GameWindow] = winctl.find_game_window):
        self.root, self.find_window = root, find_window
        self.top: tk.Toplevel | None = None
        self.canvas: tk.Canvas | None = None
        self.size = (1, 1)

    # -- window --------------------------------------------------------
    def _ensure(self) -> None:
        win = self.find_window()
        x, y, w, h = winctl.client_screen_rect(win)
        self.size = (w, h)
        if self.top is None:
            top = tk.Toplevel(self.root)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
            top.attributes("-transparentcolor", TRANSPARENT)
            top.configure(bg=TRANSPARENT)
            self.canvas = tk.Canvas(top, bg=TRANSPARENT, highlightthickness=0)
            self.canvas.pack(fill="both", expand=True)
            self.top = top
            top.geometry(f"{w}x{h}+{x}+{y}")
            top.update_idletasks()
            self._click_through(top)
        else:
            self.top.geometry(f"{w}x{h}+{x}+{y}")
            self.top.deiconify()
        self.top.lift()

    @staticmethod
    def _click_through(top: tk.Toplevel) -> None:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(top.winfo_id()) or top.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)

    def hide(self) -> None:
        if self.top is not None:
            self.top.withdraw()

    def clear(self, tag: str | None = None) -> None:
        if self.canvas is not None:
            self.canvas.delete(tag or "all")

    # -- drawing -------------------------------------------------------
    def banner(self, text: str, avoid: tuple[float, float, float, float] | None = None,
               order: tuple[str, ...] = ("top", "middle", "bottom")) -> None:
        """Step text placed where it does not cover `avoid` (relative rect of the zone to mark)."""
        self._ensure()
        c, (w, h) = self.canvas, self.size
        c.delete("banner")
        t = c.create_text(0, 0, text=text, fill=PAPER, width=min(w - 120, 520), justify="center",
                          font=("Segoe UI", 13, "bold"), tags="banner")
        bx = c.bbox(t)
        bw, bh = bx[2] - bx[0] + 32, bx[3] - bx[1] + 20
        avoid_px = geometry.rect_to_px(avoid, self.size) if avoid else None
        x0, y0, x1, y1 = banner_box(self.size, bh, bw, avoid_px, order)
        r = c.create_rectangle(x0, y0, x1, y1, fill=INK, outline=GOLD, width=2, tags="banner")
        c.coords(t, (x0 + x1) // 2, (y0 + y1) // 2)
        c.tag_lower(r, t)

    def guide(self, rect: tuple[float, float, float, float] | None, text: str = "Zona sugerida") -> None:
        """Dashed box showing where the zone usually is."""
        self._ensure()
        c = self.canvas
        c.delete("guide")
        if rect is None:
            return
        x0, y0, x1, y1 = geometry.rect_to_px(rect, self.size)
        c.create_rectangle(x0 - 4, y0 - 4, x1 + 4, y1 + 4, outline=GOLD, width=2, dash=(6, 4), tags="guide")
        t = c.create_text(x0, y1 + 14, text=text, fill=PAPER, anchor="w", font=("Segoe UI", 9, "bold"), tags="guide")
        bb = c.bbox(t)
        bg = c.create_rectangle(bb[0] - 3, bb[1] - 1, bb[2] + 3, bb[3] + 1, fill=INK, outline=GOLD, tags="guide")
        c.tag_lower(bg, t)

    def rect(self, rect: tuple[float, float, float, float], color: str = GOLD, label: str | None = None,
             tag: str = "live") -> None:
        self._ensure()
        c = self.canvas
        c.delete(tag)
        x0, y0, x1, y1 = geometry.rect_to_px(rect, self.size)
        c.create_rectangle(x0, y0, x1, y1, outline=color, width=3, tags=tag)
        if label:
            t = c.create_text(x0 + 4, max(12, y0 - 12), text=label, fill=PAPER, anchor="w",
                              font=("Segoe UI", 10, "bold"), tags=tag)
            bx = c.bbox(t)
            bg = c.create_rectangle(bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1, fill=INK, outline=color, tags=tag)
            c.tag_lower(bg, t)

    def marker(self, pos: tuple[float, float], label: str) -> None:
        self._ensure()
        c = self.canvas
        x, y = geometry.to_px(pos, self.size)
        c.create_oval(x - 18, y - 18, x + 18, y + 18, outline=GREEN, width=3, tags="saved")
        t = c.create_text(x + 24, y, text=label, fill=PAPER, anchor="w", font=("Segoe UI", 10, "bold"), tags="saved")
        bx = c.bbox(t)
        bg = c.create_rectangle(bx[0] - 3, bx[1] - 1, bx[2] + 3, bx[3] + 1, fill=INK, outline=GREEN, tags="saved")
        c.tag_lower(bg, t)

    def saved_rect(self, name: str, rect: tuple[float, float, float, float]) -> None:
        self.clear("live")
        self.rect(rect, color=GREEN, label=name, tag=f"saved_{name}")
