"""Calibration shipped with the app, so a fresh install works without calibrating.

Measured on the Spanish game in a 16:9 Google Play Games window (button positions are relative,
the button images are in defaults/templates). Only what is missing is filled in: a user's own
calibration is never overwritten. A different language or window proportion needs a recalibration.
"""
import shutil
from pathlib import Path

from cocmacro.config import Config

DIR = Path(__file__).with_name("defaults") / "templates"
BUTTONS = {
    "battle": (0.0747, 0.8822), "find": (0.1388, 0.6972), "attack": (0.8381, 0.8598),
    "next": (0.9096, 0.7551), "end": (0.0756, 0.7915), "ok": (0.5878, 0.6168),
    "back": (0.4984, 0.8617), "surrender": (0.0705, 0.7813),
    # village upgrade UI (2026-11-05 captures, 1296x729; to be refined on the real game)
    "build": (0.945, 0.905), "build_close": (0.984, 0.032), "filter": (0.7595, 0.032),
    "wall_spot": (0.575, 0.270), "wall_more": (0.500, 0.800), "wall_remove": (0.339, 0.800),
    "wall_add1": (0.500, 0.800),
    "wall_up_gold": (0.580, 0.809), "wall_up_elixir": (0.661, 0.809),
    # Construir menu tabs (the forge / hero-equipment tab at x 0.899 is deliberately NOT here: never upgraded)
    "tab_builders": (0.764, 0.930), "tab_researchers": (0.833, 0.930), "tab_pets": (0.967, 0.930),
    "upgrade_confirm": (0.698, 0.850), "upgrade_window_close": (0.883, 0.075),
    "dialog_close": (0.669, 0.333),      # X of the "No hay constructores libres" notice
    "reload_inactive": (0.355, 0.571),   # VOLVER A CARGAR of the inactivity dialog
}
REGIONS = {
    "free_builders": (0.905, 0.797, 0.945, 0.822), "free_researchers": (0.948, 0.797, 0.988, 0.822),
    "wall_title": (0.40, 0.690, 0.60, 0.730),
    "wall_cost_gold": (0.545, 0.745, 0.620, 0.775), "wall_cost_elixir": (0.625, 0.745, 0.700, 0.775),
    "tab_count_builders": (0.739, 0.948, 0.787, 0.985), "tab_count_researchers": (0.809, 0.948, 0.857, 0.985),
    "tab_count_pets": (0.947, 0.948, 0.987, 0.985), "upgrade_cost": (0.66, 0.84, 0.72, 0.885),
    "storage_gold": (0.815, 0.030, 0.950, 0.060), "storage_elixir": (0.815, 0.085, 0.950, 0.115),
    "storage_dark": (0.858, 0.143, 0.968, 0.178),
}


def apply(cfg: Config, tpl_dir: Path) -> bool:
    """Fill in the missing buttons and button images. True if anything changed."""
    tpl_dir = Path(tpl_dir)
    changed = False
    for name, pos in BUTTONS.items():
        if name not in cfg.buttons:
            cfg.buttons[name] = pos
            changed = True
    for name, rect in REGIONS.items():
        if name not in cfg.regions:
            cfg.regions[name] = rect
            changed = True
    for src in sorted(DIR.glob("*.png")):
        dst = tpl_dir / src.name
        if not dst.exists():
            tpl_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            changed = True
    return changed
