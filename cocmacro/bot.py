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

    def _wait(self, pred: Callable[[], bool], what: str) -> None:
        for i in range(max(1, int(self.timeout_s / POLL))):
            self._check()
            if pred():
                return
            if i and i % REPORT_EVERY == 0:
                self.log(f"Sigo esperando: {what} ({i * POLL:.0f}s)")
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
        self._wait(lambda: self.game.screen_is("home"), "pantalla de inicio")
        self._phase("search")
        for name in ("battle", "find", "attack"):
            self._click(name)
            self.sleep(self.step_delay)
        unreadable = 0
        while True:
            self._wait(lambda: self.game.screen_is("scout"), "aldea enemiga")
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
            if decisions.should_surrender(pct, self.cfg, left):
                if decisions.should_surrender(pct, self.cfg):
                    self.log(f"Rindiendose con {pct}%")
                else:
                    self.log(f"Rindiendose por tiempo (quedan {left}s)")
                self._phase("surrender")
                self._click("surrender")
                self._wait(lambda: self.game.screen_is("confirm"), "confirmar rendicion")
                self._click("ok")
                self._wait(lambda: self.game.screen_is("results"), "pantalla de resultados")
                self._phase("back")
                self._click("back")
                break
            self.sleep(POLL)
        else:
            raise _Abort("Tiempo agotado esperando el final de la batalla")
        self._wait(lambda: self.game.screen_is("home"), "volver a la aldea")

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
            if not self.run_once():
                break
