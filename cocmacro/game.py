"""Real Game backend: window capture + templates + OCR + replay, behind bot.Game."""
import threading
import time
from pathlib import Path

import cv2

from cocmacro import frames, ocr, player, templates, winctl
from cocmacro.config import Config
from cocmacro.recorder import Recording

# Template(s) whose presence identifies each screen.
SCREEN_TEMPLATES = {"home": ["battle"], "scout": ["next"], "confirm": ["ok"], "results": ["back"]}
DEBUG_KEEP = 60     # newest debug images kept


class RealGame:
    def __init__(self, win: winctl.GameWindow, cfg: Config, recording: Recording,
                 stop: threading.Event, tpl_dir: Path, debug_dir: Path | None = None):
        self.win, self.cfg, self.recording, self.stop, self.tpl_dir = win, cfg, recording, stop, Path(tpl_dir)
        self.debug_dir = Path(debug_dir) if debug_dir else None

    def _has(self, frame, name: str) -> bool:
        return templates.match(frame, name, self.tpl_dir)

    def screen_is(self, name: str) -> bool:
        frame = frames.grab(self.win)
        if name == "battle":
            # Rendirse (<50%) or Terminar batalla (>=50%); both also show on the scout screen
            return (self._has(frame, "surrender") or self._has(frame, "end")) and not self._has(frame, "next")
        return any(self._has(frame, t) for t in SCREEN_TEMPLATES[name])

    def why_not(self, name: str) -> str:
        """Why the screen is not recognised: similarity of each template that identifies it."""
        frame = frames.grab(self.win)
        names = ["surrender", "end"] if name == "battle" else SCREEN_TEMPLATES[name]
        parts = []
        for t in names:
            found = templates.score(frame, t, self.tpl_dir)
            if found is None:
                parts.append(f"falta la imagen '{t}'")
            else:
                parts.append(f"{t} {found[0]:.2f} de {templates.THRESHOLD:.2f} (mejor sitio {found[1][0]:.2f},{found[1][1]:.2f})")
        return (f"{'; '.join(parts)}. Ventana {self.win.client_w}x{self.win.client_h}, "
                f"brillo medio {int(frame.mean())}")

    def click_button(self, name: str) -> None:
        x, y = self.cfg.buttons[name]
        winctl.click(self.win, x, y)

    def read_resources(self) -> tuple[int | None, int | None]:
        frame = frames.grab(self.win)
        return (ocr.read_number(frame, self.cfg.regions["gold"]),
                ocr.read_number(frame, self.cfg.regions["elixir"]))

    def read_damage(self) -> int | None:
        return ocr.read_number(frames.grab(self.win), self.cfg.regions["damage"])

    def read_time_left(self) -> int | None:
        return ocr.read_time_left(frames.grab(self.win), self.cfg.regions["timer"])

    def play_deployment(self) -> bool:
        return player.play(self.win, self.recording, self.stop)

    def dump_debug(self, reason: str) -> None:
        """Save the full frame and the number crops of what could not be read (kept locally)."""
        if self.debug_dir is None:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        stamp = f"{time.strftime('%H%M%S')}_{time.time_ns() % 10**9}"
        frame = frames.grab(self.win)
        cv2.imwrite(str(self.debug_dir / f"{stamp}_{reason}_frame.png"), frame)
        for k in ("gold", "elixir", "damage", "timer"):
            if k in self.cfg.regions:
                cv2.imwrite(str(self.debug_dir / f"{stamp}_{reason}_{k}.png"), ocr._crop(frame, self.cfg.regions[k]))
        for old in sorted(self.debug_dir.iterdir(), key=lambda p: p.stat().st_mtime)[:-DEBUG_KEEP]:
            old.unlink(missing_ok=True)
