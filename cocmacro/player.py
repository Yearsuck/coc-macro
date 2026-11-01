"""Replay a Recording into the game window via PostMessage."""
import threading
import time

from cocmacro import winctl
from cocmacro.recorder import Recording

_CHUNK = 0.1


def play(win, rec: Recording, stop: threading.Event, sleep=time.sleep,
         post=winctl.post_mouse) -> bool:
    """Returns False if stopped early. Never leaves the button pressed."""
    down, last = False, (0.0, 0.0)
    for ev in rec.events:
        remaining = ev.dt
        while remaining > 1e-9:
            if stop.is_set():
                break
            step = min(_CHUNK, remaining)
            sleep(step)
            remaining -= step
        if stop.is_set():
            if down:
                post(win, "up", last[0], last[1])
            return False
        post(win, ev.kind, ev.x, ev.y)
        if ev.kind == "down":
            down = True
        elif ev.kind == "up":
            down = False
        last = (ev.x, ev.y)
    if down:
        post(win, "up", last[0], last[1])
    return True
