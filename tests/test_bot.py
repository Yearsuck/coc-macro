import threading

import pytest

from cocmacro import config
from cocmacro.bot import Bot, RELOAD_WAIT_S, _Abort
from cocmacro.winctl import WindowNotFound

LOW = (100_000, 100_000)
GOOD = (600_000, 700_000)


class FakeGame:
    def __init__(self, reads, damages=(), results_early=False, never_scout=False, boom=False, times=(), popup=False):
        self.reads, self.damages, self.times = list(reads), list(damages), list(times)
        self.results_early, self.never_scout, self.boom = results_early, never_scout, boom
        self.screen, self.clicks, self.deployed, self.dumped = "home", [], 0, []
        self.popup, self.dismissed = popup, 0

    def screen_is(self, name):
        if self.boom:
            raise WindowNotFound("Ventana de Clash of Clans no encontrada")
        return self.screen == name

    def click_button(self, name):
        self.clicks.append(name)
        if name == "attack":
            self.screen = "menu" if self.never_scout else "scout"
        elif name == "surrender":
            self.screen = "confirm"
        elif name == "ok":
            self.screen = "results"
        elif name == "back":
            self.screen = "bonus" if self.popup else "home"

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
    g = FakeGame([GOOD, GOOD], damages=[10, 20], times=[170, 139])
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
    assert any("recargo" in m.lower() for m in logs)


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
    with pytest.raises(_Abort, match="aviso sigue"):
        bot._reload_if_disconnected()
    assert g.reload_calls == RELOAD_TRIES                       # the first press plus the retries
    assert sum("pulso otra vez" in m for m in logs) == RELOAD_TRIES - 1


def test_reload_if_disconnected_never_home_aborts():
    g = ReloadGame(reloads=[True], home_after=999999)
    slept = []
    bot, logs, _ = make(g)
    bot.sleep = slept.append

    with pytest.raises(_Abort, match="La aldea no cargo tras recargar"):
        bot._reload_if_disconnected()
    assert sum(slept) >= RELOAD_WAIT_S
    assert any("recargo" in m.lower() for m in logs)


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
    assert any("recargo" in m.lower() for m in logs)


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
