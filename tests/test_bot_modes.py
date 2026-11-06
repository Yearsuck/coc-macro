import threading

from cocmacro import bot as bot_module, config
from cocmacro.bot import Bot
from test_bot import GOOD, FakeGame


class ModeGame(FakeGame):
    """FakeGame plus the optional readings and the upgrade action of the new modes."""

    def __init__(self, full=(), slots=(), upgrade_ok=True, on_poll=None, **kw):
        super().__init__(kw.pop("reads", [GOOD, GOOD]), damages=kw.pop("damages", [60]), **kw)
        self.full, self.slots, self.upgrade_ok = list(full), list(slots), upgrade_ok
        self.upgrades, self.on_poll, self.polls = [], on_poll, 0

    def storages_full(self):
        self.polls += 1
        if self.on_poll:
            self.on_poll(self)
        return self.full.pop(0) if len(self.full) > 1 else (self.full[0] if self.full else None)

    def free_slots(self):
        s = self.slots.pop(0) if len(self.slots) > 1 else (self.slots[0] if self.slots else {})
        return dict(s)

    def upgrade(self, kind, log=None, check=None):
        self.upgrades.append(kind)
        return self.upgrade_ok


def make(game, **cfg):
    logs, stop = [], threading.Event()
    bot = Bot(game, config.Config(**cfg), logs.append, stop, sleep=lambda s: None)
    return bot, logs, stop


def test_no_mode_never_calls_hooks():
    g = ModeGame(full=[True], slots=[{"builders": 3}])
    bot, _, _ = make(g)
    bot.wait_if_full()
    bot.after_attack()
    assert g.polls == 0 and g.upgrades == []


def test_walls_runs_only_when_a_builder_is_free():
    g = ModeGame(slots=[{"builders": 0}, {"builders": 2}])
    bot, _, _ = make(g, mode="walls")
    bot.after_attack()
    assert g.upgrades == []
    bot.after_attack()
    assert g.upgrades == ["walls"]


def test_unreadable_counter_counts_as_none_free():
    g = ModeGame(slots=[{"builders": None, "researchers": None}])
    for mode in ("walls", "busy"):
        bot, _, _ = make(g, mode=mode)
        bot.after_attack()
    assert g.upgrades == []


def test_busy_runs_for_a_free_researcher_but_walls_does_not():
    g = ModeGame(slots=[{"builders": 0, "researchers": 1}])
    walls, _, _ = make(g, mode="walls")
    walls.after_attack()
    assert g.upgrades == []
    busy, _, _ = make(g, mode="busy")
    busy.after_attack()
    assert g.upgrades == ["busy"]


def test_full_storages_idle_without_clicks_in_mode_none():
    def release(game):
        if game.polls >= 3:
            game.full = [False]
    g = ModeGame(full=[True], on_poll=release)
    bot, logs, _ = make(g, stop_when_full=True)
    bot.wait_if_full()
    assert g.clicks == [] and g.upgrades == [] and g.polls >= 3
    assert sum("llenos" in m.lower() for m in logs) == 1


def test_full_storages_wait_for_a_free_slot_then_upgrade():
    def free_up(game):
        if game.polls >= 3:
            game.slots = [{"builders": 1}]
        if game.upgrades:
            game.full = [False]
    g = ModeGame(full=[True], slots=[{"builders": 0}], on_poll=free_up)
    bot, _, _ = make(g, mode="walls")
    bot.wait_if_full()
    assert g.upgrades == ["walls"]


def test_failed_upgrade_while_full_pauses_before_retrying():
    slept = []

    def stop_soon(game):
        if game.polls >= 3:
            stop.set()
    g = ModeGame(full=[True], slots=[{"builders": 1}], upgrade_ok=False, on_poll=stop_soon)
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="walls"), logs.append, stop, sleep=slept.append)
    bot.run()
    assert g.upgrades and sum(slept) >= bot_module.FAIL_WAIT_S * (len(g.upgrades) - 1)


def test_hook_failure_does_not_stop_the_bot():
    class Boom(ModeGame):
        def upgrade(self, kind, log=None, check=None):
            raise RuntimeError("ui exploded")
    g = Boom(slots=[{"builders": 1}])
    bot, logs, _ = make(g, mode="walls")
    bot.after_attack()
    assert any("ui exploded" in m for m in logs)


def test_dry_run_never_upgrades():
    g = ModeGame(full=[True], slots=[{"builders": 1}])
    bot, _, _ = make(g, mode="walls")
    bot.dry_run = True
    bot.wait_if_full()
    bot.after_attack()
    assert g.upgrades == [] and g.polls == 0


def test_run_upgrades_after_each_attack():
    g = ModeGame(slots=[{"builders": 1}])
    bot, _, stop = make(g, mode="walls")
    real = bot.after_attack

    def once():
        real()
        stop.set()
    bot.after_attack = once
    bot.run()
    assert g.deployed == 1 and g.upgrades == ["walls"]


def test_busy_looks_in_the_menu_every_fifth_attack_for_pets():
    g = ModeGame(slots=[{"builders": 0, "researchers": 0}])
    bot, _, _ = make(g, mode="busy")
    for done in (1, 2, 3, 4):
        bot.attacks_done = done
        bot.after_attack()
    assert g.upgrades == []
    bot.attacks_done = 5
    bot.after_attack()
    assert g.upgrades == ["busy"]


def test_unreadable_game_state_never_takes_the_bot_down():
    class Flaky(ModeGame):
        def storages_full(self):
            raise ValueError("bad frame")

        def free_slots(self):
            raise ValueError("bad frame")
    g = Flaky()
    bot, logs, _ = make(g, mode="walls", stop_when_full=True)
    bot.wait_if_full()
    bot.after_attack()
    assert g.upgrades == [] and sum("No pude leer" in m for m in logs) == 2


def test_busy_mode_waits_by_spending_even_with_no_village_slot_free():
    def release(game):
        if game.upgrades:
            game.full = [False]
    g = ModeGame(full=[True], slots=[{"builders": 0, "researchers": 0}], on_poll=release)
    bot, _, _ = make(g, mode="busy")
    bot.wait_if_full()
    assert g.upgrades == ["busy"]


def test_unreadable_storages_count_as_not_full_and_do_not_wait():
    g = ModeGame(full=[None])
    bot, logs, _ = make(g, stop_when_full=True)
    bot.wait_if_full()
    assert g.polls == 1 and not any("llenos" in m.lower() for m in logs)


def test_losing_the_window_during_an_upgrade_stops_the_run_cleanly():
    from cocmacro.winctl import WindowNotFound

    class Lost(ModeGame):
        def upgrade(self, kind, log=None, check=None):
            raise WindowNotFound("ventana perdida")
    g = Lost(slots=[{"builders": 1}])
    bot, logs, _ = make(g, mode="walls")
    bot.run()
    assert any("ventana perdida" in m for m in logs) and g.deployed == 1


def test_a_failed_attack_never_triggers_the_upgrade_hook():
    g = ModeGame(slots=[{"builders": 1}], never_scout=True)
    bot, _, _ = make(g, mode="walls")
    bot.timeout_s = 3
    bot.run()
    assert g.upgrades == [] and bot.attacks_done == 0


def test_the_upgrade_phase_is_announced_to_the_window():
    phases = []
    g = ModeGame(slots=[{"builders": 1}])
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="walls"), logs.append, stop, sleep=lambda s: None, on_phase=phases.append)
    bot.after_attack()
    assert phases == ["upgrade"]
