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
SEARCH_TRIES = 3          # presses of Batalla / Buscar / Atacar before giving up
SEARCH_RETRY_S = 12       # seconds to see the scout screen before pressing them again
FULL_POLL_S = 5          # seconds between storage checks while waiting for room
STORAGE_SETTLE = 0.6      # seconds for the HUD to settle after a window closes, before the first reading
STORAGE_READ_GAP = 0.4   # seconds between the readings of the storage bars
MAX_SPEND_ROUNDS = 10    # upgrade routines run back to back before an attack
FAIL_WAIT_S = 30         # pause after an upgrade routine that did nothing, before trying again
UNREADABLE_LIMIT = 5   # villages in a row whose loot cannot be read before giving up
RELOAD_WAIT_S = 300      # seconds to wait for the village after reloading (it can open a live replay of an attack, ~3 min)
RELOAD_TRIES = 3         # presses of VOLVER A CARGAR before giving up
RELOAD_PRESS_WAIT_S = 20  # seconds to see the dialog go away after a press
SURRENDER_TRIES = 3       # presses of Rendirse before giving up on the confirmation window
CONFIRM_WAIT_S = 6        # seconds to see the confirmation window after pressing Rendirse
TIME_RULE_GRACE_POLLS = 20  # the clock rule only counts after this many battle polls (>= 10 s: OCR slows each
                            # poll) since the deployment ended; turns of the other account shift the clock
BACK_EVERY_S = 4          # while on the results screen, press Volver again this often
RELOAD_SETTLE_S = 2      # extra seconds once the village is back


class Game(Protocol):
    def screen_is(self, name: str) -> bool: ...  # home, scout, battle, confirm, results
    def click_button(self, name: str) -> None: ...  # battle, find, attack, next, surrender, ok, back
    def read_resources(self) -> tuple[int | None, int | None]: ...
    def read_damage(self) -> int | None: ...
    def read_time_left(self) -> int | None: ...  # battle clock, seconds
    def play_deployment(self) -> bool: ...
    def reload_if_disconnected(self) -> bool: ...  # inactivity dialog: press it, True if pressed
    def inactivity_dialog(self) -> bool: ...       # optional: is that dialog still on screen


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

    def _dismiss_popup(self) -> bool:
        """Close an unexpected 'Vale' notice (star bonus after a win) so it cannot block the next screen.
        True if one was closed."""
        fn = getattr(self.game, "dismiss_popup", None)
        if fn and fn():
            self.log("Cierro un aviso (bonus estelar)")
            self.sleep(self.step_delay)
            return True
        return False

    def _reload_if_disconnected(self) -> bool:
        """Inactivity dialog: press 'VOLVER A CARGAR' and wait for the village to return. True if pressed."""
        if self.dry_run:
            return False
        fn = getattr(self.game, "reload_if_disconnected", None)
        if not fn:
            return False
        try:
            pressed = fn()
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"No pude comprobar la sesion: {e}")
            return False
        if not pressed:
            return False
        self.log("Sesion desconectada por inactividad: recargo")
        # The village is visible behind the dialog, so "home" alone proves nothing: first the dialog must go.
        # If it stays the press was not taken: press again.
        still_up = getattr(self.game, "inactivity_dialog", None)
        if still_up:
            for attempt in range(RELOAD_TRIES):
                for _ in range(max(1, int(RELOAD_PRESS_WAIT_S / POLL))):
                    self._check()
                    if not still_up():
                        break
                    self.sleep(POLL)
                else:
                    if attempt + 1 >= RELOAD_TRIES:
                        raise _Abort("La sesion no se recargo: el aviso sigue ahi")
                    self.log("El aviso sigue: pulso otra vez")
                    fn()
                    continue
                break
        for _ in range(max(1, int(RELOAD_WAIT_S / POLL))):
            self._check()
            if self.game.screen_is("home"):
                break
            self.sleep(POLL)
        else:
            raise _Abort("La aldea no cargo tras recargar")
        self._nap(RELOAD_SETTLE_S)
        return True

    def _wait(self, pred: Callable[[], bool], what: str, screen: str | None = None,
              popups: bool = False, results: bool = False) -> None:
        """Wait for `pred`. `popups` also closes a 'Vale' notice; `results` also presses Volver again every
        BACK_EVERY_S while the results screen is up (the caller pressed it once already, or the first press was
        lost, and the bot would wait for the village forever). Never at the first look: that would double-press."""
        for i in range(max(1, int(self.timeout_s / POLL))):
            self._check()
            if pred():
                return
            if popups:
                self._dismiss_popup()
            if results and i and i % max(1, int(BACK_EVERY_S / POLL)) == 0 and self.game.screen_is("results"):
                self.log("Estoy en la pantalla de resultados: pulso Volver")
                self._click("back")
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

    def _open_search(self) -> None:
        """Batalla -> Buscar -> Atacar. A notice (star bonus after a win) can appear late and swallow these
        clicks, leaving the village on screen: if after a few seconds it is still the village, press them again
        (at most 3 times). Still loading a village (not the village, not scouting yet) is NOT retried."""
        for attempt in range(SEARCH_TRIES):
            self._reload_if_disconnected()
            for name in ("battle", "find", "attack"):
                self._click(name)
                self.sleep(self.step_delay)
            noticed = False
            for _ in range(int(SEARCH_RETRY_S / POLL)):
                self._check()
                if self.game.screen_is("scout"):
                    return
                if self._dismiss_popup():
                    noticed = True            # it swallowed the presses: press them again right away
                    break
                if self._reload_if_disconnected():
                    noticed = True
                    break
                self.sleep(POLL)
            if not noticed and not self.game.screen_is("home"):
                return                        # loading: let the normal wait for the scout screen handle it
            if attempt + 1 < SEARCH_TRIES:
                self.log("La busqueda no arranco (aviso encima?): repito Batalla, Buscar, Atacar")
        raise _Abort(f"La busqueda no arranco tras {SEARCH_TRIES} intentos: sigo en el pueblo")

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
        if self.game.screen_is("results"):
            self.log("Estoy en la pantalla de resultados: pulso Volver")
            self._click("back")
        self._wait(lambda: self.game.screen_is("home"), "pantalla de inicio", "home", popups=True, results=True)
        self._phase("search")
        self._open_search()
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
        blind, since_deploy = 0, 0
        grace_polls = TIME_RULE_GRACE_POLLS
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
            since_deploy += 1
            # the clock rule counts from the end of the deployment: waiting for the other account's turn to deploy
            # already used up part of the 3 minutes and must not make this one give up before its troops fight
            rule_left = left if since_deploy >= grace_polls else None
            if decisions.should_surrender(pct, self.cfg, rule_left):
                if decisions.should_surrender(pct, self.cfg):
                    self.log(f"Rindiendose con {pct}%")
                else:
                    self.log(f"Rindiendose por tiempo (quedan {left}s)")
                self._phase("surrender")
                if not self._surrender():
                    break                          # the battle ended by itself while surrendering
                self._wait(lambda: self.game.screen_is("results"), "pantalla de resultados", "results")
                self._phase("back")
                self._click("back")
                break
            self.sleep(POLL)
        else:
            raise _Abort("Tiempo agotado esperando el final de la batalla")
        self._wait(lambda: self.game.screen_is("home"), "volver a la aldea", "home", popups=True, results=True)

    def _surrender(self) -> bool:
        """Press Rendirse and confirm. The press can be lost (the game was busy), so if the confirmation window
        does not show within a few seconds it is pressed again (SURRENDER_TRIES times). False if the battle ended
        on its own meanwhile (results screen), True once the confirmation was pressed."""
        for attempt in range(SURRENDER_TRIES):
            self._click("surrender")
            for _ in range(max(1, int(CONFIRM_WAIT_S / POLL))):
                self._check()
                if self.game.screen_is("confirm"):
                    self._click("ok")
                    return True
                if self.game.screen_is("results"):
                    return False
                self.sleep(POLL)
            if attempt + 1 < SURRENDER_TRIES:
                self.log("La rendicion no se confirmo: pulso Rendirse otra vez")
        raise _Abort("Tiempo agotado esperando: confirmar rendicion")

    # -- modes: storages full / spend free builders ---------------------
    def _nap(self, seconds: float) -> None:
        """Sleep in short steps so F8 is honoured."""
        for _ in range(max(1, int(seconds / POLL))):
            self._check()
            self.sleep(POLL)

    def _storages_full(self) -> bool:
        """Full if two readings say so, out of up to 4. Right after a window closes the HUD is shifted for a
        moment and a bar can read 'not full', so the HUD gets a moment to settle first and one reading is not
        trusted. An unreadable reading (None) counts for neither side; if nothing is ever clear it is not full."""
        fn = getattr(self.game, "storages_full", None)
        if not fn:
            return False
        self.sleep(STORAGE_SETTLE)
        full = not_full = 0
        try:
            for i in range(4):
                if i:
                    self.sleep(STORAGE_READ_GAP)
                answer = fn()
                if answer is True:
                    full += 1
                elif answer is False:
                    not_full += 1
                if full == 2 or not_full == 2:
                    break
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:             # an unreadable screen must not take the bot down
            self.log(f"No pude leer los depositos: {e}")
            return False
        return full >= 2

    def _slot_free(self) -> bool:
        if self.cfg.mode == "busy":
            return True      # the pet counter is only readable inside the Construir menu: always look there
        return self._free_builders() >= 1

    def _spend(self, kind: str | None = None) -> bool:
        """Run an upgrade routine (by default the one of the active mode). A routine that fails never stops the bot."""
        fn = getattr(self.game, "upgrade", None)
        if not fn:
            return False
        kind = kind or self.cfg.mode
        self._phase("upgrade")
        self.log({"walls": "Mejorando muros", "surplus": "Sobran constructores: lo mas barato permanente"}
                 .get(kind, "Mejorando lo mas barato"))
        try:
            ok = bool(fn(kind, self.log, self._check))
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"La mejora fallo: {e}")
            return False
        if not ok:
            self.log("No se pudo mejorar nada")
        return ok

    def _free_builders(self) -> int:
        fn = getattr(self.game, "free_slots", None)
        if not fn:
            return 0
        try:
            return int(fn().get("builders") or 0)
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"No pude leer los constructores: {e}")
            return 0

    def spend_free_slots(self) -> None:
        """Before every attack (the first one too). Busy mode: use every free builder / researcher / pet, so the
        counters are at 0, unless the price cannot be paid (the routine drains every tab by itself). Walls mode:
        keep exactly one builder free (the surplus goes to the cheapest permanent upgrades) and run the walls
        while that builder is free."""
        if self.dry_run or self.cfg.mode == "none":
            return
        if self.cfg.mode == "busy":
            self._spend()
            return
        builders = self._free_builders()
        if builders > 1 and self._spend("surplus"):
            # The routine stops at the reserve, so one builder is free for sure. Right after the menu closes the
            # HUD is still settling and the counter can read blurry: wait, look again, and trust the reserve.
            self.sleep(STORAGE_SETTLE)
            builders = max(self._free_builders(), 1)
        for _ in range(MAX_SPEND_ROUNDS):
            if builders < 1 or not self._spend():
                return
            builders = self._free_builders()

    def wait_if_full(self) -> None:
        """No attacks while gold and elixir are full; in a mode, spend a free slot meanwhile."""
        if self.dry_run or not (self.cfg.stop_when_full or self.cfg.mode != "none"):
            return
        self._reload_if_disconnected()
        announced = False
        while self._storages_full():
            self._reload_if_disconnected()
            self._check()
            if not announced:
                self.log("Depositos llenos: espero")
                announced = True
            if self.cfg.mode == "busy" or (self.cfg.mode != "none" and self._slot_free()):
                if not self._spend():
                    self._nap(FAIL_WAIT_S)
                continue
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
                self._reload_if_disconnected()
                if not self.dry_run:
                    self._close_leftover_menu()      # so the storage bars are readable
                self.spend_free_slots()              # counters to 0 before attacking (the first attack too)
                if not self.dry_run:
                    self._close_leftover_menu()      # a menu left open would hide the storage bars
                self.wait_if_full()                  # then, if the storages are still full, wait for room
            except (_Abort, WindowNotFound, WindowMinimized) as e:
                self.log(str(e))
                break
            if not self.run_once():
                break
