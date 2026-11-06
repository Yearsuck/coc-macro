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


def test_storages_full_needs_both_and_never_guesses(tmp_path, monkeypatch):
    from cocmacro import vision
    g, _ = make(tmp_path, monkeypatch, "f004.png")
    g.cfg.regions.update({"storage_gold": (0.8, 0.03, 0.95, 0.06), "storage_elixir": (0.8, 0.08, 0.95, 0.11)})
    for gold, elixir, expected in ((True, True, True), (True, False, False), (False, True, False),
                                   (True, None, None), (None, False, False), (None, None, None)):
        answers = iter((gold, elixir))
        monkeypatch.setattr(vision, "storage_full", lambda frame, region, hue=None: next(answers))
        assert g.storages_full() is expected


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
