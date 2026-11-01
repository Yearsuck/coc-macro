from cocmacro import config, decisions

CFG = config.Config()


def test_attack_needs_both():
    assert decisions.should_attack(600_000, 400_000, CFG) is False
    assert decisions.should_attack(400_000, 600_000, CFG) is False
    assert decisions.should_attack(600_000, 600_000, CFG) is True
    assert decisions.should_attack(500_000, 500_000, CFG) is False


def test_none_never_attacks():
    assert decisions.should_attack(None, 900_000, CFG) is False
    assert decisions.should_attack(900_000, None, CFG) is False


def test_surrender_threshold():
    assert decisions.should_surrender(50, CFG) is False
    assert decisions.should_surrender(51, CFG) is True
    assert decisions.should_surrender(None, CFG) is False
