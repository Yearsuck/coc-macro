import threading

import pytest

from cocmacro import bot as bot_module, config
from cocmacro.bot import Bot
from test_bot import GOOD, FakeGame


class ModeGame(FakeGame):
    """FakeGame plus the optional readings and the upgrade action of the new modes."""

    def __init__(self, full=(), slots=(), upgrade_ok=True, on_poll=None, levels=(), **kw):
        super().__init__(kw.pop("reads", [GOOD, GOOD]), damages=kw.pop("damages", [60]), **kw)
        self.full, self.slots, self.upgrade_ok = list(full), list(slots), upgrade_ok
        self.levels = list(levels)
        self.upgrades, self.on_poll, self.polls = [], on_poll, 0
        self.level_polls = 0

    def storages_full(self):
        self.polls += 1
        if self.on_poll:
            self.on_poll(self)
        return self.full.pop(0) if len(self.full) > 1 else (self.full[0] if self.full else None)

    def storage_levels(self):
        self.level_polls += 1
        if self.on_poll:
            self.on_poll(self)
        if self.levels:
            return self.levels.pop(0) if len(self.levels) > 1 else self.levels[0]
        f = self.storages_full()
        return {"gold": f, "elixir": f, "dark": False}

    def free_slots(self):
        if self.on_poll:
            self.on_poll(self)
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
    bot.spend_free_slots()
    assert g.polls == 0 and g.upgrades == []


def test_walls_runs_only_when_storage_full_and_builder_free():
    # Old name: test_walls_runs_only_when_a_builder_is_free
    # Rewritten because walls mode now also requires a storage to be full (Spec 1.3b).
    # Without storage full: 1 builder free -> no upgrade.
    g_not_full = ModeGame(slots=[{"builders": 1}], levels=[{"gold": False, "elixir": False}])
    bot1, _, _ = make(g_not_full, mode="walls")
    bot1.spend_free_slots()
    assert g_not_full.upgrades == []

    # With storage full: 1 builder free -> upgrades walls.
    g_full = ModeGame(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}, {"gold": True, "elixir": False}, {"gold": False, "elixir": False}])
    bot2, _, _ = make(g_full, mode="walls")
    bot2.spend_free_slots()
    assert g_full.upgrades == ["walls"]


def test_unreadable_counter_counts_as_none_free():
    """Walls need a builder: an unreadable village counter means none. (Busy always looks in the menu.)"""
    g = ModeGame(slots=[{"builders": None, "researchers": None}], levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == []


def test_busy_runs_for_a_free_researcher_but_walls_does_not():
    g = ModeGame(slots=[{"builders": 0, "researchers": 1}], levels=[{"gold": False, "elixir": False}])
    walls, _, _ = make(g, mode="walls")
    walls.spend_free_slots()
    assert g.upgrades == []
    busy, _, _ = make(g, mode="busy")
    busy.spend_free_slots()
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


def test_walls_full_storage_waits_for_free_builder_in_spend_free_slots_then_upgrades():
    # Old name: test_full_storages_wait_for_a_free_slot_then_upgrade
    # Rewritten because wait_if_full in walls mode no longer upgrades (owned by spend_free_slots, Spec 1.3/1.4).
    polls = 0
    def free_up(game):
        nonlocal polls
        polls += 1
        if polls >= 3:
            game.slots = [{"builders": 1}]
    g = ModeGame(levels=[{"gold": True, "elixir": False}, {"gold": True, "elixir": False}, {"gold": False, "elixir": False}],
                 slots=[{"builders": 0}], on_poll=free_up)
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls"]


def test_busy_failed_upgrade_while_full_pauses_before_retrying():
    # Old name: test_failed_upgrade_while_full_pauses_before_retrying
    # Rewritten to mode="busy" because walls mode no longer retries/pauses in wait_if_full (Spec 1.3e, 1.4).
    slept = []

    def stop_soon(game):
        if game.polls >= 3:
            stop.set()
    g = ModeGame(full=[True], slots=[{"builders": 1}], upgrade_ok=False, on_poll=stop_soon)
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="busy"), logs.append, stop, sleep=slept.append)
    bot.run()
    assert g.upgrades and sum(slept) >= bot_module.FAIL_WAIT_S * (len(g.upgrades) - 1)


def test_hook_failure_does_not_stop_the_bot():
    class Boom(ModeGame):
        def upgrade(self, kind, log=None, check=None):
            raise RuntimeError("ui exploded")
    g = Boom(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert any("ui exploded" in m for m in logs)


def test_dry_run_never_upgrades():
    g = ModeGame(full=[True], slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.dry_run = True
    bot.wait_if_full()
    bot.spend_free_slots()
    assert g.upgrades == [] and g.polls == 0


def test_unreadable_game_state_never_takes_the_bot_down():
    class Flaky(ModeGame):
        def storages_full(self):
            raise ValueError("bad frame")

        def storage_levels(self):
            raise ValueError("bad frame")

        def free_slots(self):
            raise ValueError("bad frame")
    g = Flaky()
    bot, logs, _ = make(g, mode="walls", stop_when_full=True)
    bot.wait_if_full()
    bot.spend_free_slots()
    assert g.upgrades == [] and sum("No pude leer" in m for m in logs) == 3


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
    assert g.polls == 4 and not any("llenos" in m.lower() for m in logs)      # nothing clear in 4 readings: not full


def test_losing_the_window_during_an_upgrade_stops_the_run_cleanly():
    from cocmacro.winctl import WindowNotFound

    class Lost(ModeGame):
        def upgrade(self, kind, log=None, check=None):
            raise WindowNotFound("ventana perdida")
    g = Lost(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.run()
    assert any("ventana perdida" in m for m in logs) and g.deployed == 0     # the upgrades come before the attack


def test_the_upgrade_phase_is_announced_to_the_window():
    phases = []
    g = ModeGame(slots=[{"builders": 1}, {"builders": 0}], levels=[{"gold": True, "elixir": False}])
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="walls"), logs.append, stop, sleep=lambda s: None, on_phase=phases.append)
    bot.spend_free_slots()
    assert phases == ["upgrade"]


def test_a_menu_left_open_is_closed_before_searching():
    """Starts with the menu covering the village: without closing it the home screen is never seen."""
    class Covered(ModeGame):
        def __init__(self):
            super().__init__()
            self.screen, self.closed = "menu", 0

        def close_menu(self):
            if self.screen != "menu":
                return False
            self.closed += 1
            self.screen = "home"
            return True
    g = Covered()
    bot, logs, _ = make(g)
    bot.timeout_s = 3
    assert bot.run_once() is True
    assert g.closed == 1 and g.clicks[0] == "battle" and any("quedo abierto" in m for m in logs)


def test_close_attempts_are_bounded_when_nothing_closes():
    class Stuck(ModeGame):
        calls = 0

        def close_menu(self):
            self.calls += 1
            return True
    g = Stuck()
    bot, _, _ = make(g)
    bot._close_leftover_menu()
    assert g.calls == 3


def test_a_menu_left_open_is_also_closed_before_checking_the_storages():
    order = []

    class Ordered(ModeGame):
        def close_menu(self):
            order.append("close")
            return False

        def storages_full(self):
            order.append("storages")
            stop.set()
            return False
    g = Ordered()
    bot, _, stop = make(g, mode="walls")
    bot.run()
    assert order[0] == "close" and order[order.index("storages") - 1] == "close"     # closed right before reading


def test_a_game_without_close_menu_runs_as_before():
    g = ModeGame()
    bot, _, _ = make(g)
    assert bot.run_once() is True and g.clicks[0] == "battle"


class SwallowGame(ModeGame):
    """A star-bonus notice swallows the first search clicks: Atacar leaves the village on screen."""

    def __init__(self, swallow=1, **kw):
        super().__init__(**kw)
        self.swallow, self.attacks = swallow, 0

    def click_button(self, name):
        if name == "attack":
            self.attacks += 1
            if self.attacks <= self.swallow:
                self.clicks.append(name)
                return                        # nothing happens: still in the village
        super().click_button(name)


def test_search_is_repeated_when_a_notice_swallowed_the_clicks():
    g = SwallowGame(swallow=1)
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks[:6] == ["battle", "find", "attack"] * 2 and g.deployed == 1
    assert any("repito" in m for m in logs)


def test_search_aborts_with_a_clear_message_after_three_tries_without_waiting_again():
    """Review finding: after 3 failed presses the old code fell into another 60 s wait for the scout screen."""
    g = SwallowGame(swallow=99)
    slept, logs, stop = [], [], threading.Event()
    bot = Bot(g, config.Config(), logs.append, stop, sleep=slept.append)
    assert bot.run_once() is False
    assert g.clicks.count("battle") == 3
    assert any("no arranco tras 3 intentos" in m for m in logs) and not any("Sigo esperando" in m for m in logs)
    assert sum(slept) < 60                       # 3 x (3 presses + 12 s), not 105 s


def test_a_dismissed_notice_means_retry_now_not_after_12_seconds():
    """Review finding: the poll loop kept waiting for the scout screen after the notice had been closed."""
    class Notice(SwallowGame):
        def click_button(self, name):
            if name == "attack" and self.attacks == 0:
                self.attacks += 1
                self.clicks.append(name)
                self.screen = "bonus"              # the notice covers the village and swallows the presses
                return
            super().click_button(name)
    g = Notice(swallow=0)
    slept, logs, stop = [], [], threading.Event()
    bot = Bot(g, config.Config(), logs.append, stop, sleep=slept.append)
    assert bot.run_once() is True
    assert g.dismissed == 1 and g.clicks[:6] == ["battle", "find", "attack"] * 2
    assert sum(slept) < 12                         # it did not sit out the 12 s poll


def test_a_slow_scout_load_is_not_mistaken_for_a_swallowed_click():
    """Not in the village and not yet scouting (loading): the clicks worked, do not press Batalla again."""
    g = ModeGame(never_scout=True)                  # screen becomes 'menu' after Atacar, never 'scout'
    bot, _, _ = make(g)
    bot.timeout_s = 3
    assert bot.run_once() is False
    assert g.clicks == ["battle", "find", "attack"]


def _stop_after_first_attack(bot, stop):
    real = bot.run_once
    bot.run_once = lambda: (real(), stop.set())[0]


def test_busy_spends_before_the_first_attack_not_only_after_one():
    class Order(ModeGame):
        def upgrade(self, kind, log=None, check=None):
            self.at_upgrade = list(self.clicks)
            return super().upgrade(kind, log, check)
    g = Order(slots=[{"builders": 1}])
    bot, _, stop = make(g, mode="busy")
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.at_upgrade == [] and g.upgrades == ["busy"] and g.deployed == 1


def test_busy_always_looks_in_the_menu_because_only_it_shows_the_pets():
    g = ModeGame(slots=[{"builders": 0, "researchers": 0}])
    bot, _, _ = make(g, mode="busy")
    bot.spend_free_slots()
    assert g.upgrades == ["busy"]


def test_busy_calls_the_routine_once_because_it_drains_every_tab_itself():
    g = ModeGame(slots=[{"builders": 3}])
    bot, _, _ = make(g, mode="busy")
    bot.spend_free_slots()
    assert g.upgrades == ["busy"]


def test_walls_repeat_while_a_builder_is_still_free():
    # Repeats while routine returns True AND storage is still full AND a builder is free
    g = ModeGame(slots=[{"builders": 1}, {"builders": 1}, {"builders": 0}],
                 levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls", "walls"]


def test_walls_stop_trying_when_nothing_could_be_upgraded_and_the_attack_goes_on():
    """Not enough resources: no endless retry, the bot goes and attacks."""
    g = ModeGame(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}], upgrade_ok=False)
    bot, _, stop = make(g, mode="walls")
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.upgrades == ["walls"] and g.deployed == 1


def test_the_drain_is_capped():
    g = ModeGame(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert len(g.upgrades) == bot_module.MAX_SPEND_ROUNDS


class ScriptedStorage(ModeGame):
    """Answers the storage reading from a script, one answer per read."""

    def __init__(self, answers, **kw):
        super().__init__(**kw)
        self.answers = list(answers)

    def storages_full(self):
        self.polls += 1
        return self.answers.pop(0) if self.answers else self.last

    last = None


def test_a_passing_false_reading_does_not_hide_full_storages():
    """Seen live: right after a window closes the HUD is shifted and the bar reads 'not full' for a moment."""
    g = ScriptedStorage([False, True, True, False])
    g.last = False
    bot, _, _ = make(g, stop_when_full=True)
    assert bot._storages_full() is True and g.polls == 3        # F, T, T -> majority


def test_two_clear_readings_are_enough_and_cost_two_reads():
    g = ScriptedStorage([True, True])
    bot, _, _ = make(g, stop_when_full=True)
    assert bot._storages_full() is True and g.polls == 2
    g2 = ScriptedStorage([False, False])
    bot2, _, _ = make(g2, stop_when_full=True)
    assert bot2._storages_full() is False and g2.polls == 2


def test_the_free_slots_are_spent_before_deciding_to_wait_for_room():
    """Seen live: it read 'not full' once, drained the counters and attacked without looking again."""
    order = []

    class Order(ModeGame):
        def storages_full(self):
            order.append("storages")
            return False

        def upgrade(self, kind, log=None, check=None):
            order.append("upgrade")
            return True
    g = Order(slots=[{"builders": 1}, {"builders": 0}], levels=[{"gold": True, "elixir": False}])
    bot, _, stop = make(g, mode="walls", stop_when_full=True)
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert order.index("upgrade") < order.index("storages")


def test_unreadable_storage_readings_do_not_count_as_not_full():
    """Review finding: None, None used to read as 'not full' and the bot attacked with a full storage."""
    g = ScriptedStorage([None, True, None, True])
    g.last = None
    bot, _, _ = make(g, stop_when_full=True)
    assert bot._storages_full() is True


def test_all_unreadable_readings_end_as_not_full_after_four_tries():
    g = ScriptedStorage([None] * 8)
    bot, _, _ = make(g, stop_when_full=True)
    assert bot._storages_full() is False and g.polls == 4


def test_the_hud_gets_a_moment_to_settle_before_the_first_reading():
    slept = []
    g = ScriptedStorage([True, True])
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(stop_when_full=True), logs.append, stop, sleep=slept.append)
    bot._storages_full()
    assert slept and slept[0] >= 0.5 and g.polls == 2


def test_busy_mode_says_the_storages_are_full_while_it_waits():
    """Review finding: in busy mode that message was unreachable and the bot opened the menu in silence."""
    def stop_soon(game):
        if game.polls >= 4:
            stop.set()
    g = ModeGame(full=[True], slots=[{"builders": 0}], upgrade_ok=False, on_poll=stop_soon)
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="busy", stop_when_full=True), logs.append, stop, sleep=lambda s: None)
    bot.run()
    assert sum("llenos" in m.lower() for m in logs) == 1


def test_a_menu_left_open_by_the_upgrades_is_closed_before_reading_the_storages():
    order = []

    class Leaves(ModeGame):
        def upgrade(self, kind, log=None, check=None):
            order.append("upgrade")
            return True

        def close_menu(self):
            order.append("close")
            return False

        def storages_full(self):
            order.append("storages")
            return False
    g = Leaves(slots=[{"builders": 1}])
    bot, _, stop = make(g, mode="busy", stop_when_full=True)
    _stop_after_first_attack(bot, stop)
    bot.run()
    i = order.index("upgrade")
    assert order[i + 1] == "close" and order[i + 2] == "storages"


class KeepGame(ModeGame):
    """Records the kind of every upgrade call and lets 'surplus' free builders down to the reserve."""

    def __init__(self, builders, surplus_ok=True, levels=(), **kw):
        super().__init__(slots=[{"builders": builders}], levels=levels, **kw)
        self.builders, self.surplus_ok, self.kinds = builders, surplus_ok, []

    def free_slots(self):
        return {"builders": self.builders}

    def upgrade(self, kind, log=None, check=None):
        self.kinds.append(kind)
        if kind == "surplus" and self.surplus_ok:
            self.builders = 1
            return True
        if kind == "walls":
            return len([k for k in self.kinds if k == "walls"]) == 1     # a second pass finds nothing to pay
        return False


def test_walls_mode_puts_the_surplus_builders_in_cheap_upgrades_first_and_keeps_one_for_walls():
    g = KeepGame(builders=4, levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.kinds[0] == "surplus" and "walls" in g.kinds and g.builders == 1


def test_walls_mode_with_exactly_one_builder_goes_straight_to_the_walls():
    g = KeepGame(builders=1, levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert "surplus" not in g.kinds and g.kinds[0] == "walls"


def test_walls_mode_with_no_free_builder_does_nothing():
    g = KeepGame(builders=0, levels=[{"gold": False, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.kinds == []


def test_walls_still_run_when_the_surplus_could_not_be_paid():
    g = KeepGame(builders=3, surplus_ok=False, levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.kinds[0] == "surplus" and "walls" in g.kinds


def test_busy_mode_never_asks_for_the_surplus_routine():
    g = KeepGame(builders=4)
    bot, _, _ = make(g, mode="busy")
    bot.spend_free_slots()
    assert g.kinds == ["busy"]


class SettlingGame(KeepGame):
    """Right after the Construir menu closes the village counter reads blurry (None) for a moment."""

    def __init__(self, builders, **kw):
        super().__init__(builders, **kw)
        self.blurry_after_surplus = False

    def free_slots(self):
        if self.blurry_after_surplus:
            self.blurry_after_surplus = False
            return {"builders": None}
        return {"builders": self.builders}

    def upgrade(self, kind, log=None, check=None):
        ok = super().upgrade(kind, log, check)
        if kind == "surplus":
            self.blurry_after_surplus = True
        return ok


def test_the_reserved_builder_is_trusted_when_the_counter_blinks_after_the_surplus():
    """Review finding: a blurry read right after the menu closed made the bot think no builder was left and it
    skipped the walls the reserve was kept for."""
    g = SettlingGame(builders=4, levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.kinds[0] == "surplus" and "walls" in g.kinds


def test_the_walls_wait_for_the_hud_after_the_surplus_before_looking_at_the_counter():
    slept = []
    g = KeepGame(builders=3, levels=[{"gold": True, "elixir": False}])
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="walls"), logs.append, stop, sleep=slept.append)
    bot.spend_free_slots()
    assert any(x >= bot_module.STORAGE_SETTLE for x in slept)


def test_a_partial_surplus_still_lets_the_walls_run():
    class Partial(KeepGame):
        def upgrade(self, kind, log=None, check=None):
            self.kinds.append(kind)
            if kind == "surplus":
                self.builders = 3              # one upgrade started, the next price was red
                return True
            return kind == "walls" and self.kinds.count("walls") == 1
    g = Partial(builders=4, levels=[{"gold": True, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.kinds[:2] == ["surplus", "walls"]


def test_losing_the_window_while_reading_the_builders_stops_the_run():
    from cocmacro.winctl import WindowNotFound

    class Lost(KeepGame):
        def free_slots(self):
            raise WindowNotFound("ventana perdida")
    g = Lost(builders=2, levels=[{"gold": True, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.run()
    assert any("ventana perdida" in m for m in logs) and g.deployed == 0


def test_an_unexpected_error_reading_the_builders_means_none_free_and_the_attack_goes_on():
    class Broken(KeepGame):
        def free_slots(self):
            raise ValueError("bad frame")
    g = Broken(builders=2)
    bot, logs, stop = make(g, mode="walls")
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.kinds == [] and g.deployed == 1 and any("No pude leer los constructores" in m for m in logs)


# --- Part 1 Must-Pass Tests ---

def test_walls_nothing_full_1_builder_runs_no_upgrade_attacks():
    # walls, nothing full, 1 builder free -> spend_free_slots() runs no upgrade; a full run() step attacks.
    g = ModeGame(slots=[{"builders": 1}], levels=[{"gold": False, "elixir": False, "dark": False}])
    bot, logs, stop = make(g, mode="walls")
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.upgrades == []
    assert g.deployed == 1
    assert bot.attacks_done == 1


def test_walls_gold_full_only_1_builder_upgrades_walls():
    # walls, gold full only (elixir not), 1 builder -> upgrades == ["walls"].
    g = ModeGame(slots=[{"builders": 1}],
                 levels=[{"gold": True, "elixir": False, "dark": False}, {"gold": True, "elixir": False, "dark": False},
                         {"gold": False, "elixir": False, "dark": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls"]


def test_walls_elixir_full_only_upgrades_walls():
    # walls, elixir full only -> upgrades == ["walls"].
    g = ModeGame(slots=[{"builders": 1}],
                 levels=[{"gold": False, "elixir": True, "dark": False}, {"gold": False, "elixir": True, "dark": False},
                         {"gold": False, "elixir": False, "dark": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls"]


def test_walls_dark_full_only_no_upgrade():
    # walls, dark full only (gold and elixir not) -> no upgrade.
    g = ModeGame(slots=[{"builders": 1}], levels=[{"gold": False, "elixir": False, "dark": True}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == []


def test_walls_gold_full_builders_0_0_1_waits_and_upgrades_walls():
    # walls, gold full, builders 0, 0, then 1 -> waits (naps) and then upgrades == ["walls"]; the wait log line appears once.
    g = ModeGame(slots=[{"builders": 0}, {"builders": 0}, {"builders": 1}],
                 levels=[{"gold": True, "elixir": False}, {"gold": True, "elixir": False},
                         {"gold": False, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls"]
    assert sum("sin constructor libre" in m for m in logs) == 1


def test_walls_gold_full_f8_while_waiting_builder_aborts():
    # walls, gold full, F8 pressed while waiting for a builder -> _Abort, no upgrade.
    stop = threading.Event()

    class StopGame(ModeGame):
        def free_slots(self):
            stop.set()
            return {"builders": 0}

    g = StopGame(levels=[{"gold": True, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.stop = stop
    with pytest.raises(bot_module._Abort, match="Detenido"):
        bot.spend_free_slots()
    assert g.upgrades == []


def test_walls_gold_full_repeat_while_true_and_full_capped_max_spend_rounds():
    # walls, gold full, routine returns True and the storage is still full with a builder -> the routine runs again; capped at MAX_SPEND_ROUNDS.
    g = ModeGame(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}], upgrade_ok=True)
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert len(g.upgrades) == bot_module.MAX_SPEND_ROUNDS
    assert all(u == "walls" for u in g.upgrades)


def test_walls_gold_full_routine_false_no_block_attack_goes_on():
    # walls, gold full, routine returns False -> one call, no block, the attack goes on.
    g = ModeGame(slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}], upgrade_ok=False)
    bot, _, stop = make(g, mode="walls")
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.upgrades == ["walls"]
    assert g.deployed == 1
    assert bot.attacks_done == 1


def test_walls_three_builders_free_nothing_full_surplus_only():
    # walls, 3 builders free, nothing full -> upgrades == ["surplus"] only.
    g = KeepGame(builders=3, levels=[{"gold": False, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.kinds == ["surplus"]


def test_walls_one_passing_true_reading_among_false_not_full():
    # walls, one passing True reading among False ones -> not full (two readings needed).
    class ScriptedLevels(ModeGame):
        def __init__(self, script):
            super().__init__()
            self.script = list(script)

        def storage_levels(self):
            return self.script.pop(0) if self.script else {"gold": False, "elixir": False}

    g = ScriptedLevels([{"gold": True, "elixir": False},
                        {"gold": False, "elixir": False},
                        {"gold": False, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    assert bot._any_storage_full() is False


def test_walls_stop_when_full_false_everything_full_routine_false_no_wait():
    # walls + stop_when_full=False, everything full, routine False -> wait_if_full returns without waiting.
    g = ModeGame(full=[True], levels=[{"gold": True, "elixir": True}], upgrade_ok=False)
    bot, logs, _ = make(g, mode="walls", stop_when_full=False)
    bot.wait_if_full()
    assert g.polls == 0
    assert not any("llenos" in m.lower() for m in logs)


def test_walls_stop_waiting_for_a_builder_when_the_counter_cannot_be_read():
    """Review finding: an unreadable counter read as 'no builder free' and the bot waited for ever on a
    number it could not see. After a few blind looks in a row it goes on attacking."""
    g = ModeGame(slots=[{"builders": 0}, {"builders": None}],
                 levels=[{"gold": True, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == []
    assert sum("No consigo leer los constructores" in m for m in logs) == 1


def test_walls_keep_waiting_while_the_counter_clearly_says_no_builder():
    looks = []

    class Busy(ModeGame):
        def free_slots(self):
            looks.append(1)
            return {"builders": 1 if len(looks) > 12 else 0}

    g = Busy(levels=[{"gold": True, "elixir": False}, {"gold": True, "elixir": False}, {"gold": False, "elixir": False}])
    bot, logs, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls"] and len(looks) > 12


def test_dialogs_are_still_pressed_while_walls_wait_for_a_builder():
    reloads = []

    class Waiting(ModeGame):
        def reload_if_disconnected(self):
            reloads.append(1)
            return False

    g = Waiting(slots=[{"builders": 0}, {"builders": 0}, {"builders": 0}, {"builders": 1}],
                levels=[{"gold": True, "elixir": False}, {"gold": True, "elixir": False}, {"gold": False, "elixir": False}])
    bot, _, _ = make(g, mode="walls")
    bot.spend_free_slots()
    assert g.upgrades == ["walls"] and len(reloads) >= 3


def test_walls_with_stop_when_full_retry_the_routine_after_a_pause_while_everything_is_full():
    """wait_if_full still owns this case: everything full, a builder free, the routine failed once."""
    slept = []

    def stop_soon(game):
        if len(game.upgrades) >= 3:
            stop.set()
    g = ModeGame(full=[True], levels=[{"gold": True, "elixir": True}], slots=[{"builders": 1}],
                 upgrade_ok=False, on_poll=stop_soon)
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="walls", stop_when_full=True), logs.append, stop, sleep=slept.append)
    bot.run()
    assert len(g.upgrades) >= 3 and sum(slept) >= bot_module.FAIL_WAIT_S


def test_waiting_for_a_builder_is_announced_to_the_window():
    phases = []
    g = ModeGame(slots=[{"builders": 0}, {"builders": 1}],
                 levels=[{"gold": True, "elixir": False}, {"gold": True, "elixir": False}, {"gold": False, "elixir": False}])
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(mode="walls"), logs.append, stop, sleep=lambda s: None, on_phase=phases.append)
    bot.spend_free_slots()
    assert phases[:2] == ["wait_builder", "upgrade"]


# ── the Batalla menu left open (live 2026-11-16: two stuck cycles of 4 minutes on the walls account) ──

class MenuGame(ModeGame):
    """The Batalla menu is a full-height panel over the left half: it hides the Batalla button, so the village is
    not 'home' while it is up. `menu_swallows` presses of Buscar are lost and leave it open."""

    def __init__(self, menu_open=True, menu_swallows=0, **kw):
        super().__init__(**kw)
        self.menu, self.swallows = menu_open, menu_swallows

    def battle_menu_open(self):
        return self.menu

    def screen_is(self, name):
        if name == "home" and self.menu:
            return False
        return super().screen_is(name)

    def click_button(self, name):
        if name == "battle":
            self.menu = True
            self.clicks.append(name)
            return
        if name == "find" and self.menu:
            self.clicks.append(name)
            if self.swallows > 0:
                self.swallows -= 1
                return
            self.menu = False
            self.screen = "clouds"            # Buscar batalla goes to the search screen, never back to the village
            return
        if name == "attack" and self.menu:
            self.clicks.append(name)             # the panel is over the village: Atacar is not there to press
            return
        super().click_button(name)


def test_a_search_whose_buscar_press_was_lost_presses_it_again_instead_of_waiting_for_loading():
    """The menu is still up, so the village is not 'home': that used to be taken for 'loading a village'."""
    g = MenuGame(menu_open=False, menu_swallows=1)
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks.count("find") == 2 and g.deployed == 1
    assert any("repito" in m for m in logs)


def test_a_cycle_that_starts_with_the_menu_already_open_goes_on_from_there():
    g = MenuGame(menu_open=True)
    bot, logs, _ = make(g)
    assert bot.run_once() is True
    assert g.clicks[:2] == ["find", "attack"]          # no Batalla press: the menu is already there
    assert g.deployed == 1


def test_the_recovery_stops_when_it_finds_the_menu_open_and_clicks_nothing():
    g = MenuGame(menu_open=True)
    bot, logs, _ = make(g)
    bot._recover("atasco")
    assert g.clicks == [] and any("menu de Batalla" in m for m in logs)


def test_nothing_is_spent_with_the_menu_over_the_village():
    """The walls routine taps the village: with the panel over half of it that is a lottery."""
    g = MenuGame(menu_open=True, slots=[{"builders": 1}], levels=[{"gold": True, "elixir": False}])
    bot, _, stop = make(g, mode="walls")
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.upgrades == [] and g.deployed == 1


def test_a_game_that_cannot_see_the_menu_waits_for_loading_as_before():
    """Without the check (an older backend, or a template that does not match) a lost press of Buscar is again taken
    for 'loading': that is the behaviour before this change, and it ends in the timeout it always did."""
    g = MenuGame(menu_open=False, menu_swallows=1)
    g.battle_menu_open = None                          # the optional method is not there
    bot, _, _ = make(g)
    bot.timeout_s = 3
    assert bot.run_once() is False
    assert g.clicks == ["battle", "find", "attack"]


def test_a_search_that_never_takes_gives_up_after_three_presses_of_buscar():
    g = MenuGame(menu_open=False, menu_swallows=99)
    bot, logs, _ = make(g)
    assert bot.run_once() is False
    assert g.clicks.count("find") == 3 and g.clicks.count("battle") == 1       # Batalla only once: the menu stayed up
    assert any("La busqueda no arranco tras 3 intentos" in m for m in logs)


def test_with_everything_full_and_the_menu_up_the_bot_attacks_once_instead_of_waiting():
    """Known and accepted: the panel hides the storage bars and half the village, so it neither waits for room nor taps
    walls; one attack closes the menu and the next cycle is a normal one."""
    g = MenuGame(menu_open=True, full=[True], slots=[{"builders": 1}], levels=[{"gold": True, "elixir": True}])
    bot, _, stop = make(g, mode="walls", stop_when_full=True)
    _stop_after_first_attack(bot, stop)
    bot.run()
    assert g.deployed == 1 and g.upgrades == []


def test_a_menu_that_never_closes_keeps_the_recoveries_counting_and_never_ends_the_run():
    g = MenuGame(menu_open=False, menu_swallows=10**6)
    logs, stop = [], threading.Event()
    bot = Bot(g, config.Config(), logs.append, stop, sleep=lambda s: None)
    real = g.click_button

    def watch(name):
        real(name)
        if g.clicks.count("find") >= 9:
            stop.set()
    g.click_button = watch
    bot.run()
    assert bot.recoveries_done >= 2 and bot.attacks_done == 0
    assert sum("El menu de Batalla esta abierto" in m for m in logs) >= 2
