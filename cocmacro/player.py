"""Replay a Recording into the game window via PostMessage."""
import contextlib
import threading
import time

from cocmacro import winctl
from cocmacro.recorder import Recording

_CHUNK = 0.1


def play(win, rec: Recording, stop: threading.Event, sleep=time.sleep,
         post=winctl.post_mouse, post_wheel=winctl.post_wheel) -> bool:
    """Returns False if stopped early. Never leaves the button pressed.

    The shared input channel is held one GESTURE at a time (a press with its moves and release, or one wheel
    turn), not for the whole replay: a deployment is ~70 gestures of under 0.1 s with ~0.14 s between them, so the
    other account's taps (Siguiente while scouting, which only lasts 30 s) get in between instead of waiting out
    the whole 22 s, and the two accounts' gestures still never mix. The waiting between gestures happens
    without the channel, and each gesture marks this window as the active instance first (the host forwards
    input to the active instance only)."""
    down, last = False, None
    holding = False
    held = contextlib.ExitStack()
    try:
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
            if not holding:                                     # a new gesture starts: take the channel
                if not held.enter_context(winctl.exclusive_input(stop)):
                    return False                                # stopped while waiting for the other account
                holding = True
                winctl.activate_instance(win)
            if ev.kind == "wheel":
                post_wheel(win, ev.x, ev.y, ev.delta)
                if not down:                                    # a wheel turn inside a drag stays in that gesture
                    held.close()
                    holding = False
                continue
            if ev.kind == "down" and (last is None or (ev.x, ev.y) == last) and post is winctl.post_mouse:
                winctl.hover_to(win, ev.x, ev.y)                # the first press, or the same spot twice, is dropped
            post(win, ev.kind, ev.x, ev.y)
            if ev.kind == "down":
                down = True
            elif ev.kind == "up":
                down = False
            last = (ev.x, ev.y)
            if not down:                                        # release (or a lone move): the gesture is over
                held.close()
                holding = False
        if down:
            post(win, "up", last[0], last[1])
        return True
    finally:
        held.close()
