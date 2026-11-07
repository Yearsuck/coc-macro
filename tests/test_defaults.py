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


NEW_BUTTONS = ("build", "build_close", "filter", "wall_spot", "wall_more", "wall_remove",
               "wall_add1", "wall_up_gold", "wall_up_elixir", "tab_builders", "tab_researchers",
               "tab_pets", "upgrade_confirm", "upgrade_window_close", "dialog_close")
NEW_REGIONS = ("storage_gold", "storage_elixir", "free_builders", "free_researchers",
               "wall_title", "wall_cost_gold", "wall_cost_elixir",
               "tab_count_builders", "tab_count_researchers", "tab_count_pets", "upgrade_cost")


def test_defaults_apply_adds_upgrade_buttons_and_regions(tmp_path):
    cfg = config.Config()
    defaults.apply(cfg, tmp_path / "templates")
    assert all(n in cfg.buttons for n in NEW_BUTTONS)
    assert all(n in cfg.regions and config.region_ok(cfg.regions[n]) for n in NEW_REGIONS)


def test_own_upgrade_region_is_never_overwritten(tmp_path):
    cfg = config.Config(regions={"free_builders": (0.1, 0.1, 0.2, 0.2)})
    defaults.apply(cfg, tmp_path / "templates")
    assert cfg.regions["free_builders"] == (0.1, 0.1, 0.2, 0.2)


def test_the_forge_tab_is_never_a_button():
    """The user forbade touching the forge / hero-equipment tab: there is no button to press it."""
    assert not any("forge" in n or "equip" in n for n in defaults.BUTTONS)


def test_reload_inactive_button_and_template_exist():
    assert "reload_inactive" in defaults.BUTTONS
    assert defaults.BUTTONS["reload_inactive"] == (0.355, 0.571)
    assert (defaults.DIR / "reload_inactive_title.png").exists()
    assert (defaults.DIR / "reload_inactive_body.png").exists()
