from cocmacro import config


def test_config_defaults(tmp_path):
    cfg = config.load(tmp_path / "missing.json")
    assert cfg.gold_min == 500000
    assert cfg.elixir_min == 500000
    assert cfg.surrender_pct == 50


def test_config_save_load(tmp_path):
    cfg = config.Config(gold_min=700000, surrender_pct=60, aspect=1.78,
                        buttons={"battle": (0.05, 0.9)},
                        regions={"gold": (0.8, 0.05, 0.9, 0.1)})
    p = tmp_path / "c.json"
    config.save(cfg, p)
    assert config.load(p) == cfg
