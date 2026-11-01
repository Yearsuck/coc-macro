"""Attack loop state machine. Talks only to the Game protocol (see game.py for the real one)."""
import threading
import time
from typing import Callable, Protocol

from cocmacro import decisions
from cocmacro.config import Config
from cocmacro.winctl import WindowMinimized, WindowNotFound

POLL = 0.5
READ_GAP = 0.4
MAX_READ_TRIES = 20


class Game(Protocol):
    def screen_is(self, name: str) -> bool: ...  # home, scout, battle, confirm, results
    def click_button(self, name: str) -> None: ...  # battle, find, attack, next, surrender, ok, back
    def read_resources(self) -> tuple[int | None, int | None]: ...
    def read_damage(self) -> int | None: ...
    def read_time_left(self) -> int | None: ...  # battle clock, seconds
    def play_deployment(self) -> bool: ...


class _Abort(Exception):
    pass


class Bot:
    def __init__(self, game: Game, cfg: Config, log: Callable[[str], None],
                 stop: threading.Event, sleep=time.sleep, timeout_s: float = 60,
                 dry_run: bool = False, battle_timeout_s: float = 240,
                 step_delay: float = 1.0):
        self.game, self.cfg, self.log, self.stop = game, cfg, log, stop
        self.sleep, self.timeout_s, self.dry_run = sleep, timeout_s, dry_run
        self.battle_timeout_s, self.step_delay = battle_timeout_s, step_delay
        self.attacks_done = 0

    # -- helpers -------------------------------------------------------
    def _check(self) -> None:
        if self.stop.is_set():
            raise _Abort("Detenido")

    def _wait(self, pred: Callable[[], bool], what: str) -> None:
        for _ in range(max(1, int(self.timeout_s / POLL))):
            self._check()
            if pred():
                return
            self.sleep(POLL)
        raise _Abort(f"Tiempo agotado esperando: {what}")

    def _click(self, name: str) -> None:
        self._check()
        self.game.click_button(name)

    def _stable_read(self) -> tuple[int, int]:
        """Two equal, valid reads in a row (counters may still be animating)."""
        for _ in range(MAX_READ_TRIES):
            self._check()
            a = self.game.read_resources()
            self.sleep(READ_GAP)
            b = self.game.read_resources()
            if a == b and None not in a:
                return a
            self.sleep(READ_GAP)
        raise _Abort("No se pudo leer oro y elixir de forma fiable")

    # -- cycle ---------------------------------------------------------
    def _cycle(self) -> None:
        self._check()
        if self.dry_run:
            gold, elixir = self._stable_read()
            verdict = "atacaria" if decisions.should_attack(gold, elixir, self.cfg) else "pasaria (Siguiente)"
            self.log(f"[simulacion] oro {gold} elixir {elixir}: {verdict}")
            return
        self._wait(lambda: self.game.screen_is("home"), "pantalla de inicio")
        for name in ("battle", "find", "attack"):
            self._click(name)
            self.sleep(self.step_delay)
        while True:
            self._wait(lambda: self.game.screen_is("scout"), "aldea enemiga")
            gold, elixir = self._stable_read()
            if decisions.should_attack(gold, elixir, self.cfg):
                self.log(f"Atacando: oro {gold}, elixir {elixir}")
                break
            self.log(f"Siguiente: oro {gold}, elixir {elixir}")
            self._click("next")
            self.sleep(self.step_delay)
        self._check()
        if not self.game.play_deployment():
            raise _Abort("Despliegue interrumpido")
        for _ in range(max(1, int(self.battle_timeout_s / POLL))):
            self._check()
            if self.game.screen_is("results"):
                self.log("La batalla termino sola")
                self._click("back")
                break
            pct = self.game.read_damage()
            left = self.game.read_time_left()
            if decisions.should_surrender(pct, self.cfg, left):
                if decisions.should_surrender(pct, self.cfg):
                    self.log(f"Rindiendose con {pct}%")
                else:
                    self.log(f"Rindiendose por tiempo (quedan {left}s)")
                self._click("surrender")
                self._wait(lambda: self.game.screen_is("confirm"), "confirmar rendicion")
                self._click("ok")
                self._wait(lambda: self.game.screen_is("results"), "pantalla de resultados")
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
