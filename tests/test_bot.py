import threading

import pytest

from cocmacro import config
from cocmacro.bot import Bot, RELOAD_WAIT_S, _Abort, _Stuck
from cocmacro.winctl import WindowNotFound

LOW = (100_000, 100_000)
GOOD = (600_000, 700_000)


class FakeGame:
    def __init__(self, reads, damages=(), results_early=False, never_scout=False, boom=False, times=(), popup=False,
                 next_stuck=0):
        self.reads, self.damages, self.times = list(reads), list(damages), list(times)
        self.results_early, self.never_scout, self.boom = results_early, never_scout, boom
        self.screen, self.clicks, self.deployed, self.dumped = "home", [], 0, []
        self.popup, self.dismissed = popup, 0
        self.next_stuck = next_stuck           # first N presses of "next" have no effect
        self._next_presses = 0
        self._clouds = False                   # True after a working "next" press; clears on next screen_is call

    def screen_is(self, name):
        if self.boom:
            raise WindowNotFound("Ventana de Clash of Clans no encontrada")
        res = (self.screen == name)
        if self._clouds:
            self._clouds = False
            self.screen = "scout"
        return res

    def click_button(self, name):
        self.clicks.append(name)
        if name == "attack":
            self.screen = "menu" if self.never_scout else "scout"
        elif name == "next":
            self._next_presses += 1
            if self._next_presses > self.next_stuck:
                self._clouds = True
                self.screen = "clouds"
        elif name == "surrender":
            self.screen = "confirm"
        elif name == "ok":
            self.screen = "results"
        elif name == "back":
            self.screen = "bonus" if self.popup else "home"
        elif name == "end":
            self.screen = "home"

    def dismiss_popup(self):
        if self.screen != "bonus":
            return False
        self.dismissed += 1
        self.screen = "home"
        return True

    def read_resources(self):
        return self.reads.pop(0)

    def read_damage(self):
        v = self.damages.pop(0)
        if self.results_early and not self.damages:
            self.screen = "results"
        return v

    def read_time_left(self):
        return self.times.pop(0) if self.times else None

    def dump_debug(self, reason):
        self.dumped.append(reason)

    def play_deployment(self):
        self.deployed += 1
        self.screen = "battle"
        return True


def make(game, **kw):
    logs = []
    stop = kw.pop("stop", threading.Event())
    bot = Bot(game, config.Config(), logs.append, stop, sleep=lambda s: None, **kw)
    return bot, logs, stop


def test_full_cycle():
    g = FakeGame([GOOD, GOOD], damages=[30, 60])
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks == ["battle", "find", "attack", "surrender", "ok", "back"]
    assert g.deployed == 1 and bot.attacks_done == 1


def test_skips_until_good_village():
    g = FakeGame([LOW, LOW, (200_000, 900_000), (200_000, 900_000), GOOD, GOOD], damages=[60])
    bot, _, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks.count("next") == 2
    assert g.deployed == 1


def test_none_read_retries_not_next():
    g = FakeGame([(None, None), GOOD, GOOD, GOOD], damages=[60])
    bot, _, _ = make(g)
    assert bot.run_once() is True
    assert "next" not in g.clicks


def test_battle_ends_on_its_own():
    g = FakeGame([GOOD, GOOD], damages=[20, 30], results_early=True)
    bot, _, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks == ["battle", "find", "attack", "back"]


def test_timeout_stops():
    g = FakeGame([], never_scout=True)
    bot, logs, _ = make(g, timeout_s=3)
    assert bot.run_once() is False
    assert g.clicks == ["battle", "find", "attack"]
    assert any("tiempo" in m.lower() for m in logs)


def test_stop_event_halts():
    stop = threading.Event()
    stop.set()
    g = FakeGame([GOOD, GOOD], damages=[60])
    bot, _, _ = make(g, stop=stop)
    assert bot.run_once() is False
    assert g.clicks == []
    bot.run()
    assert g.clicks == []


def test_window_lost_stops_cleanly():
    g = FakeGame([], boom=True)
    bot, logs, _ = make(g)
    assert bot.run_once() is False
    assert any("no encontrada" in m for m in logs)


def test_dry_run_never_clicks():
    g = FakeGame([GOOD, GOOD])
    bot, logs, _ = make(g, dry_run=True)
    assert bot.run_once() is True
    assert g.clicks == [] and g.deployed == 0
    assert any("atacaria" in m.lower() for m in logs)


def test_surrenders_when_time_runs_low():
    g = FakeGame([GOOD, GOOD], damages=[10] * 30, times=[170] * 20 + [139] * 10)
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks == ["battle", "find", "attack", "surrender", "ok", "back"]
    assert any("tiempo" in m.lower() for m in logs)


def test_time_rule_disabled_falls_back_to_percent():
    g = FakeGame([GOOD, GOOD], damages=[10, 20, 60], times=[100, 100, 100])
    bot, _, _ = make(g)
    bot.cfg.surrender_time_s = 0
    assert bot.run_once() is True
    assert g.damages == []          # all three damage reads consumed: surrendered on the %


def test_unreadable_timer_is_ignored():
    g = FakeGame([GOOD, GOOD], damages=[10, 60], times=[None, None])
    bot, _, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks[-3:] == ["surrender", "ok", "back"]


def test_long_waits_are_reported_not_silent():
    g = FakeGame([], never_scout=True)
    bot, logs, _ = make(g, timeout_s=25)
    assert bot.run_once() is False
    waiting = [m for m in logs if "esperando" in m.lower() and "aldea enemiga" in m.lower()]
    assert len(waiting) >= 2          # reported at 10 s and 20 s before giving up at 25 s


def test_unreadable_village_is_skipped_not_fatal():
    g = FakeGame([(None, None)] * 4 + [GOOD, GOOD], damages=[60])
    bot, logs, _ = make(g, read_tries=2)
    assert bot.run_once() is True
    assert g.clicks[:4] == ["battle", "find", "attack", "next"]
    assert g.deployed == 1
    assert len(g.dumped) == 1                       # kept a capture of what it could not read
    assert any("salto" in m.lower() for m in logs)


def test_gives_up_after_several_unreadable_villages_in_a_row():
    g = FakeGame([(None, None)] * 20)
    bot, logs, _ = make(g, read_tries=1, unreadable_limit=3)
    assert bot.run_once() is False
    assert g.clicks.count("next") == 2 and g.deployed == 0
    assert any("no se pudo leer" in m.lower() for m in logs)


def test_a_good_read_resets_the_unreadable_streak():
    g = FakeGame([(None, None)] * 2 + [LOW, LOW] + [(None, None)] * 2 + [GOOD, GOOD], damages=[60])
    bot, _, _ = make(g, read_tries=1, unreadable_limit=2)
    assert bot.run_once() is True
    assert g.clicks.count("next") == 3 and g.deployed == 1


def test_dry_run_reports_unreadable_without_failing():
    g = FakeGame([(None, None)] * 4)
    bot, logs, _ = make(g, dry_run=True, read_tries=2)
    assert bot.run_once() is True
    assert any("no se pudo leer" in m.lower() for m in logs)


def test_phases_and_readings_are_reported_for_the_ui():
    g = FakeGame([LOW, LOW, GOOD, GOOD], damages=[30, 60], times=[170, 160])
    phases, readings = [], []
    bot, _, _ = make(g, on_phase=phases.append, on_reading=lambda r: readings.append(dict(r)))
    assert bot.run_once() is True
    assert phases == ["search", "evaluate", "evaluate", "deploy", "watch", "watch", "surrender", "back"]
    first = next(r for r in readings if r.get("gold") is not None)        # a reset to None comes first
    assert (first["gold"], first["elixir"], first["verdict"]) == (100_000, 100_000, "skip")
    assert any(r.get("gold") == 600_000 and r.get("verdict") == "attack" for r in readings)
    last = readings[-1]
    assert last["damage"] == 60 and last["time_left"] == 160


def test_callbacks_are_optional_and_never_break_the_run():
    g = FakeGame([GOOD, GOOD], damages=[60])

    def boom(_):
        raise RuntimeError("ui exploded")
    bot, _, _ = make(g, on_phase=boom, on_reading=boom)
    assert bot.run_once() is True


def test_unreadable_damage_is_logged_and_dumped_once():
    g = FakeGame([GOOD, GOOD], damages=[None] * 45 + [60])
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.dumped == ["damage"]
    assert sum("daño" in m.lower() for m in logs) == 1


def test_waiting_message_says_why_the_screen_is_not_recognised():
    g = FakeGame([], never_scout=True)
    g.why_not = lambda name: f"{name} 0.31 de 0.85"
    bot, logs, _ = make(g, timeout_s=11)
    bot.run_once()
    assert any("Sigo esperando: aldea enemiga" in m and "scout 0.31 de 0.85" in m for m in logs)


def test_star_bonus_popup_after_victory_is_dismissed():
    g = FakeGame([GOOD, GOOD], damages=[30, 60], popup=True)
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.dismissed == 1
    assert any("aviso" in m for m in logs)


class ReloadGame(FakeGame):
    """FakeGame with the optional reload_if_disconnected method for inactivity dialogs."""

    def __init__(self, reloads=(True, False), home_after=2, **kw):
        super().__init__(kw.pop("reads", [GOOD, GOOD]), **kw)
        self.reloads = list(reloads)
        self.reload_calls = 0
        self.home_after = home_after
        self.home_polls = 0
        self.screen = "disconnected" if home_after > 0 else "home"

    def reload_if_disconnected(self):
        self.reload_calls += 1
        pressed = self.reloads.pop(0) if self.reloads else False
        if pressed:
            self.clicks.append("reload_inactive")      # only a real press counts as a click
        return pressed

    def screen_is(self, name):
        if name == "home":
            self.home_polls += 1
            if self.home_polls > self.home_after:
                self.screen = "home"
        return super().screen_is(name)


def test_reload_if_disconnected_reloads_and_waits_for_home():
    g = ReloadGame(reloads=[True, False], home_after=2)
    bot, logs, _ = make(g)
    assert bot._reload_if_disconnected() is True
    assert g.reload_calls == 1
    assert g.clicks == ["reload_inactive"]
    assert any("recarga" in m.lower() for m in logs)


def test_reload_if_disconnected_false_when_not_disconnected_or_method_missing():
    # Game lacks the method
    g_lacks = FakeGame([])
    bot_lacks, logs_lacks, _ = make(g_lacks)
    assert bot_lacks._reload_if_disconnected() is False
    assert logs_lacks == []

    # Game has method but returns False
    g_false = ReloadGame(reloads=[False])
    bot_false, logs_false, _ = make(g_false)
    assert bot_false._reload_if_disconnected() is False
    assert g_false.reload_calls == 1
    assert logs_false == []


def test_reload_if_disconnected_dry_run_never_calls_game():
    g = ReloadGame(reloads=[True])
    bot, logs, _ = make(g, dry_run=True)
    assert bot._reload_if_disconnected() is False
    assert g.reload_calls == 0
    assert g.clicks == []
    assert logs == []


class DialogReloadGame(ReloadGame):
    """The inactivity dialog stays up for `dialog_polls` looks; the village is visible behind it all the time."""

    def __init__(self, dialog_polls, **kw):
        super().__init__(**kw)
        self.dialog_polls, self.dialog_calls = dialog_polls, 0
        self.screen = "home"

    def inactivity_dialog(self):
        self.dialog_calls += 1
        return self.dialog_calls <= self.dialog_polls


def test_reload_waits_for_the_dialog_to_go_away_before_trusting_home():
    g = DialogReloadGame(3, reloads=[True], home_after=0)
    bot, logs, _ = make(g)
    assert bot._reload_if_disconnected() is True
    assert g.dialog_calls == 4 and g.reload_calls == 1          # 3 looks with the dialog, then it is gone


def test_reload_presses_again_when_the_dialog_stays_and_gives_up_after_the_tries():
    from cocmacro.bot import RELOAD_TRIES
    g = DialogReloadGame(10 ** 6, reloads=[True] * 10, home_after=0)
    bot, logs, _ = make(g)
    with pytest.raises(_Stuck, match="aviso sigue"):
        bot._reload_if_disconnected()
    assert g.reload_calls == RELOAD_TRIES                       # the first press plus the retries
    assert sum("pulso otra vez" in m for m in logs) == RELOAD_TRIES - 1


def test_reload_if_disconnected_never_home_aborts():
    g = ReloadGame(reloads=[True], home_after=999999)
    slept = []
    bot, logs, _ = make(g)
    bot.sleep = slept.append

    with pytest.raises(_Stuck, match="La aldea no cargo tras recargar"):
        bot._reload_if_disconnected()
    assert sum(slept) >= RELOAD_WAIT_S
    assert any("recarga" in m.lower() for m in logs)


def test_wait_if_full_reloads_at_start_and_each_iteration():
    class FullReloadGame(ReloadGame):
        def __init__(self):
            super().__init__(reloads=[True, False, False, False], home_after=0)
            self.full_polls = 0

        def storages_full(self):
            self.full_polls += 1
            return self.full_polls <= 2

    g = FullReloadGame()
    bot, logs, _ = make(g)
    bot.cfg.stop_when_full = True
    bot.wait_if_full()

    # one look before the loop + one per iteration (_storages_full reads the bars twice to decide, so one iteration)
    assert g.reload_calls == 2
    # Only the reload press was sent, no upgrade or attack clicks
    assert g.clicks == ["reload_inactive"]


def test_run_reloads_at_top_of_iteration():
    g = ReloadGame(reloads=[True, False], home_after=0)
    bot, logs, stop = make(g)

    calls = []
    orig_reload = g.reload_if_disconnected
    def reload_and_record():
        res = orig_reload()
        calls.append("reloaded")
        return res
    g.reload_if_disconnected = reload_and_record
    g.close_menu = lambda: (calls.append("close_menu") or stop.set() or False)

    bot.run()
    assert calls[:2] == ["reloaded", "close_menu"]
    assert g.reload_calls >= 1
    assert "reload_inactive" in g.clicks
    assert any("recarga" in m.lower() for m in logs)


def test_open_search_reloads_on_retry_and_retries_clicks():
    class SearchReloadGame(FakeGame):
        def __init__(self):
            super().__init__(reads=[GOOD, GOOD], damages=[60])
            self.reload_called = 0
            self.dialog_up = False

        def click_button(self, name):
            super().click_button(name)
            if name == "attack" and "reload_inactive" not in self.clicks:
                self.dialog_up = True
                self.screen = "disconnected"

        def reload_if_disconnected(self):
            self.reload_called += 1
            if self.dialog_up:
                self.dialog_up = False
                self.clicks.append("reload_inactive")
                self.screen = "home"
                return True
            return False

        def screen_is(self, name):
            if self.dialog_up and name == "scout":
                return False
            if not self.dialog_up and self.reload_called > 0 and name == "scout":
                if self.clicks.count("attack") >= 2:
                    return True
            return super().screen_is(name)

    g = SearchReloadGame()
    bot, logs, _ = make(g)
    bot._open_search()

    assert g.reload_called >= 1
    assert "reload_inactive" in g.clicks
    assert g.clicks == ["battle", "find", "attack", "reload_inactive", "battle", "find", "attack"]
    assert any("repito batalla" in m.lower() for m in logs)


def test_reload_if_disconnected_catches_generic_exception():
    g = ReloadGame()
    def explode():
        raise RuntimeError("boom")
    g.reload_if_disconnected = explode
    bot, logs, _ = make(g)
    assert bot._reload_if_disconnected() is False
    assert any("no pude comprobar la sesion: boom" in m.lower() for m in logs)


def test_reload_if_disconnected_reraises_window_exceptions():
    g = ReloadGame()
    def boom():
        raise WindowNotFound("perdida")
    g.reload_if_disconnected = boom
    bot, logs, _ = make(g)
    with pytest.raises(WindowNotFound):
        bot._reload_if_disconnected()


def test_reload_if_disconnected_aborts_if_stopped():
    g = ReloadGame(reloads=[True], home_after=10)
    stop = threading.Event()
    bot, logs, _ = make(g, stop=stop)
    stop.set()
    with pytest.raises(_Abort, match="Detenido"):
        bot._reload_if_disconnected()


def test_no_reload_press_in_dry_run_full_cycle():
    g = ReloadGame(reloads=[True])
    bot, logs, _ = make(g, dry_run=True)
    assert bot.run_once() is True
    assert g.reload_calls == 0
    assert "reload_inactive" not in g.clicks


class LostPressGame(FakeGame):
    """The first `lose` presses of Rendirse are ignored (the game was busy)."""

    def __init__(self, lose=1, **kw):
        super().__init__(**kw)
        self.lose, self.surrenders = lose, 0

    def click_button(self, name):
        if name == "surrender":
            self.surrenders += 1
            self.clicks.append(name)
            if self.surrenders > self.lose:
                self.screen = "confirm"
            return
        super().click_button(name)


def test_a_lost_press_of_rendirse_is_pressed_again():
    g = LostPressGame(lose=1, reads=[GOOD, GOOD], damages=[60])
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.surrenders == 2 and g.clicks[-3:] == ["surrender", "ok", "back"]
    assert any("pulso Rendirse otra vez" in m for m in logs)


def test_the_surrender_gives_up_after_the_tries():
    from cocmacro.bot import SURRENDER_TRIES
    g = LostPressGame(lose=99, reads=[GOOD, GOOD], damages=[60])
    bot, logs, _ = make(g)
    assert bot.run_once() is False
    assert g.surrenders == SURRENDER_TRIES
    assert any("confirmar rendicion" in m for m in logs)


def test_if_the_battle_ends_while_surrendering_the_bot_just_goes_back():
    g = LostPressGame(lose=99, reads=[GOOD, GOOD], damages=[60])
    real = g.screen_is
    polls = []

    def screen_is(name):
        polls.append(name)
        if name == "results" and polls.count("results") > 3:       # the battle runs out during the confirmation wait
            g.screen = "results"
        return real(name)
    g.screen_is = screen_is
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks[-1] == "back" and g.surrenders == 1


def test_the_clock_rule_waits_for_the_end_of_the_deployment_plus_a_grace_time():
    from cocmacro.bot import TIME_RULE_GRACE_POLLS
    g = FakeGame([GOOD, GOOD], damages=[10] * 60, times=[100] * 60)       # clock already below the rule at the start
    bot, _, _ = make(g)
    assert bot.run_once() is True
    consumed = 60 - len(g.times)
    assert consumed >= TIME_RULE_GRACE_POLLS                             # it did not surrender on the first look
    assert g.clicks[-3:] == ["surrender", "ok", "back"]


def test_the_percent_rule_is_not_delayed_by_the_grace_time():
    g = FakeGame([GOOD, GOOD], damages=[60], times=[100])
    bot, _, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks[-3:] == ["surrender", "ok", "back"] and g.damages == []


def test_a_bot_that_starts_on_the_results_screen_presses_volver():
    g = FakeGame([GOOD, GOOD], damages=[60])
    g.screen = "results"
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks[0] == "back" and g.clicks.count("back") >= 2         # first press at once, then the new attack
    assert any("pantalla de resultados" in m for m in logs)


def test_volver_is_not_double_pressed_right_after_the_normal_press():
    g = FakeGame([GOOD, GOOD], damages=[60])
    bot, _, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks.count("back") == 1                                   # the wait for the village did not press it again


def test_volver_is_pressed_again_if_the_first_press_is_lost():
    class StubbornResults(FakeGame):
        def __init__(self):
            super().__init__([])
            self.screen, self.backs = "results", 0

        def click_button(self, name):
            self.clicks.append(name)
            if name == "back":
                self.backs += 1
                if self.backs >= 3:
                    self.screen = "home"
    g = StubbornResults()
    bot, _, _ = make(g, timeout_s=60)
    bot._wait(lambda: g.screen_is("home"), "pantalla de inicio", "home", popups=True, results=True)
    assert g.backs == 3


# --- Part 2 and Part 3 Must-Pass Tests ---

def test_next_press_does_nothing_once_retried():
    # A 'next' press that does nothing once -> pressed again, cycle goes on and attacks good village;
    # g.clicks.count("next") == 2 for one skipped village.
    g = FakeGame([LOW, LOW, GOOD, GOOD], damages=[60], next_stuck=1)
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks.count("next") == 2
    assert g.deployed == 1
    assert any("Siguiente no hizo efecto: pulso otra vez" in m for m in logs)


def test_next_press_three_times_stuck():
    # Three 'next' presses with no effect -> _Stuck (through run_once(): returns False, message logged).
    g = FakeGame([LOW, LOW, GOOD, GOOD], damages=[60], next_stuck=3)
    bot, logs, _ = make(g)
    assert bot.run_once() is False
    assert g.clicks.count("next") == 3
    assert any("no hizo efecto tras 3 intentos" in m for m in logs)


def test_unreadable_loot_gives_up_after_max_read_tries():
    # Unreadable loot gives up after MAX_READ_TRIES (4) attempts: count read_resources calls.
    from cocmacro.bot import MAX_READ_TRIES, _Unreadable
    read_calls = 0

    class CountingGame(FakeGame):
        def read_resources(self):
            nonlocal read_calls
            read_calls += 1
            return (None, None)

    g = CountingGame([], damages=[60])
    bot, logs, _ = make(g)
    with pytest.raises(_Unreadable):
        bot._stable_read()
    # Each attempt in _stable_read reads twice (a and b)
    assert read_calls == 8        # 4 tries x 2 reads: about 3 s of the 30 s countdown


def test_battle_started_by_itself_recovers():
    # Battle started by itself while waiting for the scout screen -> end clicked,
    # search opened again (battle, find, attack clicked a second time), then normal attack; attacks_done == 1.
    class SelfStartGame(FakeGame):
        def __init__(self):
            super().__init__([GOOD, GOOD], damages=[60])
            self.scout_waits = 0

        def screen_is(self, name):
            if name == "scout" and self.scout_waits == 0:
                self.scout_waits += 1
                self.screen = "battle"     # countdown ended: battle started by itself
                return False
            return super().screen_is(name)

    g = SelfStartGame()
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert "end" in g.clicks
    assert g.clicks.count("battle") == 2
    assert g.clicks.count("find") == 2
    assert g.clicks.count("attack") == 2
    assert bot.attacks_done == 1
    assert any("la batalla empezo sola" in m for m in logs)


def test_six_self_started_battles_in_a_row_stuck():
    # Six self-started battles in a row -> _Stuck.
    class AlwaysBattleGame(FakeGame):
        def screen_is(self, name):
            if name == "scout":
                self.screen = "battle"
                return False
            return super().screen_is(name)

    g = AlwaysBattleGame([GOOD, GOOD])
    bot, logs, _ = make(g)
    assert bot.run_once() is False
    assert g.clicks.count("end") == 5     # 5 self-starts handled, on 6th raises _Stuck
    assert any("veces en una misma busqueda" in m for m in logs)


def test_run_timeout_recovers_and_later_attack_completes():
    # run(): a timeout waiting for the scout screen -> _recover runs (dump "stuck" recorded),
    # the loop continues and a later attack completes; the run does NOT end.
    class TimeoutOnceGame(FakeGame):
        def __init__(self, stop):
            super().__init__([GOOD, GOOD], damages=[60])
            self.stop = stop
            self.failed = False

        def screen_is(self, name):
            if name == "scout" and not self.failed:
                return False
            return super().screen_is(name)

        def dump_debug(self, reason):
            super().dump_debug(reason)
            if reason == "stuck":
                self.failed = True
                self.screen = "home"

        def play_deployment(self):
            res = super().play_deployment()
            return res

    stop = threading.Event()
    g = TimeoutOnceGame(stop)
    bot, logs, _ = make(g, stop=stop, timeout_s=2)
    bot.log = lambda m: (logs.append(m), 'completado' in m and stop.set())   # end the run after one whole attack
    bot.run()
    assert "stuck" in g.dumped
    assert any("Intento recuperar" in m for m in logs)
    assert bot.attacks_done == 1


def test_run_recoveries_in_a_row_pause_increases_and_resets():
    # run(): recoveries in a row pause 30, 60, 90 ... capped at 300 s; finished attack resets count.
    naps = []

    class FlakyBot(Bot):
        def _recover(self, reason):
            pass

        def _nap(self, seconds):
            naps.append(seconds)

    g = FakeGame([GOOD, GOOD], damages=[60])
    stop = threading.Event()
    bot = FlakyBot(g, config.Config(), lambda m: None, stop, sleep=lambda s: None)

    step = 0
    def fake_inner():
        nonlocal step
        step += 1
        if step in (1, 2, 3):
            raise _Stuck(f"failure {step}")
        if step == 4:
            bot.attacks_done += 1
            return
        if step == 5:
            raise _Stuck("failure after attack")
        stop.set()

    bot._run_inner = fake_inner
    bot.spend_free_slots = lambda: None
    bot.wait_if_full = lambda: None
    bot._reload_if_disconnected = lambda: False
    bot._close_leftover_menu = lambda: None

    bot.run()
    assert naps[0] == 30
    assert naps[1] == 60
    assert naps[2] == 90
    assert naps[3] == 30   # reset by the finished attack at step 4


def test_recover_from_each_screen():
    # results -> back
    g1 = FakeGame([])
    g1.screen = "results"
    bot1, _, _ = make(g1)
    bot1._recover("stuck results")
    assert "back" in g1.clicks

    # confirm -> ok
    g2 = FakeGame([])
    g2.screen = "confirm"
    bot2, _, _ = make(g2)
    bot2._recover("stuck confirm")
    assert "ok" in g2.clicks

    # scout -> end
    g3 = FakeGame([])
    g3.screen = "scout"
    bot3, _, _ = make(g3)
    bot3._recover("stuck scout")
    assert "end" in g3.clicks

    # battle -> end then ok
    class BattleRecoverGame(FakeGame):
        def __init__(self):
            super().__init__([])
            self.screen = "battle"

        def click_button(self, name):
            super().click_button(name)
            if name == "end":
                self.screen = "confirm"
            elif name == "ok":
                self.screen = "home"

    g4 = BattleRecoverGame()
    bot4, _, _ = make(g4)
    bot4._recover("stuck battle")
    assert g4.clicks == ["end", "ok"]

    # popup -> dismissed
    g5 = FakeGame([])
    g5.screen = "bonus"
    bot5, _, _ = make(g5)
    bot5._recover("stuck popup")
    assert g5.dismissed == 1

    # open menu -> closed
    g6 = FakeGame([])
    g6.screen = "menu"
    closed = []
    def close():
        if g6.screen == "menu":
            closed.append(1)
            g6.screen = "home"
            return True
        return False
    g6.close_menu = close
    bot6, _, _ = make(g6)
    bot6._recover("stuck menu")
    assert len(closed) == 1

    # unknown screen that becomes home later -> waits
    polls = 0
    class DelayedHome(FakeGame):
        def screen_is(self, name):
            nonlocal polls
            polls += 1
            if polls >= 3 and name == "home":
                return True
            return False

    g7 = DelayedHome([])
    bot7, _, _ = make(g7)
    bot7._recover("stuck unknown")
    assert polls >= 3


def test_recover_never_raises_stuck_even_if_never_home():
    class NeverHome(FakeGame):
        def screen_is(self, name):
            return False

    g = NeverHome([])
    bot, logs, _ = make(g)
    bot._recover("lost in void")
    assert any("Intento recuperar" in m for m in logs)


def test_recover_f8_aborts():
    stop = threading.Event()
    g = FakeGame([])
    g.screen = "unknown"
    bot, _, _ = make(g, stop=stop)
    stop.set()
    with pytest.raises(_Abort, match="Detenido"):
        bot._recover("aborted")


def test_run_window_not_found_ends_no_recovery():
    g = FakeGame([], boom=True)
    bot, logs, _ = make(g)
    bot.run()
    assert "stuck" not in g.dumped
    assert any("no encontrada" in m for m in logs)


def test_dialog_pressed_during_wait_raises_stuck_and_recovered_by_run():
    class DialogWaitGame(FakeGame):
        def __init__(self, stop):
            super().__init__([GOOD, GOOD], damages=[60])
            self.stop = stop
            self.scout_checks = 0
            self.wait_polls = 0
            self.reloaded = False

        def screen_is(self, name):
            if name == "scout":
                self.scout_checks += 1
                if self.scout_checks == 1:
                    return True               # satisfies _open_search
                if not self.reloaded:
                    self.wait_polls += 1
                    return False              # holds _wait until reload
            return super().screen_is(name)

        def reload_if_disconnected(self):
            if self.wait_polls >= 10 and not self.reloaded:
                self.reloaded = True
                self.screen = "home"
                return True
            return False

        def play_deployment(self):
            res = super().play_deployment()
            return res

    stop = threading.Event()
    g = DialogWaitGame(stop)
    bot, logs, _ = make(g, stop=stop)
    bot.log = lambda m: (logs.append(m), 'completado' in m and stop.set())   # end the run after one whole attack
    bot.run()
    assert any("se recargo en mitad de un paso" in m for m in logs)
    assert any("Intento recuperar" in m for m in logs)
    assert bot.attacks_done == 1


def test_dry_run_no_recovery_no_clicks():
    class FailingDryGame(FakeGame):
        def read_resources(self):
            raise _Stuck("dry run stuck")

    g = FailingDryGame([])
    bot, logs, _ = make(g, dry_run=True)
    bot.run()
    assert g.clicks == []
    assert "stuck" not in g.dumped


def test_recover_never_clicks_when_village_is_already_home():
    g = FakeGame([])
    g.screen = "home"
    bot, _, _ = make(g)
    bot._recover("already home")
    assert g.clicks == []


def test_a_battle_look_alike_for_one_poll_is_not_a_self_started_battle():
    """Review finding: between two villages the screen can show Terminar batalla without Siguiente for a
    moment, the same picture as a battle that started by itself. One look must not end the search."""
    class Blink(FakeGame):
        def __init__(self):
            super().__init__([GOOD, GOOD], damages=[60])
            self.blinks = 1

        def screen_is(self, name):
            if self.screen == "scout" and self.blinks and name in ("scout", "battle"):
                if name == "battle":
                    self.blinks -= 1
                    return True
                return False
            return super().screen_is(name)

    g = Blink()
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert "end" not in g.clicks and g.clicks.count("battle") == 1
    assert not any("empezo sola" in m for m in logs)


def test_an_unexpected_error_is_recovered_from_like_a_stuck_step():
    class Flaky(FakeGame):
        def __init__(self):
            super().__init__([GOOD, GOOD, GOOD, GOOD], damages=[60, 60])
            self.boomed = False

        def read_resources(self):
            if not self.boomed:
                self.boomed = True
                raise RuntimeError("frame grab failed")
            return super().read_resources()

    g = Flaky()
    stop = threading.Event()
    bot, logs, _ = make(g, stop=stop)
    bot.log = lambda m: (logs.append(m), "completado" in m and stop.set())
    bot.run()
    assert any("Error inesperado" in m and "frame grab failed" in m for m in logs)
    assert "stuck" in g.dumped and bot.attacks_done == 1


# --- every timeout must be a _Stuck (recovered), never an _Abort (end of the run) ---

def test_loot_unreadable_too_many_villages_is_stuck_not_the_end():
    g = FakeGame([(None, None)] * 200)
    bot, _, _ = make(g)
    with pytest.raises(_Stuck, match="No se pudo leer oro y elixir"):
        bot._cycle()


def test_a_battle_that_never_ends_is_stuck_not_the_end():
    g = FakeGame([GOOD, GOOD], damages=[10] * 50)
    bot, _, _ = make(g, battle_timeout_s=3)
    with pytest.raises(_Stuck, match="final de la batalla"):
        bot._cycle()


def test_a_surrender_never_confirmed_is_stuck_not_the_end():
    class Deaf(FakeGame):
        def click_button(self, name):
            self.clicks.append(name)                 # Rendirse is pressed but nothing happens

    g = Deaf([])
    g.screen = "battle"
    bot, _, _ = make(g)
    with pytest.raises(_Stuck, match="confirmar rendicion"):
        bot._surrender()


def test_a_search_that_never_starts_is_stuck_not_the_end():
    class Deaf(FakeGame):
        def click_button(self, name):
            self.clicks.append(name)                 # the village stays on screen

    g = Deaf([])
    bot, _, _ = make(g)
    with pytest.raises(_Stuck, match="La busqueda no arranco"):
        bot._open_search()


def test_recover_presses_nothing_on_the_village_even_if_it_also_looks_like_another_screen():
    """The home check comes before every click: a village that also matched the scout or results picture
    must not get Terminar batalla or Volver pressed on it."""
    class Both(FakeGame):
        def screen_is(self, name):
            return name in ("home", "scout", "results", "confirm", "battle")

    g = Both([])
    bot, _, _ = make(g)
    bot._recover("atasco")
    assert g.clicks == []


def test_recover_cancels_a_search_that_does_not_advance():
    """Live: after a lost connection the game stayed on 'No se ha podido atacar esta aldea' with only a
    Volver button; no known screen matched and the recovery just waited."""
    class Clouds(FakeGame):
        def __init__(self):
            super().__init__([])
            self.screen, self.cancelled = "clouds", 0

        def cancel_search(self):
            if self.screen != "clouds":
                return False
            self.cancelled += 1
            self.screen = "home"
            return True

    g = Clouds()
    bot, logs, _ = make(g)
    bot._recover("atasco")
    assert g.cancelled == 1 and g.clicks == []
    assert any("Cancelo una busqueda" in m for m in logs)


def test_a_dialog_in_the_middle_of_a_battle_is_pressed_and_the_run_goes_on():
    class DialogInBattle(FakeGame):
        def __init__(self):
            super().__init__([GOOD, GOOD, GOOD, GOOD], damages=[10] * 40 + [60])
            self.reloads = 0

        def reload_if_disconnected(self):
            if self.screen == "battle" and not self.reloads:
                self.reloads += 1
                self.screen = "home"                 # the game reloads into the village
                self.damages = [60]
                return True
            return False

    g = DialogInBattle()
    stop = threading.Event()
    bot, logs, _ = make(g, stop=stop)
    bot.log = lambda m: (logs.append(m), "completado" in m and stop.set())
    bot.run()
    assert g.reloads == 1 and bot.attacks_done == 1
    assert any("se recargo en mitad de un paso" in m for m in logs)


# ── what the window is told: the phases between attacks and the recoveries ─────

def test_a_recovery_is_announced_and_counted():
    g = FakeGame([])
    g.screen = "results"
    phases = []
    bot, _, _ = make(g, on_phase=phases.append)
    bot._recover("atasco")
    assert phases == ["recover"]


def test_the_run_counts_every_recovery_it_starts():
    class TimeoutTwice(FakeGame):
        def __init__(self):
            super().__init__([GOOD, GOOD], damages=[60])
            self.stucks = 0

        def screen_is(self, name):
            if name == "scout" and self.stucks < 2:
                return False
            return super().screen_is(name)

        def dump_debug(self, reason):
            super().dump_debug(reason)
            if reason == "stuck":
                self.stucks += 1
                self.screen = "home"

    g = TimeoutTwice()
    stop = threading.Event()
    bot, logs, _ = make(g, stop=stop, timeout_s=2)
    bot.log = lambda m: (logs.append(m), "completado" in m and stop.set())
    bot.run()
    assert bot.recoveries_done == 2 and bot.attacks_done == 1
