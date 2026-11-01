"""Screen detection by template matching (button crops saved during calibration)."""
from pathlib import Path

import cv2
import numpy as np


def _path(name: str, dir: Path) -> Path:
    return Path(dir) / f"{name}.png"


def save_template(name: str, frame: np.ndarray, center: tuple[float, float],
                  size: tuple[float, float], dir: Path) -> None:
    h, w = frame.shape[:2]
    cx, cy = center[0] * w, center[1] * h
    tw, th = size[0] * w, size[1] * h
    x0, x1 = max(0, int(cx - tw / 2)), min(w, int(cx + tw / 2))
    y0, y1 = max(0, int(cy - th / 2)), min(h, int(cy + th / 2))
    Path(dir).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(_path(name, dir)), frame[y0:y1, x0:x1])


def match(frame: np.ndarray, name: str, dir: Path, threshold: float = 0.85) -> bool:
    p = _path(name, dir)
    if not p.exists():
        return False
    tpl = cv2.imread(str(p))
    if tpl is None or tpl.shape[0] > frame.shape[0] or tpl.shape[1] > frame.shape[1]:
        return False
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    return float(res.max()) >= threshold
