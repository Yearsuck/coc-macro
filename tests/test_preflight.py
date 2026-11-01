import numpy as np

from cocmacro import config, preflight, recorder, winctl
from cocmacro.recorder import Event, Recording

WIN = winctl.GameWindow(1, 1296, 729)
BTN = {n: (0.5, 0.5) for n in ["battle", "find", "attack", "next", "surrender", "ok", "back"]}
REG = {n: (0.1, 0.1, 0.2, 0.2) for n in ["gold", "elixir", "damage", "timer"]}


def good_cfg(**kw):
    return config.Config(aspect=1296 / 729, buttons=dict(BTN), regions=dict(REG), deployment="d", **kw)


def setup(tmp_path, templates=("battle", "next", "ok", "back", "surrender")):
    t = tmp_path / "tpl"
    t.mkdir()
    for n in templates:
        (t / f"{n}.png").write_bytes(b"x")
    r = tmp_path / "rec"
    recorder.save_recording(Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5)]), r)
    return t, r


def check(cfg, t, r, **kw):
    return preflight.check(cfg, t, r, find_window=lambda: WIN,
                           capture=lambda w: np.zeros((1, 1, 3)), **kw)


def test_ok(tmp_path):
    t, r = setup(tmp_path)
    assert check(good_cfg(), t, r, dry_run=False) is None


def test_not_calibrated(tmp_path):
    t, r = setup(tmp_path)
    assert "calibr" in check(config.Config(), t, r, dry_run=False).lower()


def test_missing_template(tmp_path):
    t, r = setup(tmp_path, templates=("battle", "next"))
    assert "calibr" in check(good_cfg(), t, r, dry_run=False).lower()


def test_no_recording(tmp_path):
    t, r = setup(tmp_path)
    cfg = good_cfg()
    cfg.deployment = "otro"
    assert "despliegue" in check(cfg, t, r, dry_run=False).lower()
    assert check(cfg, t, r, dry_run=True) is None


def test_window_missing_and_minimized(tmp_path):
    t, r = setup(tmp_path)

    def nf():
        raise winctl.WindowNotFound("Ventana de Clash of Clans no encontrada")

    def mini(w):
        raise winctl.WindowMinimized("La ventana esta minimizada; no se puede capturar")

    assert "no encontrada" in preflight.check(good_cfg(), t, r, dry_run=False, find_window=nf, capture=lambda w: None)
    assert "minimizada" in preflight.check(good_cfg(), t, r, dry_run=False, find_window=lambda: WIN, capture=mini)


def test_aspect_changed(tmp_path):
    t, r = setup(tmp_path)
    cfg = good_cfg()
    cfg.aspect = 1.0
    assert "proporcion" in check(cfg, t, r, dry_run=False).lower()


def test_empty_region_is_reported(tmp_path):
    t, r = setup(tmp_path)
    cfg = good_cfg()
    cfg.regions["damage"] = (0.5, 0.5, 0.5, 0.5)
    msg = check(cfg, t, r, dry_run=False)
    assert "calibr" in msg.lower() and "damage" in msg


def test_calibration_missing_lists_what_is_not_calibrated(tmp_path):
    t, _ = setup(tmp_path)
    assert preflight.calibration_missing(good_cfg(), t) == []
    cfg = good_cfg()
    del cfg.buttons["next"]
    cfg.regions["gold"] = (0.5, 0.5, 0.5, 0.5)
    assert preflight.calibration_missing(cfg, t) == ["next", "gold"]
    assert "calibrar" not in "".join(preflight.calibration_missing(good_cfg(), tmp_path / "none")).lower()
    assert "battle" in preflight.calibration_missing(good_cfg(), tmp_path / "none")        # templates missing
