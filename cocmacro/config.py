"""App configuration, stored as JSON."""
import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    gold_min: int = 500000
    elixir_min: int = 500000
    surrender_pct: int = 50
    deployment: str = "default"
    aspect: float | None = None
    buttons: dict[str, tuple[float, float]] = field(default_factory=dict)
    regions: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)
    tpl_size: tuple[float, float] = (0.06, 0.07)


def load(path: Path) -> Config:
    path = Path(path)
    if not path.exists():
        return Config()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Config)}
    cfg = Config(**{k: v for k, v in raw.items() if k in known})
    cfg.buttons = {k: tuple(v) for k, v in cfg.buttons.items()}
    cfg.regions = {k: tuple(v) for k, v in cfg.regions.items()}
    cfg.tpl_size = tuple(cfg.tpl_size)
    return cfg


def save(cfg: Config, path: Path) -> None:
    Path(path).write_text(json.dumps(asdict(cfg), indent=2), encoding="utf-8")
