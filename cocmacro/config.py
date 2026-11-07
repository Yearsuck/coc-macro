"""App configuration, stored as JSON."""
import json
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


# battle clock ("La batalla acaba en: 2m 51s"), measured on real captures
DEFAULT_REGIONS = {
    "gold": (0.040, 0.106, 0.135, 0.133),     # loot digits on the village-search screen
    "elixir": (0.040, 0.145, 0.135, 0.178),
    "damage": (0.922, 0.774, 0.971, 0.809),   # "Dano total" percentage
    "timer": (0.451, 0.045, 0.552, 0.082),
}


@dataclass
class Config:
    gold_min: int = 500000
    elixir_min: int = 500000
    surrender_pct: int = 50
    surrender_time_s: int = 140  # surrender when the clock shows less than this (2:20); 0 = off
    auto_check_updates: bool = True
    mode: str = "none"             # "none" | "walls" | "busy": what to do between attacks
    prioritize_heroes: bool = False  # busy mode: upgrade a hero first (Heroe filter) when one can be upgraded
    stop_when_full: bool = False   # do not attack while the gold and elixir storages are full
    deployment: str = "default"
    window_title: str = ""
    account_name: str = ""
    aspect: float | None = None
    buttons: dict[str, tuple[float, float]] = field(default_factory=dict)
    regions: dict[str, tuple[float, float, float, float]] = field(
        default_factory=lambda: dict(DEFAULT_REGIONS))
    tpl_size: tuple[float, float] = (0.06, 0.07)


def region_ok(r: tuple[float, float, float, float]) -> bool:
    """A real rectangle (at least ~13x7 px at 1296x729), not a click or an inverted drag."""
    return (r[2] - r[0]) >= 0.01 and (r[3] - r[1]) >= 0.01


def load(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in raw.items() if k in known})
    cfg.buttons = {k: tuple(v) for k, v in cfg.buttons.items()}
    cfg.regions = {k: tuple(v) for k, v in cfg.regions.items()}
    for k, v in DEFAULT_REGIONS.items():
        if k not in cfg.regions or not region_ok(cfg.regions[k]):
            cfg.regions[k] = v
    cfg.tpl_size = tuple(cfg.tpl_size)
    return cfg


def save(cfg: Config, path: Path) -> None:
    Path(path).write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")


def parse_mmss(text: str) -> int:
    """'2:20' -> 140. Empty -> 0 (rule off). Anything else raises ValueError."""
    text = text.strip()
    if not text:
        return 0
    m = re.fullmatch(r"(\d+):([0-5]\d)", text)
    if not m:
        raise ValueError(f"Tiempo invalido: '{text}' (usa m:ss, por ejemplo 2:20)")
    return int(m.group(1)) * 60 + int(m.group(2))


def format_mmss(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"
