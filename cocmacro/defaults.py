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
}


def apply(cfg: Config, tpl_dir: Path) -> bool:
    """Fill in the missing buttons and button images. True if anything changed."""
    tpl_dir = Path(tpl_dir)
    changed = False
    for name, pos in BUTTONS.items():
        if name not in cfg.buttons:
            cfg.buttons[name] = pos
            changed = True
    for src in sorted(DIR.glob("*.png")):
        dst = tpl_dir / src.name
        if not dst.exists():
            tpl_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            changed = True
    return changed
