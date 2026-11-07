"""Tests for cocmacro.upgrades — wall and building upgrade routines."""
import pytest

from cocmacro import vision
from cocmacro.config import Config
from cocmacro.upgrades import (
    MAX_ADDS,
    _select_filter,
    free_slots,
    upgrade_busy,
    upgrade_walls,
)


class _Abort(Exception):
    pass


ROW = (0.87, 0.20)


@pytest.fixture(autouse=True)
def _first_row_on_screen(monkeypatch):
    """The fake screens have no pixels: say where the first row of the list is, unless a test says otherwise."""
    monkeypatch.setattr(vision, "first_upgrade_row", lambda _frame: ROW)


# ── helpers ──────────────────────────────────────────────────────────


def _cfg():
    """Build a Config with all button/region names used by the upgrade routines."""
    cfg = Config()
    cfg.buttons.update({
        "wall_spot": (0.5, 0.5),
        "wall_more": (0.6, 0.6),
        "wall_add1": (0.55, 0.65),
        "wall_remove": (0.55, 0.75),
        "wall_up_gold": (0.4, 0.8),
        "wall_up_elixir": (0.7, 0.8),
        "build": (0.9, 0.9),
        "build_close": (0.95, 0.05),
        "filter": (0.85, 0.1),
    })
    cfg.regions.update({
        "wall_cost_gold": (0.3, 0.7, 0.5, 0.75),
        "wall_cost_elixir": (0.6, 0.7, 0.8, 0.75),
        "free_builders": (0.1, 0.0, 0.2, 0.05),
        "free_researchers": (0.2, 0.0, 0.3, 0.05),
    })
    return cfg


class FakeScreen:
    """Fake Screen recording clicks and providing configurable template results."""

    def __init__(self, has_templates=None, find_templates=None):
        self.clicks: list[tuple[float, float]] = []
        self.click_names: list[str] = []
        self._has = has_templates or {}
        self._find = find_templates or {}
        self._frame = object()  # sentinel
        self._menu_open = False

    def grab(self):
        return self._frame

    def click(self, x: float, y: float) -> None:
        self.clicks.append((x, y))
        # Record a human-readable name for common positions
        self.click_names.append(self._name_for(x, y))
        if self.click_names[-1] == "build":
            self._menu_open = True
        elif self.click_names[-1] == "build_close":
            self._menu_open = False

    def has(self, template: str) -> bool:
        if template == "menu_close_x" and template not in self._has:
            return self._menu_open                  # the Construir menu opens and closes like the real one
        if template == "battle" and template not in self._has:
            return True                             # the village (Batalla button) is on screen
        v = self._has.get(template, False)
        if callable(v):
            return v()
        return v

    def find(self, template: str) -> tuple[float, float] | None:
        v = self._find.get(template)
        if callable(v):
            return v()
        return v

    def _name_for(self, x: float, y: float) -> str:
        cfg = _busy_cfg()
        for name, pos in cfg.buttons.items():
            if abs(pos[0] - x) < 0.001 and abs(pos[1] - y) < 0.001:
                return name
        return f"({x:.3f},{y:.3f})"


def _nop_sleep(_s):
    pass


# ── upgrade_walls tests ─────────────────────────────────────────────


def test_walls_normal_upgrade_both_resources(monkeypatch):
    """Cost turns red after 3 add1 clicks for each resource -> upgrade both."""
    cfg = _cfg()
    counters = {"gold": 0, "elixir": 0}

    def cost_tracker(_frame, region):
        for res in ("gold", "elixir"):
            if region == cfg.regions[f"wall_cost_{res}"]:
                counters[res] += 1
                # Calls: 1=after add1#1, 2=after add1#2, 3=after add1#3 -> True here
                # 4=after remove -> False (affordable again)
                if counters[res] <= 2:
                    return False
                if counters[res] == 3:
                    return True  # triggers the remove
                return False  # after remove, affordable again
        return False

    monkeypatch.setattr(vision, "cost_is_red", cost_tracker)

    scr = FakeScreen(
        has_templates={"wall_panel": True, "gem_cost": False, "confirm_upgrade": True, "walls_dialog": True},
        find_templates={"confirm_upgrade": (0.5, 0.9)},
    )

    result = upgrade_walls(scr, cfg, lambda s: None, lambda: None, _nop_sleep)

    assert result is True
    # For each resource: wall_spot, wall_more, add1 x3, remove, up_<res>
    # Gold clicks
    names = scr.click_names
    assert names[0] == "wall_spot"
    assert names[1] == "wall_more"
    assert names[2:5] == ["wall_add1"] * 3
    assert names[5] == "wall_remove"
    assert names[6] == "wall_up_gold"
    # confirm click at (0.5, 0.9)
    assert names[7] == "(0.500,0.900)"
    # Elixir clicks
    assert names[8] == "wall_spot"
    assert names[9] == "wall_more"
    assert names[10:13] == ["wall_add1"] * 3
    assert names[13] == "wall_remove"
    assert names[14] == "wall_up_elixir"


def test_walls_panel_absent_returns_false(monkeypatch):
    """Wall panel absent -> no add/remove/upgrade clicks, returns False."""
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)

    scr = FakeScreen(
        has_templates={"wall_panel": False},
    )

    result = upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)

    assert result is False
    # Only the selection attempts (spot + two shifted retries); no wall_more, no add/remove/up
    names = scr.click_names
    assert names[0] == "wall_spot" and names[1:3] != ["wall_spot"] * 2 and len(names) == 5
    assert names[3:] == ["build", "build_close"]      # the view is reset even when nothing was upgraded
    assert not any(n in names for n in ("wall_more", "wall_add1", "wall_remove", "wall_up_gold"))


def test_walls_cost_never_red_no_upgrade(monkeypatch):
    """Cost never turns red -> at most MAX_ADDS add1 clicks, then no upgrade."""
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)

    scr = FakeScreen(
        has_templates={"wall_panel": True, "gem_cost": False},
    )
    logs = []

    result = upgrade_walls(scr, _cfg(), logs.append, lambda: None, _nop_sleep)

    assert result is False
    names = scr.click_names
    # For gold: wall_spot, wall_more, add1 * MAX_ADDS (cost never red -> exhausts loop)
    assert names[0] == "wall_spot"
    assert names[1] == "wall_more"
    assert names[2:2 + MAX_ADDS] == ["wall_add1"] * MAX_ADDS
    # No wall_up_gold
    assert "wall_up_gold" not in names
    assert "wall_up_elixir" not in names


def test_walls_check_raises_stops_immediately(monkeypatch):
    """check() raising an exception propagates and stops everything."""
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)

    scr = FakeScreen(has_templates={"wall_panel": True})

    call_count = {"n": 0}

    def check():
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise _Abort("stopped")

    with pytest.raises(_Abort):
        upgrade_walls(scr, _cfg(), lambda s: None, check, _nop_sleep)

    # Only one click before check raised on the second call
    assert len(scr.clicks) == 1


# ── upgrade_cheapest_permanent tests ─────────────────────────────────


def test_free_slots(monkeypatch):
    """free_slots returns builder and researcher counts from vision."""
    cfg = _cfg()

    def fake_free_count(_frame, region):
        if region == cfg.regions["free_builders"]:
            return 3
        if region == cfg.regions["free_researchers"]:
            return 1
        return None

    monkeypatch.setattr(vision, "free_count", fake_free_count)

    scr = FakeScreen()
    result = free_slots(scr, cfg)
    assert result == {"builders": 3, "researchers": 1}


def test_free_slots_none(monkeypatch):
    """free_slots returns None when vision cannot read."""
    monkeypatch.setattr(vision, "free_count", lambda _f, _r: None)

    scr = FakeScreen()
    result = free_slots(scr, _cfg())
    assert result == {"builders": None, "researchers": None}


def test_walls_zoom_out_first_when_the_screen_can_do_it(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)
    scr = FakeScreen(has_templates={"wall_panel": False})
    calls = []
    scr.zoom_out = lambda: calls.append("zoom")
    upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)
    assert calls == ["zoom"] and scr.click_names[0] == "wall_spot"


def test_walls_end_by_opening_and_closing_construir(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True})
    upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)
    assert scr.click_names[-2:] == ["build", "build_close"]


# -- busy mode: Construir menu, one pass over the tabs that have a free slot ----------------------

class MenuScreen(FakeScreen):
    """Menu with a scripted free count per tab; remembers which tab is open."""

    def __init__(self, free, **kw):
        super().__init__(**kw)
        self.free = free


def _busy_cfg():
    cfg = _cfg()
    cfg.buttons.update({"tab_builders": (0.76, 0.93), "tab_researchers": (0.83, 0.93), "tab_pets": (0.97, 0.93),
                        "upgrade_confirm": (0.70, 0.85), "upgrade_window_close": (0.88, 0.07), "dialog_close": (0.67, 0.33)})
    cfg.regions.update({"tab_count_builders": (0.74, 0.95, 0.79, 0.98), "tab_count_researchers": (0.81, 0.95, 0.86, 0.98),
                        "tab_count_pets": (0.95, 0.95, 0.99, 0.98), "upgrade_cost": (0.66, 0.84, 0.72, 0.90)})
    return cfg


def _busy_screen(**has):
    base = {"menu_close_x": True, "filter_permanent_on": True, "filter_cost_min_on": True, "upgrade_window": True}
    base.update(has)
    return FakeScreen(has_templates=base, find_templates={"filtered_header": (0.87, 0.46),
                                                          "assigned_header": (0.87, 0.14)})


def _free(monkeypatch, builders=0, researchers=0, pets=0, red=False):
    cfg = _busy_cfg()
    reads = {cfg.regions["tab_count_builders"]: builders, cfg.regions["tab_count_researchers"]: researchers,
             cfg.regions["tab_count_pets"]: pets}
    monkeypatch.setattr(vision, "free_count", lambda _f, region: reads[region])
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: red)
    return cfg


def test_busy_nothing_free_only_looks_and_closes(monkeypatch):
    cfg = _free(monkeypatch)
    scr = _busy_screen()
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is False
    assert scr.click_names == ["build", "build_close"]


def test_busy_builder_free_uses_builders_tab_with_both_filters_and_confirms(monkeypatch):
    cfg = _free(monkeypatch, builders=2)
    scr = _busy_screen()
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    n = scr.click_names
    assert n[:3] == ["build", "tab_builders", "filter"] and n[3] == "filter"      # popup opened and closed
    assert "upgrade_confirm" in n and n.index("upgrade_confirm") > n.index("tab_builders")
    assert "tab_researchers" not in n and "tab_pets" not in n
    assert scr.clicks[n.index("upgrade_confirm")] == cfg.buttons["upgrade_confirm"]


def test_busy_researcher_free_filters_only_by_cost_min(monkeypatch):
    cfg = _free(monkeypatch, researchers=1)
    scr = _busy_screen(filter_permanent_on=False)      # no Permanente on this tab: it must not be needed
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    assert "tab_researchers" in scr.click_names and "upgrade_confirm" in scr.click_names


def test_busy_pets_have_no_filter_and_use_the_assigned_header(monkeypatch):
    cfg = _free(monkeypatch, pets=1)
    scr = _busy_screen()
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    n = scr.click_names
    assert "tab_pets" in n and "filter" not in n and "upgrade_confirm" in n
    assert ROW in scr.clicks and n.index("upgrade_confirm") > n.index("tab_pets")


def test_busy_never_touches_the_forge_tab(monkeypatch):
    cfg = _free(monkeypatch, builders=1, researchers=1, pets=1)
    scr = _busy_screen()
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    assert all(abs(x - 0.899) > 0.01 for x, y in scr.clicks if y > 0.9)        # the third tab, x ~0.899


def test_busy_red_price_closes_the_window_without_confirming(monkeypatch):
    cfg = _free(monkeypatch, builders=1, red=True)
    scr = _busy_screen()
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is False
    assert "upgrade_confirm" not in scr.click_names


def test_busy_without_the_upgrade_window_does_not_confirm(monkeypatch):
    cfg = _free(monkeypatch, builders=1)
    scr = _busy_screen(upgrade_window=False)
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is False
    assert "upgrade_confirm" not in scr.click_names


def test_busy_missing_filter_button_closes_popup_and_menu(monkeypatch):
    cfg = _free(monkeypatch, builders=1)
    scr = _busy_screen(filter_permanent_on=False, filter_cost_min_on=False)     # nothing recognised
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is False
    n = scr.click_names
    assert n.count("filter") == 2 and n[-1] == "build_close" and "upgrade_confirm" not in n


def test_busy_check_raising_stops_everything(monkeypatch):
    cfg = _free(monkeypatch, builders=1)
    scr = _busy_screen()

    def boom():
        raise _Abort()
    with pytest.raises(_Abort):
        upgrade_busy(scr, cfg, lambda s: None, boom, _nop_sleep)
    assert scr.click_names == []


def test_walls_click_the_wall_found_on_screen_before_the_fixed_spot(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True})
    scr.wall_spot = lambda: (0.61, 0.22)
    upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)
    assert scr.clicks[0] == (0.61, 0.22)


def test_walls_press_nothing_when_the_block_cannot_be_found(monkeypatch):
    """Never fall back to a fixed spot on a moving camera: it can land on the gem shop."""
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True})
    scr.wall_spot = lambda: None
    logs = []
    assert upgrade_walls(scr, _cfg(), logs.append, lambda: None, _nop_sleep) is False
    assert scr.clicks == [] and any("No veo el bloque" in m for m in logs)


def test_walls_stop_touching_things_when_another_screen_opens(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": False, "battle": False})      # a window covers the village
    logs = []
    assert upgrade_walls(scr, _cfg(), logs.append, lambda: None, _nop_sleep) is False
    assert scr.click_names == ["wall_spot"] and any("inesperada" in m for m in logs)


def test_the_menu_is_only_closed_when_it_is_open(monkeypatch):
    """Its X is where the gold bar sits in the village: pressing it there opens the gem shop."""
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True, "menu_close_x": False})     # the build click never opens it
    upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)
    assert "build_close" not in scr.click_names


def test_walls_close_a_menu_left_open_before_zooming(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True})
    scr._menu_open = True
    upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)
    assert scr.click_names[0] == "build_close"


def test_walls_do_not_report_success_when_the_dialog_never_shows(monkeypatch):
    calls = iter([True, False, True, False])      # per resource: red after the add, payable after the remove
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: next(calls, False))
    scr = FakeScreen(has_templates={"wall_panel": True, "confirm_upgrade": False, "walls_dialog": True})
    logs = []
    assert upgrade_walls(scr, _cfg(), logs.append, lambda: None, _nop_sleep) is False
    assert any("dialogo" in m for m in logs)


def test_walls_never_press_mejorar_while_the_price_is_red(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True, "confirm_upgrade": True, "walls_dialog": True},
                     find_templates={"confirm_upgrade": (0.59, 0.62)})
    assert upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep) is False
    assert not any(n.startswith("wall_up_") for n in scr.click_names)
    assert "(0.590,0.620)" not in scr.click_names                 # the Vale is never pressed either


def test_walls_close_the_open_panel_when_giving_up_a_resource(monkeypatch):
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: True)
    scr = FakeScreen(has_templates={"wall_panel": True})
    upgrade_walls(scr, _cfg(), lambda s: None, lambda: None, _nop_sleep)
    n = scr.click_names
    first_give_up = n.index("wall_remove") + 1
    assert n[first_give_up:first_give_up + 3] == ["wall_remove", "build", "build_close"]     # panel reset before elixir


def test_busy_filter_retries_honour_f8(monkeypatch):
    cfg = _free(monkeypatch, builders=1)
    scr = _busy_screen(filter_permanent_on=False, filter_cost_min_on=False)
    scr._find = {"filtered_header": (0.87, 0.46)}
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        if calls["n"] > 6:
            raise _Abort()
    with pytest.raises(_Abort):
        upgrade_busy(scr, cfg, lambda s: None, check, _nop_sleep)


class ToggleScreen(FakeScreen):
    """Stateful: pressing the 'off' button turns the 'on' look of that filter on, like the real popup."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.on = False

    def has(self, template):
        return self.on if template == "filter_cost_min_on" else super().has(template)

    def click(self, x, y):
        super().click(x, y)
        if (x, y) == (0.85, 0.12):
            self.on = True


def test_select_filter_presses_the_button_and_sees_it_turn_on():
    scr = ToggleScreen(find_templates={"filter_cost_min": (0.85, 0.12)})
    assert _select_filter(scr, "filter_cost_min", "filter_cost_min_on", lambda: None, _nop_sleep) is True
    assert scr.clicks == [(0.85, 0.12)]


def test_select_filter_reports_failure_when_pressing_does_nothing():
    scr = FakeScreen(find_templates={"filter_cost_min": (0.85, 0.12)})
    assert _select_filter(scr, "filter_cost_min", "filter_cost_min_on", lambda: None, _nop_sleep) is False


def test_walls_second_remove_rescues_the_upgrade(monkeypatch):
    cfg = _cfg()
    seq = iter([True, True, False, True, True, False])     # per resource: red after the add, red after remove 1, payable after 2
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: next(seq, False))
    scr = FakeScreen(has_templates={"wall_panel": True, "confirm_upgrade": True, "walls_dialog": True},
                     find_templates={"confirm_upgrade": (0.59, 0.62)})
    assert upgrade_walls(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    n = scr.click_names
    assert n[:6] == ["wall_spot", "wall_more", "wall_add1", "wall_remove", "wall_remove", "wall_up_gold"]


def test_busy_upgrades_every_tab_with_a_free_slot_in_one_pass(monkeypatch):
    cfg = _free(monkeypatch, builders=1, researchers=1)
    scr = _busy_screen()
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    n = scr.click_names
    assert n.index("tab_builders") < n.index("tab_researchers") and n.count("upgrade_confirm") == 2
    assert n[-1] == "build_close"


def test_busy_does_not_confirm_when_the_window_price_is_red(monkeypatch):
    cfg = _busy_cfg()
    monkeypatch.setattr(vision, "free_count", lambda _f, r: 1 if r == cfg.regions["tab_count_builders"] else 0)
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, region: region == cfg.regions["upgrade_cost"])
    scr = _busy_screen()
    logs = []
    assert upgrade_busy(scr, cfg, logs.append, lambda: None, _nop_sleep) is False
    assert "upgrade_confirm" not in scr.click_names and "upgrade_window_close" in scr.click_names
    assert any("No hay recursos" in m for m in logs)


def _afford_one(monkeypatch):
    seq = iter([True, False])           # red after the first add, payable after the remove
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: next(seq, False))


def test_walls_close_the_no_builder_notice_and_never_press_anything_else(monkeypatch):
    """Seen live: with no free builder the game offers to finish another task for 3 gems."""
    _afford_one(monkeypatch)
    scr = FakeScreen(has_templates={"wall_panel": True, "no_builder_dialog": True, "walls_dialog": True},
                     find_templates={"confirm_upgrade": (0.59, 0.62)})
    logs = []
    assert upgrade_walls(scr, _busy_cfg(), logs.append, lambda: None, _nop_sleep) is False
    n = scr.click_names
    assert n[-1] == "dialog_close" and "(0.590,0.620)" not in n
    assert sum(m.startswith("No hay constructores") for m in logs) == 1


def test_walls_confirm_only_with_the_walls_dialog_title_on_screen(monkeypatch):
    _afford_one(monkeypatch)
    scr = FakeScreen(has_templates={"wall_panel": True, "walls_dialog": False},
                     find_templates={"confirm_upgrade": (0.59, 0.62)})      # some other green button
    upgrade_walls(scr, _busy_cfg(), lambda s: None, lambda: None, _nop_sleep)
    assert "(0.590,0.620)" not in scr.click_names


def test_busy_closes_the_no_builder_notice_after_confirming(monkeypatch):
    cfg = _free(monkeypatch, builders=1)
    scr = _busy_screen(no_builder_dialog=True)
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is False
    n = scr.click_names
    assert n.index("dialog_close") > n.index("upgrade_confirm")


class DrainScreen(FakeScreen):
    """The tab counter drops by one every time the green Confirmar is pressed, like the real menu."""

    def __init__(self, free, stick=False, **kw):
        super().__init__(**kw)
        self.free, self.stick, self.confirms = free, stick, 0

    def click(self, x, y):
        super().click(x, y)
        if self.click_names[-1] == "upgrade_confirm":
            self.confirms += 1
            if not self.stick:
                self.free -= 1


def _drain(monkeypatch, scr, red_after=None, researchers=0):
    cfg = _busy_cfg()
    monkeypatch.setattr(vision, "free_count", lambda _f, r: scr.free if r == cfg.regions["tab_count_builders"]
                        else (researchers if r == cfg.regions["tab_count_researchers"] else 0))
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: red_after is not None and scr.confirms >= red_after)
    return cfg


def _drain_screen(free, **kw):
    return DrainScreen(free, has_templates={"menu_close_x": True, "filter_permanent_on": True,
                                            "filter_cost_min_on": True, "upgrade_window": True},
                       find_templates={"filtered_header": (0.87, 0.46)}, **kw)


def test_busy_keeps_upgrading_a_tab_until_its_counter_reaches_zero(monkeypatch):
    scr = _drain_screen(3)
    cfg = _drain(monkeypatch, scr)
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    assert scr.confirms == 3 and scr.free == 0


def test_busy_stops_a_tab_when_the_cheapest_item_cannot_be_paid(monkeypatch):
    """Not enough resources: it does not insist, the bot goes to attack."""
    scr = _drain_screen(3)
    cfg = _drain(monkeypatch, scr, red_after=1)          # the second cheapest price is red
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    assert scr.confirms == 1 and scr.free == 2 and scr.click_names[-1] == "build_close"


def test_busy_does_not_loop_when_the_counter_never_drops(monkeypatch):
    scr = _drain_screen(2, stick=True)
    cfg = _drain(monkeypatch, scr)
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    assert scr.confirms == 1


def test_busy_drain_is_capped_per_tab(monkeypatch):
    from cocmacro.upgrades import MAX_PER_TAB
    scr = _drain_screen(99)
    cfg = _drain(monkeypatch, scr)
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    assert scr.confirms == MAX_PER_TAB


def test_busy_drains_researchers_after_builders(monkeypatch):
    scr = _drain_screen(0)
    cfg = _drain(monkeypatch, scr, researchers=1)
    scr.free = 0
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    assert "tab_researchers" in scr.click_names and "tab_builders" not in scr.click_names


def test_busy_presses_nothing_when_the_list_is_not_on_screen(monkeypatch):
    cfg = _free(monkeypatch, builders=1)
    monkeypatch.setattr(vision, "first_upgrade_row", lambda _frame: None)
    scr = _busy_screen()
    logs = []
    assert upgrade_busy(scr, cfg, logs.append, lambda: None, _nop_sleep) is False
    assert ROW not in scr.clicks and "upgrade_confirm" not in scr.click_names
    assert any("No encuentro la lista" in m for m in logs) and scr.click_names[-1] == "build_close"


def test_busy_needs_no_banner_to_find_the_first_row_of_the_researchers_tab(monkeypatch):
    """Real finding: that tab has no 'Filtrado' banner, only the progress bars of what is being upgraded."""
    cfg = _free(monkeypatch, researchers=1)
    scr = FakeScreen(has_templates={"menu_close_x": True, "filter_cost_min_on": True, "upgrade_window": True})
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep) is True
    assert "upgrade_confirm" in scr.click_names


def test_busy_presses_no_row_when_the_menu_did_not_open(monkeypatch):
    """Review finding: with the menu closed the list column is the village HUD (gold bar, gem shop)."""
    cfg = _free(monkeypatch, builders=1)
    scr = FakeScreen(has_templates={"menu_close_x": False, "filter_permanent_on": True,
                                    "filter_cost_min_on": True, "upgrade_window": True})
    scr._menu_open = False
    logs = []
    assert upgrade_busy(scr, cfg, logs.append, lambda: None, _nop_sleep) is False
    assert ROW not in scr.clicks and "upgrade_confirm" not in scr.click_names
    assert any("no se abrio" in m for m in logs)


def test_busy_reads_the_counter_again_when_it_blinks_after_an_upgrade(monkeypatch):
    scr = _drain_screen(2)
    cfg = _busy_cfg()
    calls = {"n": 0}

    def free(_f, region):
        if region != cfg.regions["tab_count_builders"]:
            return 0
        calls["n"] += 1
        if calls["n"] == 2:
            return None                      # blurry right after the confirm
        return scr.free
    monkeypatch.setattr(vision, "free_count", free)
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    assert scr.confirms == 2 and scr.free == 0


def _keep_one(monkeypatch, scr, researchers=0, pets=0):
    cfg = _busy_cfg()
    monkeypatch.setattr(vision, "free_count", lambda _f, r: scr.free if r == cfg.regions["tab_count_builders"]
                        else (researchers if r == cfg.regions["tab_count_researchers"]
                              else (pets if r == cfg.regions["tab_count_pets"] else 0)))
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)
    return cfg


def test_keep_one_builder_upgrades_only_the_surplus(monkeypatch):
    """Walls mode wants exactly one builder free: with 4 free, three go to the cheapest permanent upgrade."""
    scr = _drain_screen(4)
    cfg = _keep_one(monkeypatch, scr)
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep,
                        only=("builders",), keep={"builders": 1}) is True
    assert scr.confirms == 3 and scr.free == 1


def test_keep_one_builder_does_nothing_with_exactly_one_free(monkeypatch):
    scr = _drain_screen(1)
    cfg = _keep_one(monkeypatch, scr)
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep,
                        only=("builders",), keep={"builders": 1}) is False
    assert scr.confirms == 0 and "tab_builders" not in scr.click_names


def test_keep_one_builder_leaves_researchers_and_pets_alone(monkeypatch):
    scr = _drain_screen(2)
    cfg = _keep_one(monkeypatch, scr, researchers=2, pets=1)
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep, only=("builders",), keep={"builders": 1})
    assert "tab_researchers" not in scr.click_names and "tab_pets" not in scr.click_names
    assert scr.confirms == 1


class BigStepScreen(DrainScreen):
    """A confirm that drops the counter by two (the counter can move more than one between two readings)."""

    def click(self, x, y):
        FakeScreen.click(self, x, y)
        if self.click_names[-1] == "upgrade_confirm":
            self.confirms += 1
            self.free = max(0, self.free - 2)


def test_keep_one_builder_stops_when_the_counter_jumps_below_the_reserve(monkeypatch):
    scr = BigStepScreen(2, has_templates={"menu_close_x": True, "filter_permanent_on": True,
                                          "filter_cost_min_on": True, "upgrade_window": True})
    cfg = _keep_one(monkeypatch, scr)
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep, only=("builders",), keep={"builders": 1})
    assert scr.confirms == 1                      # one confirm took it from 2 to 0: no second one


def test_busy_stops_when_the_counter_stays_unreadable_after_a_confirm(monkeypatch):
    scr = _drain_screen(3)
    cfg = _busy_cfg()
    reads = {"n": 0}

    def free(_f, region):
        if region != cfg.regions["tab_count_builders"]:
            return 0
        reads["n"] += 1
        return scr.free if reads["n"] == 1 else None      # the first look sees 3, every later one is blurry
    monkeypatch.setattr(vision, "free_count", free)
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: False)
    upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep)
    assert scr.confirms == 1


# ── hero priority and never-upgrade rows ─────────────────────────────

HERO_BTN = (0.72, 0.34)


class _HeroScreen(FakeScreen):
    """Construir menu whose Heroe filter button toggles when pressed (and can be missing or stuck)."""

    def __init__(self, hero_exists=True, hero_on=False, sticky=False, **find):
        super().__init__(has_templates={"menu_close_x": True, "filter_permanent_on": True,
                                        "filter_cost_min_on": True, "upgrade_window": True},
                         find_templates={"filtered_header": (0.87, 0.46), **find})
        self.hero_exists, self.hero_on, self.sticky = hero_exists, hero_on, sticky
        self.finds: list[str] = []
        self.hero_presses = 0
        self.confirms = 0

    def click(self, x, y):
        super().click(x, y)
        if (x, y) == HERO_BTN:
            self.hero_presses += 1
            if self.hero_exists and not self.sticky:
                self.hero_on = not self.hero_on
        if self.click_names[-1] == "upgrade_confirm":
            self.confirms += 1

    def has(self, template):
        if template == "filter_hero_on":
            return self.hero_on
        if template == "filter_hero":
            return self.hero_exists and not self.hero_on
        return super().has(template)

    def find(self, template):
        self.finds.append(template)
        if template == "filter_hero":
            return HERO_BTN if self.hero_exists and not self.hero_on else None
        if template == "filter_hero_on":
            return HERO_BTN if self.hero_on else None
        return super().find(template)


def _run(monkeypatch, scr, builders=1, heroes=False, red=False):
    cfg = _busy_cfg()
    monkeypatch.setattr(vision, "free_count", lambda _f, r: max(builders - scr.confirms, 0)
                        if r == cfg.regions["tab_count_builders"] else 0)
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: red)
    logs: list[str] = []
    ok = upgrade_busy(scr, cfg, logs.append, lambda: None, _nop_sleep, heroes=heroes)
    return ok, logs


def test_busy_with_heroes_selects_the_hero_filter_first(monkeypatch):
    scr = _HeroScreen()
    ok, logs = _run(monkeypatch, scr, heroes=True)
    assert ok is True and scr.confirms == 1
    assert scr.hero_presses == 1 and scr.hero_on is True
    assert scr.click_names.count("tab_builders") == 1            # no second, plain attempt
    assert any("heroe" in line for line in logs)


def test_busy_with_heroes_falls_back_when_the_hero_filter_cannot_be_selected(monkeypatch):
    scr = _HeroScreen(hero_exists=False)
    ok, logs = _run(monkeypatch, scr, heroes=True)
    assert ok is True and scr.confirms == 1
    assert scr.click_names.count("tab_builders") == 2             # hero try, then the usual one
    assert any("Filtros no activados" in line for line in logs)
    assert not any("heroe" in line for line in logs)


def test_busy_with_heroes_falls_back_when_the_hero_list_is_empty_and_switches_the_filter_off(monkeypatch):
    rows = iter([None, None])                                     # empty hero list (both looks), then a plain list
    monkeypatch.setattr(vision, "first_upgrade_row", lambda _f: next(rows, ROW))
    scr = _HeroScreen()
    ok, logs = _run(monkeypatch, scr, heroes=True)
    assert ok is True and scr.confirms == 1
    assert scr.hero_on is False and scr.hero_presses == 2         # on for the hero try, off for the plain one
    assert any("No encuentro la lista" in line for line in logs)


def test_busy_with_heroes_falls_back_when_the_hero_price_is_red(monkeypatch):
    cfg = _busy_cfg()
    scr = _HeroScreen()
    monkeypatch.setattr(vision, "free_count", lambda _f, r: max(1 - scr.confirms, 0)
                        if r == cfg.regions["tab_count_builders"] else 0)
    reds = iter([True, False])                                    # the hero cannot be paid; the plain one can
    monkeypatch.setattr(vision, "cost_is_red", lambda _f, _r: next(reds, False))
    assert upgrade_busy(scr, cfg, lambda s: None, lambda: None, _nop_sleep, heroes=True) is True
    assert scr.click_names.count("tab_builders") == 2 and scr.confirms == 1


def test_a_failed_hero_try_is_not_repeated_for_every_upgrade_of_the_tab(monkeypatch):
    scr = _HeroScreen(hero_exists=False)
    ok, logs = _run(monkeypatch, scr, builders=3, heroes=True)
    assert scr.confirms == 3
    assert sum("Filtros no activados" in line for line in logs) == 1      # tried once, then plain only


def test_no_free_builder_notice_after_the_hero_try_does_not_start_a_plain_attempt(monkeypatch):
    scr = _HeroScreen()
    scr._has["no_builder_dialog"] = True
    ok, logs = _run(monkeypatch, scr, heroes=True)
    assert ok is False
    assert scr.click_names.count("tab_builders") == 1 and scr.click_names.count("upgrade_confirm") == 1


def test_without_heroes_the_hero_filter_is_never_selected(monkeypatch):
    scr = _HeroScreen()
    ok, _ = _run(monkeypatch, scr)
    assert ok is True and scr.hero_presses == 0 and scr.confirms == 1


def test_a_remembered_hero_filter_is_switched_off_for_the_plain_flow(monkeypatch):
    scr = _HeroScreen(hero_on=True)
    ok, _ = _run(monkeypatch, scr)
    assert ok is True and scr.hero_on is False and scr.hero_presses == 1


def test_a_hero_filter_that_will_not_switch_off_stops_the_plain_attempt(monkeypatch):
    scr = _HeroScreen(hero_on=True, sticky=True)
    ok, logs = _run(monkeypatch, scr)
    assert ok is False and scr.confirms == 0
    assert any("No pude apagar" in line for line in logs)


def test_clear_filter_reports_what_it_saw():
    from cocmacro.upgrades import _clear_filter
    off = FakeScreen(has_templates={"a": True})
    assert _clear_filter(off, "a", "a_on", lambda: None, _nop_sleep) == "off"
    assert _clear_filter(FakeScreen(), "a", "a_on", lambda: None, _nop_sleep) == "unknown"
    stuck = FakeScreen(has_templates={"a": False}, find_templates={"a_on": (0.5, 0.5)})
    assert _clear_filter(stuck, "a", "a_on", lambda: None, _nop_sleep) == "stuck"


def test_busy_skips_a_row_named_like_a_never_upgrade_item(monkeypatch):
    from cocmacro.upgrades import NAME_DY, ROW_PITCH
    scr = _HeroScreen(skip_arrojatroncos=(0.82, ROW[1] + NAME_DY))
    ok, _ = _run(monkeypatch, scr)
    assert ok is True
    assert (ROW[0], ROW[1] + ROW_PITCH) in scr.clicks and ROW not in scr.clicks


def test_several_forbidden_rows_in_a_row_are_all_skipped(monkeypatch):
    from cocmacro.upgrades import NAME_DY, ROW_PITCH
    scr = _HeroScreen(skip_arrojatroncos=(0.82, ROW[1] + NAME_DY),
                      skip_destructor=(0.82, ROW[1] + ROW_PITCH + NAME_DY),
                      skip_tiradora=(0.82, ROW[1] + 2 * ROW_PITCH + NAME_DY))
    ok, _ = _run(monkeypatch, scr)
    assert ok is True and (ROW[0], ROW[1] + 3 * ROW_PITCH) in scr.clicks
    for k in range(3):
        assert (ROW[0], ROW[1] + k * ROW_PITCH) not in scr.clicks


def test_a_single_missed_look_does_not_let_a_forbidden_row_through(monkeypatch):
    """The name is not seen on the first look (list still drawing) but is on the second: the row is skipped."""
    from cocmacro.upgrades import NAME_DY, ROW_PITCH
    looks = iter([None, (0.82, ROW[1] + NAME_DY)])
    scr = _HeroScreen(skip_arrojatroncos=lambda: next(looks, None))
    ok, _ = _run(monkeypatch, scr)
    assert ok is True and ROW not in scr.clicks and (ROW[0], ROW[1] + ROW_PITCH) in scr.clicks


def test_never_upgrade_name_on_another_row_does_not_block_this_one(monkeypatch):
    scr = _HeroScreen(skip_destructor=(0.82, 0.60))               # far from the first row
    _run(monkeypatch, scr)
    assert ROW in scr.clicks


def test_allowed_row_gives_up_when_the_list_ends():
    from cocmacro.upgrades import NAME_DY, _allowed_row
    first = (0.87, 0.80)
    scr = FakeScreen(find_templates={"skip_tiradora": (0.82, first[1] + NAME_DY)})
    assert _allowed_row(scr, first) is None                       # the next row would be on the tabs
    assert _allowed_row(FakeScreen(), first) == first


def test_menu_opened_looks_a_few_times_before_giving_up():
    from cocmacro.upgrades import _menu_opened
    looks = iter([False, False, True])
    scr = FakeScreen(has_templates={"menu_close_x": lambda: next(looks)})
    pauses = []
    assert _menu_opened(scr, pauses.append) is True
    assert pauses == [0.5, 0.5]                          # it waited between the looks, not after the last one


def test_menu_opened_says_no_after_every_look_failed():
    from cocmacro.upgrades import _menu_opened
    scr = FakeScreen(has_templates={"menu_close_x": False})
    pauses = []
    assert _menu_opened(scr, pauses.append, tries=4) is False
    assert len(pauses) == 3
