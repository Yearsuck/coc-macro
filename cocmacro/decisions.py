"""Pure decisions: attack this village? surrender now?"""
from cocmacro.config import Config


def should_attack(gold: int | None, elixir: int | None, cfg: Config) -> bool:
    if gold is None or elixir is None:
        return False
    return gold > cfg.gold_min and elixir > cfg.elixir_min


def should_surrender(pct: int | None, cfg: Config, time_left: int | None = None) -> bool:
    """Surrender when damage is above the % threshold OR the battle clock is below the time threshold."""
    by_pct = pct is not None and pct > cfg.surrender_pct
    by_time = cfg.surrender_time_s > 0 and time_left is not None and time_left < cfg.surrender_time_s
    return by_pct or by_time
