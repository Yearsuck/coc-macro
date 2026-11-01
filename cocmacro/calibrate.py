"""Interactive calibration: the user performs one attack by hand while we record
button positions (+ template crops) and the rectangles where numbers are read."""
import threading
from typing import Callable
from pathlib import Path

import numpy as np
from pynput import mouse

from cocmacro import frames, geometry, templates, winctl
from cocmacro import config
from cocmacro.config import Config

BUTTONS = ["battle", "find", "attack", "next", "surrender", "ok", "back"]
REGIONS = ["gold", "elixir", "damage", "timer"]

# (name, kind, instruction shown to the user), in the order of one real attack
STEPS: list[tuple[str, str, str]] = [
    ("battle", "button", "Haz clic en Batalla"),
    ("find", "button", "Haz clic en Buscar batalla"),
    ("attack", "button", "Haz clic en Atacar"),
    ("gold", "region", "Arrastra un rectangulo SOLO sobre las cifras del ORO (guiate por el recuadro punteado)"),
    ("elixir", "region", "Arrastra un rectangulo SOLO sobre las cifras del ELIXIR (recuadro punteado)"),
    ("next", "button", "Haz clic en Siguiente"),
    ("damage", "region", "Despliega una tropa y arrastra un rectangulo sobre el % de dano (recuadro punteado)"),
    ("timer", "region", "Arrastra un rectangulo sobre el reloj de la batalla, ej. 2m 51s (recuadro punteado)"),
    ("surrender", "button", "Haz clic en Rendirse"),
    ("ok", "button", "Haz clic en Vale"),
    ("back", "button", "Haz clic en Volver"),
]


class RectTracker:
    """Turns press / move / release into a normalised rectangle, reported live."""

    def __init__(self, on_change: Callable[[tuple[float, float, float, float]], None]):
        self._on_change, self._start = on_change, None

    @staticmethod
    def _rect(a, b):
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))

    def down(self, pos):
        self._start = pos
        self._on_change(self._rect(pos, pos))

    def move(self, pos):
        if self._start is not None:
            self._on_change(self._rect(self._start, pos))

    def up(self, pos):
        if self._start is None:
            return None
        rect = self._rect(self._start, pos)
        self._start = None
        self._on_change(rect)
        return rect


def _wait_press_release(win: winctl.GameWindow, need_release: bool, timeout: float,
                        on_move: Callable[[tuple[float, float]], None] | None = None,
                        on_down: Callable[[tuple[float, float]], None] | None = None):
    done, state = threading.Event(), {}

    def on_click(x, y, button, pressed):
        if button != mouse.Button.left:
            return
        pos = winctl.screen_to_rel(win, int(x), int(y))
        if pressed and pos is not None and "down" not in state:
            state["down"], state["frame"] = pos, frames.grab(win)  # before the game reacts
            if on_down:
                on_down(pos)
            if not need_release:
                done.set()
        elif not pressed and "down" in state:
            state["up"] = pos or state["down"]
            done.set()

    def on_motion(x, y):
        if on_move and "down" in state and not done.is_set():
            pos = winctl.screen_to_rel(win, int(x), int(y))
            if pos is not None:
                on_move(pos)

    listener = mouse.Listener(on_click=on_click, on_move=on_motion)
    listener.start()
    try:
        if not done.wait(timeout):
            raise TimeoutError("No se detecto ningun clic en la ventana del juego")
    finally:
        listener.stop()
    return state


def capture_click(win: winctl.GameWindow, timeout: float = 120) -> tuple[tuple[float, float], np.ndarray]:
    s = _wait_press_release(win, need_release=False, timeout=timeout)
    return s["down"], s["frame"]


def suggested_region(name: str):
    """Where the zone normally is (measured on real captures); drawn as a guide while calibrating."""
    return config.DEFAULT_REGIONS.get(name)


def validate_rect(rect: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not config.region_ok(rect):
        raise ValueError("No se detecto un arrastre: arrastra un rectangulo sobre la zona (un clic no vale)")
    return rect


def capture_rect(win: winctl.GameWindow, timeout: float = 120,
                 on_rect: Callable[[tuple[float, float, float, float]], None] | None = None,
                 on_invalid: Callable[[str], None] | None = None
                 ) -> tuple[tuple[float, float, float, float], np.ndarray]:
    """Waits for a drag; a plain click is reported through on_invalid and the wait restarts."""
    while True:
        tracker = RectTracker(on_rect or (lambda r: None))
        s = _wait_press_release(win, need_release=True, timeout=timeout,
                                on_down=tracker.down, on_move=tracker.move)
        rect = tracker.up(s["up"])
        try:
            return validate_rect(rect), s["frame"]
        except ValueError as e:
            if on_invalid is None:
                raise
            on_invalid(str(e))


def run_step(win: winctl.GameWindow, cfg: Config, name: str, kind: str, tpl_dir: Path,
             on_rect=None, on_click=None, on_invalid=None) -> Config:
    cfg.aspect = geometry.aspect((win.client_w, win.client_h))
    if kind == "button":
        pos, frame = capture_click(win)
        cfg.buttons[name] = pos
        templates.save_template(name, frame, pos, cfg.tpl_size, tpl_dir)
        if on_click:
            on_click(pos)
    else:
        rect, _ = capture_rect(win, on_rect=on_rect, on_invalid=on_invalid)
        cfg.regions[name] = rect
    return cfg
