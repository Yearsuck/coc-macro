import cv2

from cocmacro import config, defaults, preflight


def test_fresh_install_gets_a_complete_calibration(tmp_path):
    cfg, tpl = config.Config(), tmp_path / "templates"
    assert defaults.apply(cfg, tpl) is True
    assert preflight.calibration_missing(cfg, tpl) == []
    assert all(cv2.imread(str(p)) is not None for p in tpl.glob("*.png"))


def test_second_run_changes_nothing(tmp_path):
    cfg, tpl = config.Config(), tmp_path / "templates"
    defaults.apply(cfg, tpl)
    assert defaults.apply(cfg, tpl) is False


def test_own_calibration_is_never_overwritten(tmp_path):
    tpl = tmp_path / "templates"
    tpl.mkdir()
    (tpl / "ok.png").write_bytes(b"mine")
    cfg = config.Config(aspect=1.5, buttons={"ok": (0.1, 0.2)})
    defaults.apply(cfg, tpl)
    assert (tpl / "ok.png").read_bytes() == b"mine"
    assert cfg.buttons["ok"] == (0.1, 0.2) and cfg.aspect == 1.5
    assert "battle" in cfg.buttons and (tpl / "battle.png").exists()    # the missing ones are filled
