import json
import pytest

from cocmacro import accounts, config


def test_valid_file_name():
    assert accounts.valid_file_name("config.json") is True
    assert accounts.valid_file_name("config_1.json") is False      # would collide with config.json (index 1)
    assert accounts.valid_file_name("config_01.json") is False
    assert accounts.valid_file_name("config_02.json") is False
    assert accounts.valid_file_name("config_2.json") is True
    assert accounts.valid_file_name("config_10.json") is True

    # Invalid names and non-strings
    assert accounts.valid_file_name("../x.json") is False
    assert accounts.valid_file_name("config_.json") is False
    assert accounts.valid_file_name("config_abc.json") is False
    assert accounts.valid_file_name("config.json\n") is False
    assert accounts.valid_file_name(123) is False
    assert accounts.valid_file_name(None) is False
    assert accounts.valid_file_name(["config.json"]) is False


def test_load_registry(tmp_path):
    # Missing file returns ["config.json"]
    assert accounts.load_registry(tmp_path) == ["config.json"]

    # Garbage JSON returns ["config.json"]
    reg = tmp_path / accounts.REGISTRY_FILE
    reg.write_text("{bad json: 123", encoding="utf-8")
    assert accounts.load_registry(tmp_path) == ["config.json"]

    # Non-list JSON returns ["config.json"]
    reg.write_text('{"accounts": ["config.json"]}', encoding="utf-8")
    assert accounts.load_registry(tmp_path) == ["config.json"]

    # Drops invalid names, drops duplicates, forces config.json first
    reg.write_text(json.dumps(["config_2.json", "../x.json", "config_2.json"]), encoding="utf-8")
    assert accounts.load_registry(tmp_path) == ["config.json", "config_2.json"]

    # Existing config.json not first is moved to first
    reg.write_text(json.dumps(["config_3.json", "config.json", "config_2.json"]), encoding="utf-8")
    assert accounts.load_registry(tmp_path) == ["config.json", "config_3.json", "config_2.json"]

    # More than 4 valid names capped at MAX_ACCOUNTS (4)
    reg.write_text(json.dumps(["config.json", "config_2.json", "config_3.json", "config_4.json", "config_5.json"]),
                   encoding="utf-8")
    res = accounts.load_registry(tmp_path)
    assert res == ["config.json", "config_2.json", "config_3.json", "config_4.json"]
    assert len(res) == accounts.MAX_ACCOUNTS


def test_save_registry(tmp_path):
    sub = tmp_path / "data"
    accounts.save_registry(sub, ["config.json", "config_2.json"])
    assert (sub / accounts.REGISTRY_FILE).exists()
    assert json.loads((sub / accounts.REGISTRY_FILE).read_text(encoding="utf-8")) == ["config.json", "config_2.json"]


def test_account_index():
    assert accounts.account_index("config.json") == 1
    assert accounts.account_index("config_1.json") == 1
    assert accounts.account_index("config_3.json") == 3
    assert accounts.account_index("config_12.json") == 12
    with pytest.raises(ValueError):
        accounts.account_index("other.json")


def test_next_file(tmp_path):
    # Registry ["config.json"], empty dir -> config_2.json
    assert accounts.next_file(tmp_path, ["config.json"]) == "config_2.json"

    # Registry ["config.json", "config_2.json"] with stale config_5.json on disk -> config_6.json
    (tmp_path / "config_5.json").write_text("{}", encoding="utf-8")
    assert accounts.next_file(tmp_path, ["config.json", "config_2.json"]) == "config_6.json"

    # Closed tab's file stays on disk, so its name is never reused
    (tmp_path / "config_2.json").write_text("{}", encoding="utf-8")
    assert accounts.next_file(tmp_path, ["config.json"]) == "config_6.json"


def test_account_config():
    base = config.Config(
        gold_min=999999,
        mode="walls",
        deployment="recorded_run",
        window_title="Clash of Clans - Base",
        account_name="Base",
        aspect=1.77,
        buttons={"battle": (0.1, 0.2)},
        regions={"gold": (0.1, 0.2, 0.3, 0.4)},
        tpl_size=(0.05, 0.05),
    )
    copy_cfg = accounts.account_config(base)

    # Calibration copied
    assert copy_cfg.aspect == base.aspect
    assert copy_cfg.buttons == base.buttons
    assert copy_cfg.regions == base.regions
    assert copy_cfg.tpl_size == base.tpl_size

    # Independence: mutating copy does not affect base
    copy_cfg.buttons["attack"] = (0.5, 0.5)
    copy_cfg.regions["gold"] = (0.2, 0.3, 0.4, 0.5)
    assert "attack" not in base.buttons
    assert base.regions["gold"] == (0.1, 0.2, 0.3, 0.4)

    # Settings reset to defaults
    assert copy_cfg.gold_min == 500000
    assert copy_cfg.mode == "none"
    assert copy_cfg.deployment == "recorded_run"        # recordings are shared: same attack to start with
    assert copy_cfg.window_title == ""
    assert copy_cfg.account_name == ""


def test_add_account(tmp_path):
    # Setup base config.json with custom calibration
    base = config.Config(buttons={"next": (0.8, 0.8)}, aspect=1.6)
    config.save(base, tmp_path / "config.json")

    # First add creates config_2.json with copied calibration
    file1, cfg1 = accounts.add_account(tmp_path)
    assert file1 == "config_2.json"
    assert cfg1.buttons == {"next": (0.8, 0.8)}
    assert cfg1.aspect == 1.6
    assert (tmp_path / "config_2.json").exists()
    assert accounts.load_registry(tmp_path) == ["config.json", "config_2.json"]

    # Add 2 more -> total 4 accounts
    file2, _ = accounts.add_account(tmp_path)
    assert file2 == "config_3.json"
    file3, _ = accounts.add_account(tmp_path)
    assert file3 == "config_4.json"
    assert accounts.load_registry(tmp_path) == ["config.json", "config_2.json", "config_3.json", "config_4.json"]

    # 5th call (4th add) raises ValueError("max accounts")
    with pytest.raises(ValueError, match="max accounts"):
        accounts.add_account(tmp_path)


def test_add_account_never_overwrites_an_existing_config(tmp_path, monkeypatch):
    config.save(config.Config(), tmp_path / "config.json")
    (tmp_path / "config_2.json").write_text('{"gold_min": 1}', encoding="utf-8")
    monkeypatch.setattr(accounts, "next_file", lambda d, files: "config_2.json")   # a name that is already taken
    with pytest.raises(FileExistsError):
        accounts.add_account(tmp_path)
    assert (tmp_path / "config_2.json").read_text(encoding="utf-8") == '{"gold_min": 1}'
    assert accounts.load_registry(tmp_path) == ["config.json"]


def test_remove_account(tmp_path):
    # Create accounts 1 and 2
    base = config.Config()
    config.save(base, tmp_path / "config.json")
    accounts.save_registry(tmp_path, ["config.json", "config_2.json"])
    (tmp_path / "config_2.json").write_text("{}", encoding="utf-8")

    # Removing config.json raises ValueError and registry is unchanged
    with pytest.raises(ValueError):
        accounts.remove_account(tmp_path, "config.json")
    assert accounts.load_registry(tmp_path) == ["config.json", "config_2.json"]

    # Removing non-registered file raises ValueError
    with pytest.raises(ValueError):
        accounts.remove_account(tmp_path, "config_99.json")

    # Removing config_2.json removes from registry, keeps file on disk
    remaining = accounts.remove_account(tmp_path, "config_2.json")
    assert remaining == ["config.json"]
    assert accounts.load_registry(tmp_path) == ["config.json"]
    assert (tmp_path / "config_2.json").exists()

    # Next add_account does NOT reuse config_2.json (it becomes config_3.json)
    new_file, _ = accounts.add_account(tmp_path)
    assert new_file == "config_3.json"
    assert (tmp_path / "config_3.json").exists()


def test_account_name_from_title():
    assert accounts.account_name_from_title("Clash of Clans - Yearsuckk", "Cuenta 2") == "Yearsuckk"
    assert accounts.account_name_from_title("Other app", "Cuenta 2") == "Cuenta 2"
    assert accounts.account_name_from_title("Clash of Clans", "Cuenta 2") == "Cuenta 2"
    assert accounts.account_name_from_title("Clash of Clans - ", "Cuenta 2") == "Cuenta 2"
    assert accounts.account_name_from_title("Clash of Clans -   ", "Cuenta 2") == "Cuenta 2"
    assert accounts.account_name_from_title("Clash of Clans - Foo - Bar", "Cuenta 2") == "Foo - Bar"


def test_debug_dir(tmp_path):
    assert accounts.debug_dir(tmp_path, "config.json") == tmp_path / "debug" / "1"
    assert accounts.debug_dir(tmp_path, "config_3.json") == tmp_path / "debug" / "3"


def test_saving_over_a_corrupt_registry_keeps_a_copy(tmp_path):
    """A corrupt accounts.json reads as just config.json; the next save must not destroy what was there."""
    (tmp_path / accounts.REGISTRY_FILE).write_text("{not json", encoding="utf-8")
    assert accounts.load_registry(tmp_path) == ["config.json"]
    accounts.save_registry(tmp_path, ["config.json", "config_2.json"])
    assert (tmp_path / (accounts.REGISTRY_FILE + ".bad")).read_text(encoding="utf-8") == "{not json"
    assert accounts.load_registry(tmp_path) == ["config.json", "config_2.json"]


def test_saving_over_a_good_registry_makes_no_backup(tmp_path):
    accounts.save_registry(tmp_path, ["config.json", "config_2.json"])
    accounts.save_registry(tmp_path, ["config.json"])
    assert not (tmp_path / (accounts.REGISTRY_FILE + ".bad")).exists()
