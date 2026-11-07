import pytest

from cocmacro import config


def test_config_defaults(tmp_path):
    cfg = config.load(tmp_path / "missing.json")
    assert cfg.gold_min == 500000
    assert cfg.elixir_min == 500000
    assert cfg.surrender_pct == 50


def test_config_save_load(tmp_path):
    cfg = config.Config(gold_min=700000, surrender_pct=60, aspect=1.78,
                        buttons={"battle": (0.05, 0.9)},
                        regions={"gold": (0.8, 0.05, 0.9, 0.1), "elixir": (0.1, 0.2, 0.2, 0.3),
                                 "damage": (0.5, 0.5, 0.6, 0.6), "timer": (0.45, 0.04, 0.55, 0.08)})
    p = tmp_path / "c.json"
    config.save(cfg, p)
    assert config.load(p) == cfg


def test_default_time_and_timer_region(tmp_path):
    cfg = config.load(tmp_path / "missing.json")
    assert cfg.surrender_time_s == 140
    assert "timer" in cfg.regions


def test_old_config_gets_timer_region(tmp_path):
    p = tmp_path / "old.json"
    p.write_text('{"gold_min": 1, "regions": {"gold": [0.1, 0.1, 0.2, 0.2]}}')
    cfg = config.load(p)
    assert cfg.regions["gold"] == (0.1, 0.1, 0.2, 0.2)
    assert cfg.regions["timer"] == config.DEFAULT_REGIONS["timer"]
    assert cfg.surrender_time_s == 140


def test_parse_mmss():
    assert config.parse_mmss("2:20") == 140
    assert config.parse_mmss("0:45") == 45
    assert config.parse_mmss("") == 0
    for bad in ("2:75", "abc", "2:", "-1:00"):
        with pytest.raises(ValueError):
            config.parse_mmss(bad)
    assert config.format_mmss(140) == "2:20"


def test_update_check_on_by_default_and_saved(tmp_path):
    assert config.load(tmp_path / "missing.json").auto_check_updates is True
    cfg = config.Config(auto_check_updates=False)
    config.save(cfg, tmp_path / "c.json")
    assert config.load(tmp_path / "c.json").auto_check_updates is False


def test_region_ok():
    assert config.region_ok((0.4, 0.1, 0.5, 0.2)) is True
    assert config.region_ok((0.5, 0.5, 0.5, 0.5)) is False       # a click, not a drag
    assert config.region_ok((0.6, 0.6, 0.5, 0.5)) is False       # inverted


def test_load_repairs_an_empty_timer_region(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"regions": {"timer": [0.5195, 0.0766, 0.5195, 0.0766]}}')
    assert config.load(p).regions["timer"] == config.DEFAULT_REGIONS["timer"]


def test_default_regions_cover_every_number_zone(tmp_path):
    cfg = config.load(tmp_path / "missing.json")
    assert set(cfg.regions) == {"gold", "elixir", "damage", "timer"}
    assert all(config.region_ok(r) for r in cfg.regions.values())


def test_suggested_zone_is_the_default_one():
    from cocmacro import calibrate
    assert calibrate.suggested_region("gold") == config.DEFAULT_REGIONS["gold"]
    assert calibrate.suggested_region("battle") is None


def test_mode_defaults_and_old_config_loads(tmp_path):
    p = tmp_path / "old.json"
    p.write_text('{"gold_min": 600000}', encoding="utf-8")
    cfg = config.load(p)
    assert cfg.mode == "none" and cfg.stop_when_full is False
    config.save(config.Config(mode="walls", stop_when_full=True), p)
    again = config.load(p)
    assert again.mode == "walls" and again.stop_when_full is True


def test_prioritize_heroes_defaults_off_and_round_trips(tmp_path):
    from cocmacro import config
    assert config.Config().prioritize_heroes is False
    cfg = config.Config()
    cfg.prioritize_heroes = True
    config.save(cfg, tmp_path / "c.json")
    assert config.load(tmp_path / "c.json").prioritize_heroes is True
