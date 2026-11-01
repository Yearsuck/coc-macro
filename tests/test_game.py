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


def test_aspect_mismatch_refuses(tmp_path, monkeypatch):
    with pytest.raises(game.CalibrationMismatch):
        frame = cv2.imread(str(FIX / "f004.png"))
        monkeypatch.setattr(winctl, "capture", lambda win: frame)
        cfg = config.Config(aspect=1.0)
        game.RealGame(WIN, cfg, Recording("d", 1.0, []), threading.Event(), tmp_path)


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
