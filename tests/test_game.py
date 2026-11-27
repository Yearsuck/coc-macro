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


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(game.time, "sleep", lambda s: None)


def test_reload_taps_nearby_points_until_the_dialog_is_gone(tmp_path, monkeypatch):
    """Measured on the real game: the dialog took (0.355, 0.571) in one window and only (0.355, 0.576) in
    another (while routing was not yet understood); the taps stop as soon as the dialog is gone."""
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    taps = []
    monkeypatch.setattr(winctl, "click", lambda win, x, y, hold_s=0.08: taps.append((round(x, 3), round(y, 3))))
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: len(taps) < 3)
    assert g.reload_if_disconnected() is True
    assert taps == [(0.355, 0.571), (0.355, 0.576), (0.355, 0.566)]


def test_reload_holds_the_input_channel_and_never_touches_the_keyboard_focus(tmp_path, monkeypatch):
    import contextlib
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    events = []

    @contextlib.contextmanager
    def channel(stop=None, poll=0.2):
        events.append("hold")
        yield True
        events.append("release")
    monkeypatch.setattr(winctl, "exclusive_input", channel)
    monkeypatch.setattr(winctl, "click", lambda win, x, y, hold_s=0.08: events.append("click"))
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: "click" not in events)
    assert g.reload_if_disconnected() is True
    assert events == ["hold", "click", "release"]
    assert not hasattr(winctl, "focused")                 # no code path that steals the real focus is left


def test_reload_stopped_while_waiting_for_the_input_taps_nothing(tmp_path, monkeypatch):
    import contextlib
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: True)

    @contextlib.contextmanager
    def not_got(stop=None, poll=0.2):
        yield False
    monkeypatch.setattr(winctl, "exclusive_input", not_got)
    assert g.reload_if_disconnected() is True
    assert clicks == []


def test_storage_levels_returns_three_keys_and_storages_full_unchanged(tmp_path, monkeypatch):
    from cocmacro import vision
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.regions.update({"storage_gold": (0.8, 0.03, 0.95, 0.06), "storage_elixir": (0.8, 0.08, 0.95, 0.11),
                          "storage_dark": (0.85, 0.14, 0.97, 0.18)})
    # gold True, elixir False, dark None
    monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: True if hue == (18, 40) else False)
    monkeypatch.setattr(vision, "dark_storage_full", lambda frame, region: None)
    levels = g.storage_levels()
    assert set(levels.keys()) == {"gold", "elixir", "dark"}
    assert levels == {"gold": True, "elixir": False, "dark": None}

    # all full -> True
    monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: True)
    monkeypatch.setattr(vision, "dark_storage_full", lambda frame, region: True)
    assert g.storages_full() is True

    # one False -> False
    monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: True if hue == (18, 40) else False)
    monkeypatch.setattr(vision, "dark_storage_full", lambda frame, region: True)
    assert g.storages_full() is False

    # gold None + elixir True -> None
    monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: None if hue == (18, 40) else True)
    monkeypatch.setattr(vision, "dark_storage_full", lambda frame, region: True)
    assert g.storages_full() is None

    # no dark region -> gold/elixir decide
    g.cfg.regions.pop("storage_dark", None)
    monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: True)
    levels_no_dark = g.storage_levels()
    assert levels_no_dark["dark"] is None
    assert g.storages_full() is True


def test_reload_if_disconnected_unknown_native_dialog(tmp_path, monkeypatch):
    from cocmacro import vision
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.debug_dir = tmp_path / "debug"
    dumped = []
    g.dump_debug = dumped.append
    # inactivity dialog is False
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: False)
    # native dialog returns a point while "up" (until clicked, then None)
    def fake_native(frame):
        return None if clicks else (0.4, 0.5)
    monkeypatch.setattr(vision, "native_dialog", fake_native)

    assert g.any_dialog() is True
    assert g.reload_dialog() == (0.4, 0.5)
    assert g.reload_if_disconnected() is True
    assert clicks == [(0.4, 0.5)]
    assert dumped == ["dialog"]


def test_reload_if_disconnected_inactivity_dialog(tmp_path, monkeypatch):
    from cocmacro import vision
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["reload_inactive"] = (0.355, 0.571)
    dumped = []
    g.dump_debug = dumped.append
    # inactivity dialog is True first, then False after click
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: not clicks and name.startswith("reload_inactive"))
    monkeypatch.setattr(vision, "native_dialog", lambda frame: None)

    assert g.reload_if_disconnected() is True
    assert clicks == [(0.355, 0.571)]
    assert dumped == []   # no dump for inactivity dialog


def test_reload_if_disconnected_no_dialog(tmp_path, monkeypatch):
    from cocmacro import vision
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    dumped = []
    g.dump_debug = dumped.append
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: False)
    monkeypatch.setattr(vision, "native_dialog", lambda frame: None)

    assert g.any_dialog() is False
    assert g.reload_dialog() is None
    assert g.reload_if_disconnected() is False
    assert clicks == []
    assert dumped == []


def test_a_button_pressed_again_right_away_is_pressed_at_another_point(tmp_path, monkeypatch):
    """Live 2026-11-15: 'Siguiente' pressed 4 times in a row at the same point was ignored every time, while a
    press at another point (Terminar batalla) was taken at once. A repeated press must not land on the same
    pixel; a first press, or one after a pause, uses the calibrated point."""
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.buttons["next"], g.cfg.buttons["back"] = (0.91, 0.755), (0.5, 0.86)
    now = [100.0]
    monkeypatch.setattr(game.time, "monotonic", lambda: now[0])
    for _ in range(3):
        g.click_button("next")
        now[0] += 1.0
    assert clicks[0] == pytest.approx((0.91, 0.755))
    assert len(set(clicks)) == 3                                         # three different points
    assert all(abs(x - 0.91) <= 0.012 and abs(y - 0.755) <= 0.01 for x, y in clicks)   # all inside the button
    clicks.clear()
    g.click_button("back")
    assert clicks[-1] == pytest.approx((0.5, 0.86))                      # another button: its own point
    now[0] += game.REPEAT_PRESS_S + 1
    g.click_button("back")
    assert clicks[-1] == pytest.approx((0.5, 0.86))                      # after a pause: the calibrated point again


def test_an_unknown_dialog_seen_in_one_look_only_is_not_pressed(tmp_path, monkeypatch):
    """Review finding: the dialog is found by shape alone, so a screen that matches for one frame must not
    get the game tapped. It has to be there twice, a moment apart."""
    from cocmacro import vision
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    g.dump_debug = lambda reason: None
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: False)
    monkeypatch.setattr(game.time, "sleep", lambda s: None)
    looks = []
    monkeypatch.setattr(vision, "native_dialog", lambda frame: (0.4, 0.5) if not looks.append(1) and len(looks) == 1 else None)
    assert g.reload_if_disconnected() is False
    assert clicks == [] and len(looks) == 2


def test_a_failed_debug_capture_does_not_leave_the_dialog_unpressed(tmp_path, monkeypatch):
    from cocmacro import vision
    g, clicks = make(tmp_path, monkeypatch, "f004.png")
    monkeypatch.setattr(templates, "match", lambda frame, name, tpl_dir, threshold=None: False)
    monkeypatch.setattr(game.time, "sleep", lambda s: None)
    monkeypatch.setattr(vision, "native_dialog", lambda frame: None if clicks else (0.4, 0.5))

    def full_disk(reason):
        raise OSError("disk full")
    g.dump_debug = full_disk
    assert g.reload_if_disconnected() is True
    assert clicks == [(0.4, 0.5)]


def test_cancel_search_presses_volver_only_on_the_search_screen(tmp_path, monkeypatch):
    from cocmacro import defaults
    frames_by_name = {n: cv2.imread(str(FIX / "ui" / f"{n}.png")) for n in ("search_failed", "village_no_menu")}
    clicks, shown = [], ["search_failed"]
    monkeypatch.setattr(winctl, "click", lambda win, x, y: clicks.append((x, y)))
    monkeypatch.setattr(game.frames, "grab", lambda win: frames_by_name[shown[0]])
    g = game.RealGame(None, config.Config(), None, threading.Event(), defaults.DIR)
    assert g.cancel_search() is True and clicks == [pytest.approx((0.055, 0.905), abs=0.005)]
    clicks.clear()
    shown[0] = "village_no_menu"
    assert g.cancel_search() is False and clicks == []


def test_the_open_battle_menu_is_recognised_and_nothing_else_is(tmp_path, monkeypatch):
    """Real capture of the Batalla menu (only its panel kept): it hides the Batalla button, so without this check
    the bot took the village for 'loading' and waited for a scout screen that was not coming."""
    from cocmacro import defaults
    shown = {n: cv2.imread(str(FIX / "ui" / f"{n}.png")) for n in
             ("battle_menu_open", "village_no_menu", "search_failed", "dialog_inactivity", "wall_block_gold")}
    shown["scout"] = cv2.imread(str(FIX / "f004.png"))
    current = ["battle_menu_open"]
    monkeypatch.setattr(game.frames, "grab", lambda win: shown[current[0]])
    g = game.RealGame(None, config.Config(), None, threading.Event(), defaults.DIR)
    assert g.battle_menu_open() is True
    for name in ("village_no_menu", "search_failed", "dialog_inactivity", "wall_block_gold", "scout"):
        current[0] = name
        assert g.battle_menu_open() is False, name
    # the same header drawn somewhere else on the screen is not the menu
    import numpy as np
    moved = np.zeros_like(shown["battle_menu_open"])
    h, w = moved.shape[:2]
    moved[int(0.50 * h):int(0.50 * h) + int(0.15 * h), int(0.45 * w):int(0.45 * w) + int(0.45 * w)] =         shown["battle_menu_open"][int(0.02 * h):int(0.02 * h) + int(0.15 * h), int(0.02 * w):int(0.02 * w) + int(0.45 * w)]
    shown["moved"] = moved
    current[0] = "moved"
    assert g.battle_menu_open() is False


def test_star_bonus_chest_is_opened_and_its_reward_collected(tmp_path, monkeypatch):
    """Real captures of the star bonus (2026-11-27): a chest to tap ('Toca') until it opens, then the reward with a
    green 'Continuar', then the village. One call goes through all of it; the village alone is left untouched."""
    from cocmacro import defaults
    shown = {n: cv2.imread(str(FIX / "ui" / f"{n}.png")) for n in
             ("star_reward_chest", "star_reward_continue", "village_no_menu")}
    sequence = ["star_reward_chest"] * 3 + ["star_reward_continue", "village_no_menu"]
    clicks = []

    def click(win, x, y, hold_s=0.08):
        clicks.append((x, y))
        if len(sequence) > 1:
            sequence.pop(0)

    monkeypatch.setattr(winctl, "click", click)
    monkeypatch.setattr(game.frames, "grab", lambda win: shown[sequence[0]])
    monkeypatch.setattr(game.time, "sleep", lambda s: None)
    g = game.RealGame(None, config.Config(), None, threading.Event(), defaults.DIR)
    assert g.dismiss_popup() is True
    assert len(clicks) == 4
    assert all(c == pytest.approx((0.49, 0.34), abs=0.03) for c in clicks[:3])     # on the chest
    assert clicks[3] == pytest.approx((0.49, 0.855), abs=0.02)                       # Continuar
    clicks.clear()
    assert g.dismiss_popup() is False and clicks == []


def test_deployment_zooms_the_camera_out_first(tmp_path, monkeypatch):
    """Live 2026-11-27: selecting a wall from the list leaves the camera zoomed in, the next attack screen opened
    zoomed too and every recorded tap fell on a building: nothing was deployed."""
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    done = []
    monkeypatch.setattr(game._Screen, "zoom_out", lambda self: done.append("zoom"))
    monkeypatch.setattr(game.player, "play", lambda *a: done.append("play") or True)
    assert g.play_deployment() is True and done == ["zoom", "play"]
