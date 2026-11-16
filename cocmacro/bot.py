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
MAX_READ_TRIES = 4
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
NEXT_GONE_S = 3           # seconds to wait for "Siguiente" to disappear after pressing it
NEXT_TRIES = 3            # presses of "Siguiente" before giving up
DIALOG_EVERY_S = 5        # seconds between dialog checks inside _wait and the battle loop
BUILDER_BLIND_LIMIT = 6   # looks in a row at an unreadable builder counter before walls mode stops waiting
SELF_START_LIMIT = 5      # max battles started by themselves (scout countdown) in one _cycle
RECOVER_STEPS = 20        # rounds of recovery before giving up
RECOVER_IDLE_S = 5        # seconds to wait on an unrecognised screen during recovery
RECOVER_PAUSE_S = 30      # base pause between recovery attempts
RECOVER_PAUSE_MAX_S = 300 # maximum pause between recovery attempts


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


class _Stuck(Exception):
    pass


class _Unreadable(Exception):
    pass


class _BailOut(Exception):
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
        self.recoveries_done = 0     # recoveries started in this run (never reset: the window shows the total)
        self._last_stuck = None

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
        """Reload dialog (inactivity or native): press and wait for the village to return. True if pressed."""
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
        self.log("Aviso de recarga: pulso y espero la aldea")
        # The village is visible behind the dialog, so "home" alone proves nothing: first the dialog must go.
        # If it stays the press was not taken: press again.
        still_up = getattr(self.game, "any_dialog", None) or getattr(self.game, "inactivity_dialog", None)
        if still_up:
            for attempt in range(RELOAD_TRIES):
                for _ in range(max(1, int(RELOAD_PRESS_WAIT_S / POLL))):
                    self._check()
                    if not still_up():
                        break
                    self.sleep(POLL)
                else:
                    if attempt + 1 >= RELOAD_TRIES:
                        raise _Stuck("La sesion no se recargo: el aviso sigue ahi")
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
            raise _Stuck("La aldea no cargo tras recargar")
        self._nap(RELOAD_SETTLE_S)
        return True

    def _wait(self, pred: Callable[[], bool], what: str, screen: str | None = None,
              popups: bool = False, results: bool = False,
              bail: Callable[[], bool] | None = None) -> None:
        """Wait for `pred`. `popups` also closes a 'Vale' notice; `results` also presses Volver again every
        BACK_EVERY_S while the results screen is up (the caller pressed it once already, or the first press was
        lost, and the bot would wait for the village forever). Never at the first look: that would double-press.
        `bail` is looked at each poll: true on two polls in a row raises `_BailOut` so the caller can start
        over (one look is not enough: a transition between screens can show the same thing for a moment)."""
        bail_hits = 0
        dialog_polls = max(1, int(DIALOG_EVERY_S / POLL))
        for i in range(max(1, int(self.timeout_s / POLL))):
            self._check()
            if pred():
                return
            bail_hits = bail_hits + 1 if bail and bail() else 0
            if bail_hits >= 2:
                raise _BailOut()
            if popups:
                self._dismiss_popup()
            if results and i and i % max(1, int(BACK_EVERY_S / POLL)) == 0 and self.game.screen_is("results"):
                self.log("Estoy en la pantalla de resultados: pulso Volver")
                self._click("back")
            if not self.dry_run and i and i % dialog_polls == 0:
                if self._reload_if_disconnected():
                    raise _Stuck("El juego se recargo en mitad de un paso")
            if i and i % REPORT_EVERY == 0:
                self.log(f"Sigo esperando: {what} ({i * POLL:.0f}s){self._why(screen)}")
            self.sleep(POLL)
        raise _Stuck(f"Tiempo agotado esperando: {what}")

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

    def _next_village(self) -> None:
        """Press 'Siguiente' and verify the button went away (F1). If the press had no effect, press again
        (up to NEXT_TRIES times). Raises _Stuck after NEXT_TRIES presses with no effect."""
        for attempt in range(NEXT_TRIES):
            self._click("next")
            for _ in range(max(1, int(NEXT_GONE_S / POLL))):
                self._check()
                if not self.game.screen_is("scout"):
                    return
                self.sleep(POLL)
            if attempt + 1 < NEXT_TRIES:
                self.log("Siguiente no hizo efecto: pulso otra vez")
        raise _Stuck(f"Siguiente no hizo efecto tras {NEXT_TRIES} intentos")

    def _battle_menu_open(self) -> bool:
        """The Batalla menu (the panel with Buscar batalla over the left half of the village) is up. It hides the
        Batalla button, so the village does not look like 'home' while it is open; without this check a lost press of
        Buscar was taken for 'loading a village' and the bot waited for a scout screen that was never coming (live:
        two stuck cycles of four minutes). Optional on the game, like the other checks."""
        fn = getattr(self.game, "battle_menu_open", None)
        if not fn or self.dry_run:
            return False
        try:
            return bool(fn())
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception:
            return False

    def _open_search(self) -> None:
        """Batalla -> Buscar -> Atacar. A notice (star bonus after a win) can appear late and swallow these
        clicks, leaving the village on screen: if after a few seconds it is still the village, press them again
        (at most 3 times). Still loading a village (not the village, not scouting yet) is NOT retried."""
        for attempt in range(SEARCH_TRIES):
            self._reload_if_disconnected()
            for name in ("battle", "find", "attack"):
                if name == "battle" and self._battle_menu_open():
                    continue                  # already open (a lost press left it there): go on from Buscar
                self._click(name)
                self.sleep(self.step_delay)
            noticed = False
            for _ in range(int(SEARCH_RETRY_S / POLL)):
                self._check()
                if self.game.screen_is("scout"):
                    return
                if self._battle_menu_open():
                    noticed = True            # Buscar did not take: the menu is still up, press it again
                    break
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
        raise _Stuck(f"La busqueda no arranco tras {SEARCH_TRIES} intentos: sigo en el pueblo")

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
        self._wait(lambda: self.game.screen_is("home") or self._battle_menu_open(), "pantalla de inicio", "home",
                   popups=True, results=True)
        self._phase("search")
        self_starts = 0
        self._open_search()
        unreadable = 0
        while True:
            # Wait for the scout screen, but bail if a battle started by itself (F2)
            try:
                self._wait(lambda: self.game.screen_is("scout"), "aldea enemiga", "scout",
                           bail=lambda: self.game.screen_is("battle"))
            except _BailOut:
                self_starts += 1
                if self_starts > SELF_START_LIMIT:
                    raise _Stuck(f"La batalla empezo sola {self_starts} veces en una misma busqueda")
                self.log("La cuenta atras termino y la batalla empezo sola: la termino y busco otra")
                self._click("end")
                self._wait(lambda: self.game.screen_is("home"), "volver a la aldea", "home",
                           popups=True, results=True)
                self._open_search()
                continue
            self._phase("evaluate")
            self._reading(gold=None, elixir=None, verdict=None, damage=None, time_left=None)
            try:
                gold, elixir = self._stable_read()
            except _Unreadable:
                unreadable += 1
                self._dump("loot")
                if unreadable >= self.unreadable_limit:
                    raise _Stuck(f"No se pudo leer oro y elixir en {unreadable} aldeas seguidas. "
                                 "Mira las capturas de la carpeta data/debug o recalibra")
                self.log(f"No se pudo leer el botin: salto esta aldea ({unreadable} seguidas)")
                self._next_village()
                continue
            unreadable = 0
            self._reading(gold=gold, elixir=elixir,
                          verdict="attack" if decisions.should_attack(gold, elixir, self.cfg) else "skip")
            if decisions.should_attack(gold, elixir, self.cfg):
                self.log(f"Atacando: oro {gold}, elixir {elixir}")
                break
            self.log(f"Siguiente: oro {gold}, elixir {elixir}")
            self._next_village()
        self._check()
        self._phase("deploy")
        if not self.game.play_deployment():
            raise _Abort("Despliegue interrumpido")
        blind, since_deploy = 0, 0
        grace_polls = TIME_RULE_GRACE_POLLS
        dialog_polls = max(1, int(DIALOG_EVERY_S / POLL))
        for poll_i in range(max(1, int(self.battle_timeout_s / POLL))):
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
            if not self.dry_run and poll_i and poll_i % dialog_polls == 0:
                if self._reload_if_disconnected():
                    raise _Stuck("El juego se recargo en mitad de un paso")
            self.sleep(POLL)
        else:
            raise _Stuck("Tiempo agotado esperando el final de la batalla")
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
        raise _Stuck("Tiempo agotado esperando: confirmar rendicion")

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

    def _any_storage_full(self) -> bool:
        """True when gold OR elixir is full (dark is ignored). Same robustness as _storages_full:
        STORAGE_SETTLE sleep first, up to 4 readings STORAGE_READ_GAP apart, a resource counts as
        full once it was read True twice; stop early as soon as one resource reached two True readings,
        or both gold and elixir reached two False readings."""
        fn = getattr(self.game, "storage_levels", None)
        if not fn:
            return False
        self.sleep(STORAGE_SETTLE)
        gold_full = gold_not = 0
        elixir_full = elixir_not = 0
        try:
            for i in range(4):
                if i:
                    self.sleep(STORAGE_READ_GAP)
                levels = fn()
                g, e = levels.get("gold"), levels.get("elixir")
                if g is True:
                    gold_full += 1
                elif g is False:
                    gold_not += 1
                if e is True:
                    elixir_full += 1
                elif e is False:
                    elixir_not += 1
                if gold_full >= 2 or elixir_full >= 2:
                    return True
                if gold_not >= 2 and elixir_not >= 2:
                    return False
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"No pude leer los depositos: {e}")
            return False
        return gold_full >= 2 or elixir_full >= 2

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

    def _builders_reading(self) -> int | None:
        """Free builders shown by the village counter; None when it cannot be read."""
        fn = getattr(self.game, "free_slots", None)
        if not fn:
            return 0
        try:
            value = fn().get("builders")
            return None if value is None else int(value)
        except (_Abort, WindowNotFound, WindowMinimized):
            raise
        except Exception as e:
            self.log(f"No pude leer los constructores: {e}")
            return None

    def _free_builders(self) -> int:
        return self._builders_reading() or 0

    def spend_free_slots(self) -> None:
        """Before every attack (the first one too). Busy mode: use every free builder / researcher / pet, so the
        counters are at 0, unless the price cannot be paid (the routine drains every tab by itself). Walls mode:
        keep exactly one builder free (the surplus goes to the cheapest permanent upgrades); then, if a storage
        is full, run the wall routine; if no storage is full, skip the walls and attack."""
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
        # Without full storages, save the builder for walls and proceed to attack
        if not self._any_storage_full():
            return
        # A storage is full but no builder is free: attacking would only waste loot, so wait for one. A
        # counter that cannot be read is not "none free": after a few blind looks in a row go on attacking
        # instead of waiting for ever on a number the bot cannot see.
        if builders < 1:
            self._phase("wait_builder")
            self.log("Deposito lleno y sin constructor libre: espero a que quede uno")
            blind = 0
            while builders < 1:
                self._reload_if_disconnected()
                self._nap(FULL_POLL_S)
                reading = self._builders_reading()
                blind = blind + 1 if reading is None else 0
                if blind >= BUILDER_BLIND_LIMIT:
                    self.log("No consigo leer los constructores: sigo atacando")
                    return
                builders = reading or 0
        # Upgrade walls while storages are full and a builder remains free
        for _ in range(MAX_SPEND_ROUNDS):
            if not self._spend("walls"):
                return
            if not self._any_storage_full():
                return
            builders = self._free_builders()
            if builders < 1:
                return

    def wait_if_full(self) -> None:
        """No attacks while gold and elixir are full; in a mode, spend a free slot meanwhile."""
        if self.dry_run or not (self.cfg.stop_when_full or self.cfg.mode != "none"):
            return
        if self.cfg.mode == "walls" and not self.cfg.stop_when_full:
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

    def _recover(self, reason: str) -> None:
        """Try to get back to the village after a _Stuck. Never raises _Stuck itself."""
        self._phase("recover")
        self.log(f"{reason}. Intento recuperar")
        self._dump("stuck")
        for _ in range(RECOVER_STEPS):
            try:
                self._check()
                if self._reload_if_disconnected():
                    continue
                # home is checked before any click so that nothing is pressed on the village
                if self.game.screen_is("home"):
                    self._close_leftover_menu()
                    return
                if self._battle_menu_open():
                    # Nothing to close: the next cycle goes on from Buscar batalla, which is where the bot was heading.
                    self.log("El menu de Batalla esta abierto: sigo desde ahi")
                    return
                if self._dismiss_popup():
                    self._nap(self.step_delay)
                    continue
                fn = getattr(self.game, "close_menu", None)
                if fn and fn():
                    self.log("Cierro un menu o ventana que quedo abierto")
                    self._nap(self.step_delay)
                    continue
                if self.game.screen_is("results"):
                    self._click("back")
                    self._nap(self.step_delay)
                    continue
                if self.game.screen_is("confirm"):
                    self._click("ok")
                    self._nap(self.step_delay)
                    continue
                if self.game.screen_is("scout") or self.game.screen_is("battle"):
                    self._click("end")
                    self._nap(self.step_delay)
                    continue
                cancel = getattr(self.game, "cancel_search", None)
                if cancel and cancel():
                    self.log("Cancelo una busqueda que no avanza")
                    self._nap(self.step_delay)
                    continue
                self._nap(RECOVER_IDLE_S)
            except _Stuck as e:
                self.log(f"Durante la recuperacion: {e}")

    def _run_inner(self) -> None:
        """One attack cycle. Lets _Stuck through (for run() to handle); catches _Abort and window exceptions
        only for the public run_once wrapper."""
        self._cycle()
        if not self.dry_run:
            self.attacks_done += 1
            self.log(f"Ataque {self.attacks_done} completado")

    def run_once(self) -> bool:
        self._last_stuck = None
        try:
            self._run_inner()
            return True
        except _Stuck as e:
            self._last_stuck = e
            self.log(str(e))
            return False
        except (_Abort, WindowNotFound, WindowMinimized) as e:
            self.log(str(e))
            return False
        except Exception as e:           # an unexpected error is one more way of being stuck, not the end
            self._last_stuck = _Stuck(f"Error inesperado: {e!r}")
            self.log(str(self._last_stuck))
            return False

    def run(self) -> None:
        """Attack until stopped. Only F8 / Stop or a lost window end the run: a step that got stuck is
        recovered from (back to the village) and the loop goes on, pausing longer after each recovery in a row
        so a broken screen is not hammered."""
        recoveries = 0
        while not self.stop.is_set():
            stuck: _Stuck | None = None
            try:
                self._reload_if_disconnected()
                if not self.dry_run:
                    self._close_leftover_menu()      # so the storage bars are readable
                if not self._battle_menu_open():     # the panel over the village would make every tap a lottery
                    self.spend_free_slots()          # counters to 0 before attacking (the first attack too)
                    if not self.dry_run:
                        self._close_leftover_menu()  # a menu left open would hide the storage bars
                    self.wait_if_full()              # then, if the storages are still full, wait for room
            except _Stuck as e:
                self.log(str(e))
                stuck = e
            except (_Abort, WindowNotFound, WindowMinimized) as e:
                self.log(str(e))
                break
            except Exception as e:
                stuck = _Stuck(f"Error inesperado: {e!r}")
                self.log(str(stuck))
            if stuck is None:
                if self.stop.is_set():
                    break
                if self.run_once():
                    recoveries = 0
                    continue
                stuck = self._last_stuck
            if stuck is None or self.dry_run:        # stopped for good; a simulation never clicks its way out
                break
            recoveries += 1
            self.recoveries_done += 1
            try:
                self._recover(str(stuck))
                self._nap(min(RECOVER_PAUSE_S * recoveries, RECOVER_PAUSE_MAX_S))
            except (_Abort, WindowNotFound, WindowMinimized) as e:
                self.log(str(e))
                break
