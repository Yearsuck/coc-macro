"""Record mouse deployments inside the game window and store them as JSON."""
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Literal

from pynput import mouse

from cocmacro import geometry, winctl


WHEEL_DELTA = 120  # Win32 units per wheel notch


@dataclass
class Event:
    dt: float  # seconds since the previous event
    kind: Literal["down", "up", "move", "wheel"]
    x: float  # relative 0-1
    y: float
    delta: int = 0  # wheel only: notches * 120, positive = away from the user


@dataclass
class Recording:
    name: str
    aspect: float | None
    events: list[Event]


def save_recording(rec: Recording, dir: Path) -> Path:
    dir = Path(dir)
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / f"{rec.name}.json"
    path.write_text(json.dumps(asdict(rec), indent=1), encoding="utf-8")
    return path


def load_recording(name: str, dir: Path) -> Recording:
    raw = json.loads((Path(dir) / f"{name}.json").read_text(encoding="utf-8"))
    return Recording(raw["name"], raw["aspect"], [Event(**e) for e in raw["events"]])


def list_recordings(dir: Path) -> list[str]:
    dir = Path(dir)
    return sorted(p.stem for p in dir.glob("*.json")) if dir.exists() else []


class Recorder:
    """to_rel(screen_x, screen_y) -> (x, y) relative, or None when outside the window."""

    def __init__(self, to_rel: Callable[[int, int], tuple[float, float] | None], name: str,
                 now: Callable[[], float] = time.monotonic, aspect: float | None = None):
        self._to_rel, self._name, self._now, self._aspect = to_rel, name, now, aspect
        self._events: list[Event] = []
        self._last_t: float | None = None
        self._last_pos = (0.0, 0.0)
        self._down = False
        self._listener: mouse.Listener | None = None

    @classmethod
    def for_window(cls, win: winctl.GameWindow, name: str) -> "Recorder":
        return cls(lambda sx, sy: winctl.screen_to_rel(win, sx, sy), name,
                   aspect=geometry.aspect((win.client_w, win.client_h)))

    def feed(self, kind: str, sx: int, sy: int, pressed: bool, delta: int = 0) -> None:
        pos = self._to_rel(sx, sy)
        if kind == "wheel":
            if pos is None or delta == 0:
                return
        elif kind == "down":
            if pos is None:
                return
            self._down = True
        elif kind == "move":
            if not self._down or pos is None:
                return
        elif kind == "up":
            if not self._down:
                return
            self._down = False
            pos = pos or self._last_pos
        t = self._now()
        dt = 0.0 if self._last_t is None else t - self._last_t
        self._last_t, self._last_pos = t, pos
        self._events.append(Event(dt, kind, pos[0], pos[1], delta))

    def start(self) -> None:
        def on_click(x, y, button, pressed):
            if button == mouse.Button.left:
                self.feed("down" if pressed else "up", int(x), int(y), pressed)

        def on_move(x, y):
            self.feed("move", int(x), int(y), self._down)

        def on_scroll(x, y, dx, dy):
            self.feed("wheel", int(x), int(y), self._down, delta=round(dy * WHEEL_DELTA))

        self._listener = mouse.Listener(on_click=on_click, on_move=on_move, on_scroll=on_scroll)
        self._listener.start()

    def result(self) -> Recording:
        return Recording(self._name, self._aspect, list(self._events))

    def stop(self) -> Recording:
        if self._listener:
            self._listener.stop()
        return self.result()
