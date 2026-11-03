"""Checks run before starting the bot; returns a user-facing message or None."""
from pathlib import Path

from cocmacro import calibrate, recorder, winctl
from cocmacro.config import Config, region_ok

NEEDED_TEMPLATES = ["battle", "next", "ok", "back"]


def calibration_missing(cfg: Config, tpl_dir: Path) -> list[str]:
    """Names of the buttons, zones and button templates that are not calibrated (usable) yet."""
    tpl_dir = Path(tpl_dir)
    missing = [n for n in calibrate.BUTTONS if n not in cfg.buttons] + \
              [n for n in calibrate.REGIONS if n not in cfg.regions or not region_ok(cfg.regions[n])]
    missing += [n for n in NEEDED_TEMPLATES if not (tpl_dir / f"{n}.png").exists()]
    if not any((tpl_dir / f"{n}.png").exists() for n in ("surrender", "end")):
        missing.append("surrender")
    return missing


def check(cfg: Config, tpl_dir: Path, rec_dir: Path, dry_run: bool,
          find_window=winctl.find_game_window, capture=winctl.capture) -> str | None:
    try:
        win = find_window()
        capture(win)
    except (winctl.WindowNotFound, winctl.WindowMinimized) as e:
        return str(e)
    missing = calibration_missing(cfg, tpl_dir)
    if missing:
        return "Falta calibrar: " + ", ".join(missing)
    if not dry_run:
        try:
            rec = recorder.load_recording(cfg.deployment, rec_dir)
        except (FileNotFoundError, KeyError):
            return f"No hay despliegue grabado con el nombre '{cfg.deployment}'"
        if not rec.events:
            return f"El despliegue '{cfg.deployment}' esta vacio"
    return None
