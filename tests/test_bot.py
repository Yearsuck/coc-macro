import threading

from cocmacro import config
from cocmacro.bot import Bot
from cocmacro.winctl import WindowNotFound

LOW = (100_000, 100_000)
GOOD = (600_000, 700_000)


class FakeGame:
    def __init__(self, reads, damages=(), results_early=False, never_scout=False, boom=False):
        self.reads, self.damages = list(reads), list(damages)
        self.results_early, self.never_scout, self.boom = results_early, never_scout, boom
        self.screen, self.clicks, self.deployed = "home", [], 0

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
