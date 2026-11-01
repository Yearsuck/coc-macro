"""Pure decisions: attack this village? surrender now?"""
from cocmacro.config import Config


def should_attack(gold: int | None, elixir: int | None, cfg: Config) -> bool:
    if gold is None or elixir is None:
        return False
    return gold > cfg.gold_min and elixir > cfg.elixir_min


def should_surrender(pct: int | None, cfg: Config) -> bool:
    return pct is not None and pct > cfg.surrender_pct
