"""Interactive calibration: the user performs one attack by hand while we record
button positions (+ template crops) and the rectangles where numbers are read."""
import threading
from pathlib import Path

import numpy as np
from pynput import mouse

from cocmacro import geometry, templates, winctl
from cocmacro.config import Config

BUTTONS = ["battle", "find", "attack", "next", "surrender", "ok", "back"]
REGIONS = ["gold", "elixir", "damage", "timer"]

# (name, kind, instruction shown to the user), in the order of one real attack
STEPS: list[tuple[str, str, str]] = [
    ("battle", "button", "Haz clic en Batalla"),
    ("find", "button", "Haz clic en Buscar batalla"),
    ("attack", "button", "Haz clic en Atacar"),
    ("gold", "region", "En la aldea enemiga, arrastra un rectangulo sobre el numero de ORO"),
    ("elixir", "region", "Arrastra un rectangulo sobre el numero de ELIXIR"),
    ("next", "button", "Haz clic en Siguiente"),
    ("damage", "region", "Despliega una tropa y arrastra un rectangulo sobre el % de dano"),
    ("timer", "region", "Arrastra un rectangulo sobre el reloj de la batalla (ej. 2m 51s)"),
    ("surrender", "button", "Haz clic en Rendirse"),
    ("ok", "button", "Haz clic en Vale"),
    ("back", "button", "Haz clic en Volver"),
]


def _wait_press_release(win: winctl.GameWindow, need_release: bool, timeout: float):
    done, state = threading.Event(), {}

    def on_click(x, y, button, pressed):
        if button != mouse.Button.left:
            return
        pos = winctl.screen_to_rel(win, int(x), int(y))
        if pressed and pos is not None and "down" not in state:
            state["down"], state["frame"] = pos, winctl.capture(win)  # before the game reacts
            if not need_release:
                done.set()
        elif not pressed and "down" in state:
            state["up"] = pos or state["down"]
            done.set()

    listener = mouse.Listener(on_click=on_click)
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


def capture_rect(win: winctl.GameWindow, timeout: float = 120) -> tuple[tuple[float, float, float, float], np.ndarray]:
    s = _wait_press_release(win, need_release=True, timeout=timeout)
    (x0, y0), (x1, y1) = s["down"], s["up"]
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)), s["frame"]


def run_step(win: winctl.GameWindow, cfg: Config, name: str, kind: str, tpl_dir: Path) -> Config:
    cfg.aspect = geometry.aspect((win.client_w, win.client_h))
    if kind == "button":
        pos, frame = capture_click(win)
        cfg.buttons[name] = pos
        templates.save_template(name, frame, pos, cfg.tpl_size, tpl_dir)
    else:
        rect, _ = capture_rect(win)
        cfg.regions[name] = rect
    return cfg
