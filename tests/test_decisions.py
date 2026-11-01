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


def test_surrender_on_time_left():
    assert decisions.should_surrender(10, CFG, time_left=139) is True    # < 2:20
    assert decisions.should_surrender(10, CFG, time_left=140) is False
    assert decisions.should_surrender(10, CFG, time_left=None) is False
    assert decisions.should_surrender(None, CFG, time_left=100) is True


def test_time_rule_can_be_disabled():
    cfg = config.Config(surrender_time_s=0)
    assert decisions.should_surrender(10, cfg, time_left=5) is False
    assert decisions.should_surrender(60, cfg, time_left=5) is True      # % rule still on
