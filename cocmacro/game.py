"""Real Game backend: window capture + templates + OCR + replay, behind bot.Game."""
import threading
from pathlib import Path

from cocmacro import geometry, ocr, player, templates, winctl
from cocmacro.config import Config
from cocmacro.recorder import Recording

# Template(s) whose presence identifies each screen.
SCREEN_TEMPLATES = {"home": ["battle"], "scout": ["next"], "confirm": ["ok"], "results": ["back"]}
ASPECT_TOLERANCE = 0.02


class CalibrationMismatch(Exception):
    pass


def check_aspect(cfg: Config, win: winctl.GameWindow) -> None:
    if cfg.aspect is None:
        raise CalibrationMismatch("Falta calibrar: no hay proporcion de ventana guardada")
    now = geometry.aspect((win.client_w, win.client_h))
    if abs(now - cfg.aspect) / cfg.aspect > ASPECT_TOLERANCE:
        raise CalibrationMismatch(
            f"La ventana cambio de proporcion ({cfg.aspect:.2f} -> {now:.2f}); recalibra")


class RealGame:
    def __init__(self, win: winctl.GameWindow, cfg: Config, recording: Recording,
                 stop: threading.Event, tpl_dir: Path):
        check_aspect(cfg, win)
        self.win, self.cfg, self.recording, self.stop, self.tpl_dir = win, cfg, recording, stop, Path(tpl_dir)

    def _has(self, frame, name: str) -> bool:
        return templates.match(frame, name, self.tpl_dir)

    def screen_is(self, name: str) -> bool:
        frame = winctl.capture(self.win)
        if name == "battle":
            # Rendirse (<50%) or Terminar batalla (>=50%); both also show on the scout screen
            return (self._has(frame, "surrender") or self._has(frame, "end")) and not self._has(frame, "next")
        return any(self._has(frame, t) for t in SCREEN_TEMPLATES[name])

    def click_button(self, name: str) -> None:
        x, y = self.cfg.buttons[name]
        winctl.click(self.win, x, y)

    def read_resources(self) -> tuple[int | None, int | None]:
        frame = winctl.capture(self.win)
        return (ocr.read_number(frame, self.cfg.regions["gold"]),
                ocr.read_number(frame, self.cfg.regions["elixir"]))

    def read_damage(self) -> int | None:
        return ocr.read_number(winctl.capture(self.win), self.cfg.regions["damage"])

    def play_deployment(self) -> bool:
        return player.play(self.win, self.recording, self.stop)
