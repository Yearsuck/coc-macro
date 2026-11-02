import threading

from cocmacro import config
from cocmacro.bot import Bot
from cocmacro.winctl import WindowNotFound

LOW = (100_000, 100_000)
GOOD = (600_000, 700_000)


class FakeGame:
    def __init__(self, reads, damages=(), results_early=False, never_scout=False, boom=False, times=()):
        self.reads, self.damages, self.times = list(reads), list(damages), list(times)
        self.results_early, self.never_scout, self.boom = results_early, never_scout, boom
        self.screen, self.clicks, self.deployed, self.dumped = "home", [], 0, []

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
            self.screen = "home"

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
