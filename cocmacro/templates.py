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
STRICT_NAMES = {"filter_permanent", "filter_permanent_on", "filter_cost_min", "filter_cost_min_on",
                "filter_hero", "filter_hero_on", "skip_arrojatroncos", "skip_destructor", "skip_tiradora",
                # the resource filters differ only in their icon colour; 'Muro' in a list row scores >= 0.93 on a
                # wall row and <= 0.80 on any other name
                "filter_gold", "filter_gold_on", "filter_elixir", "filter_elixir_on", "filter_dark", "filter_dark_on",
                "wall_row_name"}


def threshold_for(name: str) -> float:
    return STRICT if name in STRICT_NAMES else THRESHOLD


def find_all(frame: np.ndarray, name: str, dir: Path, threshold: float | None = None) -> list[tuple[float, float]]:
    """Every place where the saved image matches, as relative centres sorted top to bottom (a list shows the same
    word on many rows, `score` only gives the best one). A hit silences the pixels around it, which also score
    high: within half the template's height vertically and half its width horizontally."""
    p = _path(name, dir)
    if not p.exists():
        return []
    tpl = cv2.imread(str(p))
    keep = LABEL_ONLY.get(name)
    if keep and tpl is not None:
        tpl = tpl[: max(8, int(tpl.shape[0] * keep))]
    if tpl is None or tpl.shape[0] > frame.shape[0] or tpl.shape[1] > frame.shape[1]:
        return []
    cut = threshold if threshold is not None else threshold_for(name)
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    th, tw = tpl.shape[:2]
    h, w = frame.shape[:2]
    hits: list[tuple[float, float]] = []
    taken: list[tuple[int, int]] = []
    ys, xs = np.where(res >= cut)
    for i in np.argsort(-res[ys, xs]):          # best first, so a hit suppresses its weaker neighbours
        x, y = int(xs[i]), int(ys[i])
        if any(abs(x - tx) <= tw / 2 and abs(y - ty) <= th / 2 for tx, ty in taken):
            continue
        taken.append((x, y))
        hits.append(((x + tw / 2) / w, (y + th / 2) / h))
    return sorted(hits, key=lambda c: c[1])


# A screen the game draws in more than one way: it is there if ANY of the listed sets is fully matched. The
# 'Mejorar tu ...' window shrinks its title text to fit long names ('Conjunto de explosivos'), so the title
# crop alone misses it (live: score 0.47, the bot logged 'No aparece la ventana de mejora' while it was open);
# its red X and the 'Confirmar' label of the green button never change. Those two are generic (every dialog has
# a red X), so they only count at the spot where this window draws them (relative centre, +-POS_TOL).
POS_TOL = 0.05
# The tab header of the Batalla menu is always at the top of the panel: matched anywhere else it is something else.
BATTLE_MENU_AT = (0.18, 0.065)
ALTERNATIVES = {"battle_menu": ((("battle_menu", BATTLE_MENU_AT),),),
                "upgrade_window": ((("upgrade_window", None),),
                                   (("upgrade_window_x", (0.883, 0.077)), ("upgrade_window_confirm", (0.700, 0.833))))}


def _match_one(frame: np.ndarray, name: str, dir: Path, threshold: float | None, at=None) -> bool:
    found = score(frame, name, dir)
    if found is None or found[0] < (threshold if threshold is not None else threshold_for(name)):
        return False
    return at is None or (abs(found[1][0] - at[0]) <= POS_TOL and abs(found[1][1] - at[1]) <= POS_TOL)


def match(frame: np.ndarray, name: str, dir: Path, threshold: float | None = None) -> bool:
    sets = ALTERNATIVES.get(name, (((name, None),),))
    return any(all(_match_one(frame, n, dir, threshold, at) for n, at in parts) for parts in sets)
