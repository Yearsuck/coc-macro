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
# A repeated press of one button moves by these offsets (about 10 x 4 px at 1296 x 729: inside any button).
PRESS_NUDGES = ((0.0, 0.0), (0.008, 0.006), (-0.008, -0.006), (0.008, -0.006), (-0.008, 0.006))
SEARCH_BACK_AT = (0.055, 0.905)     # where the search screen draws its Volver button
DIALOG_CONFIRM_S = 0.3   # an unknown dialog must still be there after this long before it is pressed
REPEAT_PRESS_S = 8      # a press this soon after the last one of the same button counts as repeated
SHOP_CLOSE_AT = (0.968, 0.062)     # where the full-screen shop draws its red X
STAR_BONUS_STEPS = 12     # chest taps + 'Continuar' presses at most (live: 3-4 taps, then one press)
STAR_TAP_S, STAR_CONTINUE_S = 1.2, 2.0     # the chest shakes after a tap; the reward fades out after Continuar
INACTIVITY_TEMPLATES = (("reload_inactive_title", 0.80), ("reload_inactive_body", 0.75))


GOLD_HUE, ELIXIR_HUE = (18, 40), (135, 175)   # OpenCV hue of the gold and elixir storage bars


class _Stopped(Exception):
    """Stop was asked for in the middle of a camera move."""


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

    def drag(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Press at (x0, y0), pull to (x1, y1) in small steps and release: scrolls the Construir list (a single
        jump is read as a tap by the game)."""
        self.check()
        steps = 15
        winctl.post_mouse(self.game.win, "down", x0, y0)
        for i in range(1, steps + 1):
            time.sleep(0.03)
            winctl.post_mouse(self.game.win, "move", x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        winctl.post_mouse(self.game.win, "up", x1, y1)
        time.sleep(0.4)                         # the list keeps gliding for a moment after the release

    def has(self, template: str) -> bool:
        return templates.match(self.grab(), template, self.game.tpl_dir)

    def find(self, template: str):
        found = templates.score(self.grab(), template, self.game.tpl_dir)
        return found[1] if found is not None and found[0] >= templates.threshold_for(template) else None

    def find_all(self, template: str) -> list[tuple[float, float]]:
        return templates.find_all(self.grab(), template, self.game.tpl_dir)


class RealGame:
    def __init__(self, win: winctl.GameWindow, cfg: Config, recording: Recording,
                 stop: threading.Event, tpl_dir: Path, debug_dir: Path | None = None):
        self.win, self.cfg, self.recording, self.stop, self.tpl_dir = win, cfg, recording, stop, Path(tpl_dir)
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self._last_button, self._last_press_at, self._presses = "", 0.0, 0

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

    def battle_menu_open(self) -> bool:
        """The Batalla menu (Multijugador / Un jugador / Practica tabs over the left half of the village) is up."""
        return self._has(frames.grab(self.win), "battle_menu")

    def close_menu(self) -> bool:
        """Something a stopped routine left open: an upgrade window first (its own X), then the Construir menu.
        The menu's X is pressed only where it really is (the corner is the gold bar when no menu is open and
        that opens the gem shop). True if a button was pressed."""
        frame = frames.grab(self.win)
        if self._has(frame, "upgrade_window"):
            x, y = self.cfg.buttons["upgrade_window_close"]
            winctl.click(self.win, x, y)
            return True
        shop = self._found(frame, "upgrade_window_x")       # the same red X, drawn in the shop's corner
        if shop is not None and abs(shop[0] - SHOP_CLOSE_AT[0]) <= templates.POS_TOL                 and abs(shop[1] - SHOP_CLOSE_AT[1]) <= templates.POS_TOL:
            winctl.click(self.win, *shop)     # the shop opens by itself at times (offers, after a reload)
            return True
        found = templates.score(frame, "menu_close_x", self.tpl_dir)
        if found is None or found[0] < templates.threshold_for("menu_close_x"):
            return False
        bx, by = self.cfg.buttons["build_close"]
        if abs(found[1][0] - bx) > 0.04 or abs(found[1][1] - by) > 0.05:
            return False                 # a red X elsewhere (another window): not ours to press blindly
        winctl.click(self.win, bx, by)
        return True

    def cancel_search(self) -> bool:
        """The search screen (clouds) with its Volver button: 'Buscando rivales...' that never ends, or 'No se
        ha podido atacar esta aldea. Intentalo mas tarde' after a connection problem (live 2026-11-15: the bot
        sat on it until the wait ran out). Press Volver where it is. True if pressed."""
        found = templates.score(frames.grab(self.win), "search_back", self.tpl_dir)
        if found is None or found[0] < templates.threshold_for("search_back"):
            return False
        if abs(found[1][0] - SEARCH_BACK_AT[0]) > templates.POS_TOL or abs(found[1][1] - SEARCH_BACK_AT[1]) > templates.POS_TOL:
            return False
        winctl.click(self.win, found[1][0], found[1][1])
        return True

    def _found(self, frame, name: str):
        found = templates.score(frame, name, self.tpl_dir)
        return found[1] if found is not None and found[0] >= templates.threshold_for(name) else None

    def _collect_star_bonus(self, first) -> bool:
        """The star bonus once the day's stars are in (live 2026-11-27): a chest to tap ('Toca', a few taps, one
        rolling pin each) until it opens, then the reward with a green 'Continuar', then the village. Goes through
        all of it in one call (the screens come and go between the bot's own looks). True if it was on screen."""
        if self._found(first, "star_chest") is None and self._found(first, "star_continue") is None:
            return False
        for i in range(STAR_BONUS_STEPS):
            if self.stop.is_set():
                break
            frame = frames.grab(self.win)
            button = self._found(frame, "star_continue")
            chest = None if button else self._found(frame, "star_chest")
            if button is None and chest is None:
                break                                  # back in the village (or another screen): done
            x, y = button or chest
            dx, dy = PRESS_NUDGES[i % len(PRESS_NUDGES)]   # repeated taps at one point can be ignored
            winctl.click(self.win, x + dx, y + dy)
            time.sleep(STAR_CONTINUE_S if button else STAR_TAP_S)
        return True

    def dismiss_popup(self) -> bool:
        """The star bonus chest and its reward, or a 'Vale' button on screen (a notice after a win), are dealt
        with where they are. True if something was pressed."""
        frame = frames.grab(self.win)
        if self._collect_star_bonus(frame):
            return True
        found = templates.score(frame, "ok", self.tpl_dir)
        if found is None or found[0] < templates.THRESHOLD:
            return False
        winctl.click(self.win, found[1][0], found[1][1])
        return True

    def _reload_dialog_info(self, frame=None) -> tuple[tuple[float, float] | None, bool]:
        """((x, y) of the button to press or None, is it the inactivity dialog). The inactivity dialog is
        known by its text. Any other dialog is found by shape only, so it must be there in two looks a moment
        apart: a passing screen that happens to match must not get the game tapped."""
        if frame is None:
            frame = frames.grab(self.win)
        is_inactivity = all(templates.match(frame, name, self.tpl_dir, threshold)
                            for name, threshold in INACTIVITY_TEMPLATES)
        if is_inactivity:
            return (self.cfg.buttons["reload_inactive"], True)
        if vision.native_dialog(frame) is None:
            return (None, False)
        time.sleep(DIALOG_CONFIRM_S)
        return (vision.native_dialog(frames.grab(self.win)), False)

    def inactivity_dialog(self) -> bool:
        """The 'Estas ahi? Se te ha desconectado por inactividad' dialog is on screen. Its title AND its body
        text must both match: the 'Conexion perdida / otro dispositivo' dialog has the same dark box and a
        similar button, and pressing that one would kick the account's other session. Measured on real frames:
        the true dialog scores 0.83-1.0 on both crops, every screen without it 0.52 or less."""
        frame = frames.grab(self.win)
        return all(templates.match(frame, name, self.tpl_dir, threshold)
                   for name, threshold in INACTIVITY_TEMPLATES)

    def reload_dialog(self) -> tuple[float, float] | None:
        """The inactivity dialog -> cfg.buttons["reload_inactive"]; otherwise any native dialog
        (vision.native_dialog) -> centre of its blue button; otherwise None."""
        pt, _ = self._reload_dialog_info()
        return pt

    def any_dialog(self) -> bool:
        """True if any reload / native dialog is on screen."""
        return self.reload_dialog() is not None

    def reload_if_disconnected(self) -> bool:
        """Press the reload / retry button on any native dialog. True if pressed. The taps go through
        winctl.click, which marks this window as the active instance first (the host forwards input to the
        active instance only), so the user's keyboard focus is never touched."""
        dialog_point, is_inactivity = self._reload_dialog_info()
        if dialog_point is None:
            return False
        x, y = dialog_point
        if not is_inactivity:
            try:
                self.dump_debug("dialog")        # the only way to get a sample of a dialog never seen before
            except Exception:
                pass                             # a full disk must not leave the dialog unpressed
        with winctl.exclusive_input(self.stop) as got:
            if not got:                          # stopped while waiting for the other account
                return True
            for dx, dy in RELOAD_TAP_OFFSETS:
                if self.stop.is_set():           # F8
                    return True
                winctl.click(self.win, x + dx, y + dy)
                for _ in range(RELOAD_TAP_POLLS):
                    time.sleep(RELOAD_TAP_POLL_S)
                    if self.stop.is_set() or self.reload_dialog() is None:
                        return True
        return True

    def click_button(self, name: str) -> None:
        """Press a calibrated button. The same button pressed again within REPEAT_PRESS_S is pressed at a
        point a few pixels away: the host can ignore a tap that lands where the last one did (live: four
        presses of Siguiente in a row at one point did nothing, then a button elsewhere worked at once)."""
        x, y = self.cfg.buttons[name]
        now = time.monotonic()
        repeated = name == self._last_button and now - self._last_press_at < REPEAT_PRESS_S
        self._presses = self._presses + 1 if repeated else 0
        self._last_button, self._last_press_at = name, now
        dx, dy = PRESS_NUDGES[self._presses % len(PRESS_NUDGES)]
        winctl.click(self.win, x + dx, y + dy)

    def read_resources(self) -> tuple[int | None, int | None]:
        frame = frames.grab(self.win)
        return (ocr.read_number(frame, self.cfg.regions["gold"]),
                ocr.read_number(frame, self.cfg.regions["elixir"]))

    def read_damage(self) -> int | None:
        return ocr.read_number(frames.grab(self.win), self.cfg.regions["damage"])

    def read_time_left(self) -> int | None:
        return ocr.read_time_left(frames.grab(self.win), self.cfg.regions["timer"])

    def storage_levels(self) -> dict[str, bool | None]:
        """Individual storage readings: gold, elixir, and dark (None when there is no dark region)."""
        frame = frames.grab(self.win)
        gold = vision.storage_full(frame, self.cfg.regions.get("storage_gold"), hue=GOLD_HUE)
        elixir = vision.storage_full(frame, self.cfg.regions.get("storage_elixir"), hue=ELIXIR_HUE)
        region = self.cfg.regions.get("storage_dark")
        dark = vision.dark_storage_full(frame, region) if region else None
        return {"gold": gold, "elixir": elixir, "dark": dark}

    def storages_full(self) -> bool | None:
        """Gold, elixir AND dark elixir storages full. A clear 'not full' wins over an unreadable one. The dark
        elixir bar is optional only in config: with no `storage_dark` region it is ignored (gold and elixir decide)
        and an unreadable bar (None) is ignored too. An account WITHOUT a dark elixir bar is not detected: the
        region then shows other pixels and reads as 'not full', so such an account never waits on full storages."""
        levels = self.storage_levels()
        gold, elixir, dark = levels["gold"], levels["elixir"], levels["dark"]
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
        # The recording was made with the camera all the way out. The game keeps the zoom between screens, and the
        # wall routine leaves it close on a wall (live 2026-11-27: every tap fell on a building, nothing deployed).
        def check() -> None:
            if self.stop.is_set():
                raise _Stopped

        try:
            _Screen(self, check).zoom_out()
        except _Stopped:
            return False
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
