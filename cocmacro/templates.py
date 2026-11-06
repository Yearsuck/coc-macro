"""Screen detection by template matching (button crops saved during calibration)."""
from pathlib import Path

import cv2
import numpy as np

# Buttons whose lower part is a number that changes (the search price of 'Siguiente' depends on the
# account: 1700 vs 1600): only the top share of the saved crop, the label, is matched.
LABEL_ONLY = {"next": 0.55}


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


THRESHOLD = 0.75


def score(frame: np.ndarray, name: str, dir: Path) -> tuple[float, tuple[float, float]] | None:
    """Best match of the saved button on the frame: (similarity 0-1, relative centre). None if unusable."""
    p = _path(name, dir)
    if not p.exists():
        return None
    tpl = cv2.imread(str(p))
    keep = LABEL_ONLY.get(name)
    if keep and tpl is not None:
        tpl = tpl[: max(8, int(tpl.shape[0] * keep))]
    if tpl is None or tpl.shape[0] > frame.shape[0] or tpl.shape[1] > frame.shape[1]:
        return None
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    _, best, _, (x, y) = cv2.minMaxLoc(res)
    h, w = frame.shape[:2]
    return float(best), ((x + tpl.shape[1] / 2) / w, (y + tpl.shape[0] / 2) / h)


# Pairs that differ only in colour or in one word (selected / not selected, Coste min / max) score
# 0.78-0.79 against each other, so they need a stricter cut than ordinary buttons.
STRICT = 0.88
STRICT_NAMES = {"filter_permanent", "filter_permanent_on", "filter_cost_min", "filter_cost_min_on"}


def threshold_for(name: str) -> float:
    return STRICT if name in STRICT_NAMES else THRESHOLD


def match(frame: np.ndarray, name: str, dir: Path, threshold: float | None = None) -> bool:
    found = score(frame, name, dir)
    return found is not None and found[0] >= (threshold if threshold is not None else threshold_for(name))
