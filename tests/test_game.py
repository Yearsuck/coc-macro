import contextlib
import threading
from pathlib import Path

import cv2
import pytest

from cocmacro import config, game, templates, winctl
from cocmacro.recorder import Recording

FIX = Path(__file__).parent / "fixtures"
WIN = winctl.GameWindow(hwnd=1, client_w=1296, client_h=729)
REGIONS = {"gold": (0.040, 0.106, 0.135, 0.133), "elixir": (0.040, 0.145, 0.135, 0.178),
           "damage": (0.922, 0.774, 0.971, 0.809)}


def make(tmp_path, monkeypatch, frame_name, **cfg_kw):
    frame = cv2.imread(str(FIX / frame_name))
    monkeypatch.setattr(winctl, "capture", lambda win: frame)
    clicks = []
    monkeypatch.setattr(winctl, "click", lambda win, x, y, hold_s=0.08: clicks.append((x, y)))
    cfg = config.Config(aspect=1296 / 729, regions=REGIONS, buttons={"next": (0.909, 0.7517)}, **cfg_kw)
    g = game.RealGame(WIN, cfg, Recording("d", cfg.aspect, []), threading.Event(), tmp_path)
    return g, clicks


def test_reads_resources_and_damage(tmp_path, monkeypatch):
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    assert g.read_resources() == (986486, 183941)
    g2, _ = make(tmp_path, monkeypatch, "f052.png")
    assert g2.read_damage() == 53


def test_screen_is_uses_templates(tmp_path, monkeypatch):
    scout = cv2.imread(str(FIX / "f004.png"))
    templates.save_template("next", scout, (0.909, 0.7517), (0.06, 0.07), tmp_path)
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    assert g.screen_is("scout") is True
    g2, _ = make(tmp_path, monkeypatch, "f019.png")   # in battle: no Siguiente button
    assert g2.screen_is("scout") is False


def test_click_button_uses_calibrated_position(tmp_path, monkeypatch):
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.click_button("next")
    assert clicks == [(0.909, 0.7517)]


def test_any_window_shape_is_accepted_without_recalibrating(tmp_path, monkeypatch):
    """Resizing the window is always proportional for the user: no saved proportion is checked."""
    frame = cv2.imread(str(FIX / "f004.png"))
    monkeypatch.setattr(winctl, "capture", lambda win: frame)
    for cfg in (config.Config(aspect=1.0), config.Config(aspect=None)):
        game.RealGame(WIN, cfg, Recording("d", None, []), threading.Event(), tmp_path)


def test_works_when_the_window_is_smaller_than_at_calibration(tmp_path, monkeypatch):
    """Real bug: window became 951x535 (same aspect) while templates were cut at 1296x729."""
    full = cv2.imread(str(FIX / "f004.png"))
    templates.save_template("next", full, (0.909, 0.7517), (0.06, 0.07), tmp_path)
    small = cv2.resize(full, (951, 535), interpolation=cv2.INTER_AREA)
    monkeypatch.setattr(winctl, "capture", lambda win: small)
    cfg = config.Config(aspect=1296 / 729, regions=REGIONS)
    g = game.RealGame(winctl.GameWindow(1, 951, 535), cfg, Recording("d", cfg.aspect, []),
                      threading.Event(), tmp_path)
    assert g.screen_is("scout") is True
    assert g.read_resources() == (986486, 183941)


def test_dump_debug_keeps_what_it_could_not_read_and_prunes(tmp_path, monkeypatch):
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.debug_dir = tmp_path / "debug"
    g.dump_debug("loot")
    names = sorted(p.name for p in g.debug_dir.iterdir())
    assert len(names) == 4 and any("damage" in n for n in names) and any("gold" in n for n in names) and any("elixir" in n for n in names)
    for _ in range(14):
        g.dump_debug("loot")
    assert len(list(g.debug_dir.iterdir())) == game.DEBUG_KEEP


def test_dump_debug_without_a_dir_does_nothing(tmp_path, monkeypatch):
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.dump_debug("loot")                       # debug_dir is None: must not raise


def test_why_not_reports_template_scores(tmp_path, monkeypatch):
    scout = cv2.imread(str(FIX / "f004.png"))
    templates.save_template("next", scout, (0.909, 0.7517), (0.06, 0.07), tmp_path)
    g, _ = make(tmp_path, monkeypatch, "f052.png")             # a battle frame: no 'Siguiente' on it
    text = g.why_not("scout")
    assert "next" in text and f"{templates.THRESHOLD:.2f}" in text and "1296x729" in text
    g2, _ = make(tmp_path / "vacio", monkeypatch, "f004.png")
    assert "falta" in g2.why_not("scout")                      # no template saved at all


def test_storages_full_needs_all_and_never_guesses(tmp_path, monkeypatch):
    from cocmacro import vision
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.regions.update({"storage_gold": (0.8, 0.03, 0.95, 0.06), "storage_elixir": (0.8, 0.08, 0.95, 0.11),
                          "storage_dark": (0.85, 0.14, 0.97, 0.18)})
    cases = ((True, True, True, True), (True, False, True, False), (False, True, True, False),
             (True, None, True, None), (None, False, True, False), (None, None, None, None),
             (True, True, False, False),     # dark elixir not full blocks the wait
             (True, True, None, True))       # dark elixir unreadable / absent: gold and elixir decide
    for gold, elixir, dark, expected in cases:
        answers = iter((gold, elixir))
        monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: next(answers))
        monkeypatch.setattr(vision, "dark_storage_full", lambda frame, region, d=dark: d)
        assert g.storages_full() is expected


def test_storages_full_without_dark_region_ignores_it(tmp_path, monkeypatch):
    from cocmacro import vision
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.regions.pop("storage_dark", None)
    answers = iter((True, True))
    monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: next(answers))
    assert g.storages_full() is True


def test_free_slots_reads_both_counters(tmp_path, monkeypatch):
    from cocmacro import vision
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.regions.update({"free_builders": (0.9, 0.79, 0.94, 0.82), "free_researchers": (0.95, 0.79, 0.99, 0.82)})
    answers = iter((2, None))
    monkeypatch.setattr(vision, "free_count", lambda frame, region: next(answers))
    assert g.free_slots() == {"builders": 2, "researchers": None}


def test_upgrade_runs_the_routine_of_the_mode_over_a_real_screen(tmp_path, monkeypatch):
    from cocmacro import upgrades
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    seen = {}

    def fake(scr, cfg, log, check, sleep):
        seen["scr"] = scr
        scr.click(0.1, 0.2)
        return True
    monkeypatch.setattr(upgrades, "upgrade_walls", fake)
    assert g.upgrade("walls", lambda m: None, lambda: None) is True
    assert clicks == [(0.1, 0.2)] and seen["scr"].grab().shape[1] == 1296
    assert seen["scr"].find("nope") is None and seen["scr"].has("nope") is False
    assert g.upgrade("none", lambda m: None, lambda: None) is False


def test_zoom_out_stops_as_soon_as_f8_raises(tmp_path, monkeypatch):
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    wheel = []
    monkeypatch.setattr(winctl, "post_wheel", lambda *a: wheel.append(a))
    monkeypatch.setattr(game.time, "sleep", lambda s: None)

    class Stop(Exception):
        pass

    def check():
        raise Stop()
    with pytest.raises(Stop):
        game._Screen(g, check).zoom_out()
    assert wheel == []


def test_zoom_out_gives_the_game_a_few_rounds_before_judging_the_view_stable(tmp_path, monkeypatch):
    """Seen live: the first rounds returned identical pictures because the zoom had not started yet."""
    g, _ = make(tmp_path, monkeypatch, "f004.png")        # always the same picture
    wheel = []
    monkeypatch.setattr(winctl, "post_wheel", lambda *a: wheel.append(a))
    monkeypatch.setattr(game.time, "sleep", lambda s: None)
    game._Screen(g).zoom_out()
    assert len(wheel) >= 3 * 4


def _menu_game(tmp_path, monkeypatch, frame_name, **tpl):
    """RealGame whose 'menu_close_x' / 'upgrade_window' are crops of the scout screen's Siguiente button."""
    frame = cv2.imread(str(FIX / "f004.png"))
    for name in tpl:
        templates.save_template(name, frame, (0.909, 0.7517), (0.06, 0.07), tmp_path)
    g, clicks = make(tmp_path, monkeypatch, frame_name)
    g.cfg.buttons.update({"build_close": (0.984, 0.032), "upgrade_window_close": (0.883, 0.075)})
    return g, clicks


def test_close_menu_presses_the_x_where_it_really_is(tmp_path, monkeypatch):
    g, clicks = _menu_game(tmp_path, monkeypatch, "f004.png", menu_close_x=1)
    g.cfg.buttons["build_close"] = (0.909, 0.7517)                  # the X is found right where it is expected
    assert g.close_menu() is True and clicks == [(0.909, 0.7517)]


def test_close_menu_never_presses_the_corner_for_a_red_x_somewhere_else(tmp_path, monkeypatch):
    """The upgrade window and other dialogs have the same red X; the corner is the gold bar (gem shop)."""
    g, clicks = _menu_game(tmp_path, monkeypatch, "f004.png", menu_close_x=1)
    assert g.close_menu() is False and clicks == []                 # found at (0.909, 0.75), expected at the corner


def test_close_menu_does_nothing_on_a_screen_without_the_x(tmp_path, monkeypatch):
    g, clicks = _menu_game(tmp_path, monkeypatch, "f019.png", menu_close_x=1)
    g.cfg.buttons["build_close"] = (0.909, 0.7517)
    assert g.close_menu() is False and clicks == []


def test_close_menu_closes_a_left_over_upgrade_window_with_its_own_x(tmp_path, monkeypatch):
    g, clicks = _menu_game(tmp_path, monkeypatch, "f004.png", upgrade_window=1, menu_close_x=1)
    assert g.close_menu() is True and clicks == [(0.883, 0.075)]


def test_upgrade_surplus_runs_the_busy_routine_for_builders_only_leaving_one(tmp_path, monkeypatch):
    from cocmacro import upgrades
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    seen = {}

    def fake(scr, cfg, log, check, sleep, only=None, keep=None):
        seen.update(only=only, keep=keep)
        return True
    monkeypatch.setattr(upgrades, "upgrade_busy", fake)
    assert g.upgrade("surplus", lambda m: None, lambda: None) is True
    assert seen == {"only": ("builders",), "keep": {"builders": 1}}


def test_upgrade_busy_passes_the_hero_toggle_but_the_walls_surplus_does_not(tmp_path, monkeypatch):
    from cocmacro import upgrades
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    calls = []
    monkeypatch.setattr(upgrades, "upgrade_busy", lambda *a, **kw: calls.append(kw) or True)
    g.cfg.prioritize_heroes = True
    g.upgrade("busy", lambda s: None, lambda: None)
    g.upgrade("surplus", lambda s: None, lambda: None)
    assert calls[0].get("heroes") is True and "heroes" not in calls[1]


@pytest.fixture(autouse=True)
def _no_real_focus(monkeypatch):
    """The real winctl.focused would call Win32 on a fake window handle."""
    monkeypatch.setattr(winctl, "focused", lambda win, **kw: contextlib.nullcontext())
    monkeypatch.setattr(game.time, "sleep", lambda s: None)


def test_reload_if_disconnected_takes_the_focus_for_the_press(tmp_path, monkeypatch):
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    events = []
    monkeypatch.setattr(templates, "match",
                        lambda frame, name, tpl_dir, threshold=None: name.startswith("reload_inactive") and "click" not in events)

    @contextlib.contextmanager
    def focus(win, **kw):
        events.append("focus")
        yield
        events.append("release")
    monkeypatch.setattr(winctl, "focused", focus)
    monkeypatch.setattr(winctl, "click", lambda win, x, y, hold_s=0.08: events.append("click"))
    assert g.reload_if_disconnected() is True
    assert events == ["focus", "click", "release"]


def test_inactivity_dialog_reflects_the_template(tmp_path, monkeypatch):
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: name.startswith("reload_inactive"))
    assert g.inactivity_dialog() is True
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: False)
    assert g.inactivity_dialog() is False


def test_reload_if_disconnected_clicks_when_template_present(tmp_path, monkeypatch):
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: name.startswith("reload_inactive") and not clicks)
    assert g.reload_if_disconnected() is True
    assert clicks == [(0.355, 0.571)]                       # the dialog is gone after the first tap


def test_reload_if_disconnected_does_nothing_when_absent(tmp_path, monkeypatch):
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: False)
    assert g.reload_if_disconnected() is False
    assert clicks == []


def test_reload_if_disconnected_ignores_other_dialogs_and_templates(tmp_path, monkeypatch):
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: not name.startswith("reload_inactive"))
    assert g.reload_if_disconnected() is False
    assert clicks == []


def test_reload_taps_nearby_points_keeping_the_focus_until_the_dialog_is_gone(tmp_path, monkeypatch):
    """Measured on the real game: the dialog took (0.355, 0.571) in one window and only (0.355, 0.576) in
    another, and ignored everything once the focus had been handed back."""
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    events, taps = [], []

    def click(win, x, y, hold_s=0.08):
        taps.append((round(x, 3), round(y, 3)))
        events.append("click")

    # the dialog is up for the first look and until the third tap has been made
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: len(taps) < 3)

    @contextlib.contextmanager
    def focus(win, **kw):
        events.append("focus")
        yield
        events.append("release")
    monkeypatch.setattr(winctl, "focused", focus)
    monkeypatch.setattr(winctl, "click", click)
    assert g.reload_if_disconnected() is True
    assert taps == [(0.355, 0.571), (0.355, 0.576), (0.355, 0.566)]          # stops once the dialog is gone
    assert events == ["focus", "click", "click", "click", "release"]


def test_reload_gives_up_tapping_after_every_point_and_still_reports_the_press(tmp_path, monkeypatch):
    from cocmacro.game import RELOAD_TAP_OFFSETS
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    taps = []
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: True)       # the dialog never goes
    monkeypatch.setattr(winctl, "click", lambda win, x, y, hold_s=0.08: taps.append((x, y)))
    assert g.reload_if_disconnected() is True              # the bot checks the dialog and presses again
    assert len(taps) == len(RELOAD_TAP_OFFSETS)


def test_the_inactivity_dialog_needs_title_and_body(tmp_path, monkeypatch):
    """Only one of the two texts matching (say a dialog with the same box and another message) is not it."""
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    for only in ("reload_inactive_title", "reload_inactive_body"):
        monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None, only=only: name == only)
        assert g.inactivity_dialog() is False
        assert g.reload_if_disconnected() is False
    assert clicks == []
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: True)
    assert g.inactivity_dialog() is True


def test_f8_during_the_reload_taps_lets_go_at_once(tmp_path, monkeypatch):
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    taps = []
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: True)   # dialog stays
    monkeypatch.setattr(winctl, "click", lambda win, x, y, hold_s=0.08: (taps.append((x, y)), g.stop.set()))
    assert g.reload_if_disconnected() is True
    assert len(taps) == 1                                  # the stop flag ended the sequence after the first tap
