"""Real Game backend: window capture + templates + OCR + replay, behind bot.Game."""
import threading
import time
from pathlib import Path

import cv2

from cocmacro import frames, ocr, player, templates, upgrades, vision, winctl
from cocmacro.config import Config
from cocmacro.recorder import Recording

# Template(s) whose presence identifies each screen.
SCREEN_TEMPLATES = {"home": ["battle"], "scout": ["next"], "confirm": ["ok"], "results": ["back"]}
DEBUG_KEEP = 60     # newest debug images kept
# The inactivity dialog took the click at (0.355, 0.571) in one window and only at (0.355, 0.576) in another
# (measured live), so the press tries a few nearby points, keeping the focus, until the dialog is gone.
RELOAD_TAP_OFFSETS = ((0.0, 0.0), (0.0, 0.005), (0.0, -0.005), (0.015, 0.005), (-0.015, 0.005), (0.0, 0.010))
RELOAD_TAP_POLLS, RELOAD_TAP_POLL_S = 4, 0.5      # looks (2 s) at the dialog after each tap
INACTIVITY_TEMPLATES = (("reload_inactive_title", 0.80), ("reload_inactive_body", 0.75))


GOLD_HUE, ELIXIR_HUE = (18, 40), (135, 175)   # OpenCV hue of the gold and elixir storage bars


class _Screen:
    """upgrades.Screen over the real window: capture, click, template lookups."""

    def __init__(self, game: "RealGame", check=None):
        self.game, self.check = game, check or (lambda: None)      # check() raises when F8 was pressed

    def grab(self):
        return frames.grab(self.game.win)

    def click(self, x: float, y: float) -> None:
        winctl.click(self.game.win, x, y)

    def zoom_out(self) -> None:
        """Wheel the camera out until the picture stops changing (it may be zooming or still moving)."""
        previous = None
        for i in range(12):
            for _ in range(3):
                self.check()
                winctl.post_wheel(self.game.win, 0.5, 0.45, -120)
                time.sleep(0.12)
            time.sleep(0.5)
            frame = self.grab()
            # the game may not have started zooming yet: never decide before a few rounds
            if i >= 3 and float(abs(frame.astype(int) - previous.astype(int)).mean()) < 1.5:
                return
            previous = frame

    def wall_spot(self):
        return vision.find_wall_spot(self.grab())

    def has(self, template: str) -> bool:
        return templates.match(self.grab(), template, self.game.tpl_dir)

    def find(self, template: str):
        found = templates.score(self.grab(), template, self.game.tpl_dir)
        return found[1] if found is not None and found[0] >= templates.threshold_for(template) else None


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

    def close_menu(self) -> bool:
        """Something a stopped routine left open: an upgrade window first (its own X), then the Construir menu.
        The menu's X is pressed only where it really is (the corner is the gold bar when no menu is open and
        that opens the gem shop). True if a button was pressed."""
        frame = frames.grab(self.win)
        if self._has(frame, "upgrade_window"):
            x, y = self.cfg.buttons["upgrade_window_close"]
            winctl.click(self.win, x, y)
            return True
        found = templates.score(frame, "menu_close_x", self.tpl_dir)
        if found is None or found[0] < templates.threshold_for("menu_close_x"):
            return False
        bx, by = self.cfg.buttons["build_close"]
        if abs(found[1][0] - bx) > 0.04 or abs(found[1][1] - by) > 0.05:
            return False                 # a red X elsewhere (another window): not ours to press blindly
        winctl.click(self.win, bx, by)
        return True

    def dismiss_popup(self) -> bool:
        """A 'Vale' button on screen (star bonus after a win) is pressed where it is. True if pressed."""
        found = templates.score(frames.grab(self.win), "ok", self.tpl_dir)
        if found is None or found[0] < templates.THRESHOLD:
            return False
        winctl.click(self.win, found[1][0], found[1][1])
        return True

    def inactivity_dialog(self) -> bool:
        """The 'Estas ahi? Se te ha desconectado por inactividad' dialog is on screen. Its title AND its body
        text must both match: the 'Conexion perdida / otro dispositivo' dialog has the same dark box and a
        similar button, and pressing that one would kick the account's other session. Measured on real frames:
        the true dialog scores 0.83-1.0 on both crops, every screen without it 0.52 or less."""
        frame = frames.grab(self.win)
        return all(templates.match(frame, name, self.tpl_dir, threshold)
                   for name, threshold in INACTIVITY_TEMPLATES)

    def reload_if_disconnected(self) -> bool:
        """Press VOLVER A CARGAR if the inactivity dialog is visible. True if pressed. The dialog only takes
        the click while the window is the active one, so it gets the focus for the press."""
        if not self.inactivity_dialog():
            return False
        x, y = self.cfg.buttons["reload_inactive"]
        with winctl.exclusive_input(self.stop) as got:
            if not got:                          # stopped while waiting for the other account: no focus grab
                return True
            with winctl.focused(self.win):
                # the focus stays on the window the whole time: giving it back right after a click made the
                # dialog ignore it (measured live)
                for dx, dy in RELOAD_TAP_OFFSETS:
                    if self.stop.is_set():       # F8: let go of the focus right away
                        return True
                    winctl.click(self.win, x + dx, y + dy)
                    for _ in range(RELOAD_TAP_POLLS):
                        time.sleep(RELOAD_TAP_POLL_S)
                        if self.stop.is_set() or not self.inactivity_dialog():
                            return True
        return True

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

    def storages_full(self) -> bool | None:
        """Gold, elixir AND dark elixir storages full. A clear 'not full' wins over an unreadable one. The dark
        elixir bar is optional only in config: with no `storage_dark` region it is ignored (gold and elixir decide)
        and an unreadable bar (None) is ignored too. An account WITHOUT a dark elixir bar is not detected: the
        region then shows other pixels and reads as 'not full', so such an account never waits on full storages."""
        frame = frames.grab(self.win)
        gold = vision.storage_full(frame, self.cfg.regions["storage_gold"], hue=GOLD_HUE)
        elixir = vision.storage_full(frame, self.cfg.regions["storage_elixir"], hue=ELIXIR_HUE)
        region = self.cfg.regions.get("storage_dark")
        dark = vision.dark_storage_full(frame, region) if region else None
        if gold is False or elixir is False or dark is False:
            return False
        return True if gold is True and elixir is True else None

    def free_slots(self) -> dict[str, int | None]:
        return upgrades.free_slots(_Screen(self), self.cfg)

    def upgrade(self, kind: str, log, check) -> bool:
        scr = _Screen(self, check)
        if kind == "walls":
            return upgrades.upgrade_walls(scr, self.cfg, log, check, time.sleep)
        if kind == "busy":
            return upgrades.upgrade_busy(scr, self.cfg, log, check, time.sleep, heroes=self.cfg.prioritize_heroes)
        if kind == "surplus":      # walls mode: cheapest permanent upgrades for every builder beyond the one reserved
            return upgrades.upgrade_busy(scr, self.cfg, log, check, time.sleep,
                                         only=("builders",), keep={"builders": 1})
        return False

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
