"""Attack loop state machine. Talks only to the Game protocol (see game.py for the real one)."""
import threading
import time
from typing import Callable, Protocol

from cocmacro import decisions
from cocmacro.config import Config
from cocmacro.winctl import WindowMinimized, WindowNotFound

POLL = 0.5
REPORT_EVERY = 20   # polls (10 s) between 'still waiting' messages
READ_GAP = 0.4
MAX_READ_TRIES = 10
BLIND_POLLS = 40         # battle polls (20 s) with no damage reading before a debug capture is kept
FULL_POLL_S = 5          # seconds between storage checks while waiting for room
PET_CHECK_EVERY = 5      # busy mode: the pet counter only shows inside the menu, so look every N attacks
FAIL_WAIT_S = 30         # pause after an upgrade routine that did nothing, before trying again
UNREADABLE_LIMIT = 5   # villages in a row whose loot cannot be read before giving up


class Game(Protocol):
    def screen_is(self, name: str) -> bool: ...  # home, scout, battle, confirm, results
    def click_button(self, name: str) -> None: ...  # battle, find, attack, next, surrender, ok, back
    def read_resources(self) -> tuple[int | None, int | None]: ...
    def read_damage(self) -> int | None: ...
    def read_time_left(self) -> int | None: ...  # battle clock, seconds
    def play_deployment(self) -> bool: ...


class _Abort(Exception):
    pass


class _Unreadable(Exception):
    pass


class Bot:
    def __init__(self, game: Game, cfg: Config, log: Callable[[str], None],
                 stop: threading.Event, sleep=time.sleep, timeout_s: float = 60,
                 dry_run: bool = False, battle_timeout_s: float = 240,
                 step_delay: float = 1.0, read_tries: int = MAX_READ_TRIES,
                 unreadable_limit: int = UNREADABLE_LIMIT,
                 on_phase: Callable[[str], None] | None = None,
                 on_reading: Callable[[dict], None] | None = None):
        self.game, self.cfg, self.log, self.stop = game, cfg, log, stop
        self.sleep, self.timeout_s, self.dry_run = sleep, timeout_s, dry_run
        self.battle_timeout_s, self.step_delay = battle_timeout_s, step_delay
        self.read_tries, self.unreadable_limit = read_tries, unreadable_limit
        self.on_phase, self.on_reading, self._reading_state = on_phase, on_reading, {}
        self.attacks_done = 0

    # -- helpers -------------------------------------------------------
    def _phase(self, name: str) -> None:
        if self.on_phase:
            try:
                self.on_phase(name)
            except Exception:
                pass     # the window must never break the run

    def _reading(self, **values) -> None:
        self._reading_state.update(values)
        if self.on_reading:
            try:
                self.on_reading(dict(self._reading_state))
            except Exception:
                pass

    def _check(self) -> None:
        if self.stop.is_set():
            raise _Abort("Detenido")

    def _why(self, screen: str | None) -> str:
        fn = getattr(self.game, "why_not", None)
        if not fn or not screen:
            return ""
        try:
            return f" - {fn(screen)}"
        except Exception:
            return ""

    def _dismiss_popup(self) -> None:
        """Close an unexpected 'Vale' notice (star bonus after a win) so it cannot block the next screen."""
        fn = getattr(self.game, "dismiss_popup", None)
        if fn and fn():
            self.log("Cierro un aviso (bonus estelar)")
            self.sleep(self.step_delay)

    def _wait(self, pred: Callable[[], bool], what: str, screen: str | None = None,
              popups: bool = False) -> None:
        for i in range(max(1, int(self.timeout_s / POLL))):
            self._check()
            if pred():
                return
            if popups:
                self._dismiss_popup()
            if i and i % REPORT_EVERY == 0:
                self.log(f"Sigo esperando: {what} ({i * POLL:.0f}s){self._why(screen)}")
            self.sleep(POLL)
        raise _Abort(f"Tiempo agotado esperando: {what}")

    def _click(self, name: str) -> None:
        self._check()
        self.game.click_button(name)

    def _stable_read(self) -> tuple[int, int]:
        """Two equal, valid reads in a row (counters may still be animating)."""
        for _ in range(self.read_tries):
            self._check()
            a = self.game.read_resources()
            self.sleep(READ_GAP)
            b = self.game.read_resources()
            if a == b and None not in a:
                return a
            self.sleep(READ_GAP)
        raise _Unreadable("No se pudo leer oro y elixir de forma fiable")

    def _dump(self, reason: str) -> None:
        """Keep a capture of what could not be read, if the game backend supports it."""
        fn = getattr(self.game, "dump_debug", None)
        if fn:
            try:
                fn(reason)
            except Exception as e:
                self.log(f"(no se pudo guardar la captura: {e})")

    # -- cycle ---------------------------------------------------------
    def _close_leftover_menu(self) -> None:
        """A routine stopped with F8 can leave the Construir menu or an upgrade window open, which hides
        Batalla: close them first (at most 3 presses, looking again between them)."""
        fn = getattr(self.game, "close_menu", None)
        if not fn:
            return
        for _ in range(3):
            self._check()
            if not fn():
                return
            self.log("Cierro un menu o ventana que quedo abierto")
            self._nap(self.step_delay)

    def _cycle(self) -> None:
        self._check()
        if self.dry_run:
            try:
                gold, elixir = self._stable_read()
            except _Unreadable:
                self._dump("loot")
                self.log("[simulacion] No se pudo leer oro y elixir")
                return
            verdict = "atacaria" if decisions.should_attack(gold, elixir, self.cfg) else "pasaria (Siguiente)"
            self.log(f"[simulacion] oro {gold} elixir {elixir}: {verdict}")
            return
        self._close_leftover_menu()
        self._wait(lambda: self.game.screen_is("home"), "pantalla de inicio", "home", popups=True)
        self._phase("search")
        for name in ("battle", "find", "attack"):
            self._click(name)
            self.sleep(self.step_delay)
        unreadable = 0
        while True:
            self._wait(lambda: self.game.screen_is("scout"), "aldea enemiga", "scout")
            self._phase("evaluate")
            self._reading(gold=None, elixir=None, verdict=None, damage=None, time_left=None)
            try:
                gold, elixir = self._stable_read()
            except _Unreadable:
                unreadable += 1
                self._dump("loot")
                if unreadable >= self.unreadable_limit:
                    raise _Abort(f"No se pudo leer oro y elixir en {unreadable} aldeas seguidas: parado. "
                                 "Mira las capturas de la carpeta data/debug o recalibra")
                self.log(f"No se pudo leer el botin: salto esta aldea ({unreadable} seguidas)")
                self._click("next")
                self.sleep(self.step_delay)
                continue
            unreadable = 0
            self._reading(gold=gold, elixir=elixir,
                          verdict="attack" if decisions.should_attack(gold, elixir, self.cfg) else "skip")
            if decisions.should_attack(gold, elixir, self.cfg):
                self.log(f"Atacando: oro {gold}, elixir {elixir}")
                break
            self.log(f"Siguiente: oro {gold}, elixir {elixir}")
            self._click("next")
            self.sleep(self.step_delay)
        self._check()
        self._phase("deploy")
        if not self.game.play_deployment():
            raise _Abort("Despliegue interrumpido")
        blind = 0
        for _ in range(max(1, int(self.battle_timeout_s / POLL))):
            self._check()
            if self.game.screen_is("results"):
                self.log("La batalla termino sola")
                self._phase("back")
                self._click("back")
                break
            self._phase("watch")
            pct = self.game.read_damage()
            left = self.game.read_time_left()
            self._reading(damage=pct, time_left=left)
            blind = 0 if pct is not None else blind + 1
            if blind == BLIND_POLLS:
                self.log("No consigo leer el daño; guardo una captura en data/debug")
                self._dump("damage")
            if decisions.should_surrender(pct, self.cfg, left):
                if decisions.should_surrender(pct, self.cfg):
                    self.log(f"Rindiendose con {pct}%")
                else:
                    self.log(f"Rindiendose por tiempo (quedan {left}s)")
                self._phase("surrender")
                self._click("surrender")
                self._wait(lambda: self.game.screen_is("confirm"), "confirmar rendicion", "confirm")
                self._click("ok")
                self._wait(lambda: self.game.screen_is("results"), "pantalla de resultados", "results")
                self._phase("back")
                self._click("back")
                break
            self.sleep(POLL)
        else:
            raise _Abort("Tiempo agotado esperando el final de la batalla")
        self._wait(lambda: self.game.screen_is("home"), "volver a la aldea", "home", popups=True)

    # -- modes: storages full / spend free builders ---------------------
    def _nap(self, seconds: float) -> None:
        """Sleep in short steps so F8 is honoured."""
        for _ in range(max(1, int(seconds / POLL))):
            self._check()
            self.sleep(POLL)

    def _storages_full(self) -> bool:
        fn = getattr(self.game, "storages_full", None)
        try:
            return bool(fn and fn() is True)
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:             # an unreadable screen must not take the bot down
            self.log(f"No pude leer los depositos: {e}")
            return False

    def _slot_free(self) -> bool:
        fn = getattr(self.game, "free_slots", None)
        if not fn:
            return False
        try:
            slots = fn()
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"No pude leer los constructores: {e}")
            return False
        keys = ("builders",) if self.cfg.mode == "walls" else ("builders", "researchers")
        if any((slots.get(k) or 0) >= 1 for k in keys):
            return True
        # busy mode also covers pets, which are only readable inside the menu
        return self.cfg.mode == "busy" and self.attacks_done > 0 and self.attacks_done % PET_CHECK_EVERY == 0

    def _spend(self) -> bool:
        """Run the upgrade routine of the active mode. A routine that fails never stops the bot."""
        fn = getattr(self.game, "upgrade", None)
        if not fn:
            return False
        self._phase("upgrade")
        self.log("Mejorando muros" if self.cfg.mode == "walls" else "Mejorando lo mas barato")
        try:
            ok = bool(fn(self.cfg.mode, self.log, self._check))
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"La mejora fallo: {e}")
            return False
        if not ok:
            self.log("No se pudo mejorar nada")
        return ok

    def after_attack(self) -> None:
        if self.dry_run or self.cfg.mode == "none":
            return
        if self._slot_free():
            self._spend()

    def wait_if_full(self) -> None:
        """No attacks while gold and elixir are full; in a mode, spend a free slot meanwhile."""
        if self.dry_run or not (self.cfg.stop_when_full or self.cfg.mode != "none"):
            return
        announced = False
        while self._storages_full():
            self._check()
            if self.cfg.mode == "busy" or (self.cfg.mode != "none" and self._slot_free()):
                if not self._spend():
                    self._nap(FAIL_WAIT_S)
                continue
            if not announced:
                self.log("Depositos llenos: espero")
                announced = True
            self._nap(FULL_POLL_S)

    def run_once(self) -> bool:
        try:
            self._cycle()
        except _Abort as e:
            self.log(str(e))
            return False
        except (WindowNotFound, WindowMinimized) as e:
            self.log(str(e))
            return False
        if not self.dry_run:
            self.attacks_done += 1
            self.log(f"Ataque {self.attacks_done} completado")
        return True

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                if not self.dry_run:
                    self._close_leftover_menu()      # so the storage bars are readable
                self.wait_if_full()
            except (_Abort, WindowNotFound, WindowMinimized) as e:
                self.log(str(e))
                break
            if not self.run_once():
                break
            try:
                self.after_attack()
            except (_Abort, WindowNotFound, WindowMinimized) as e:
                self.log(str(e))
                break
