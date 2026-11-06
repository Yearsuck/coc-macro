"""Vision helpers for the village screen (storage bars, builder counters, cost colors)."""
from pathlib import Path

import cv2
import numpy as np

from cocmacro import ocr

Region = tuple[float, float, float, float]
MIN_RED_PX = 10        # fewer red pixels than this is a speck, not a price

__all__ = [
    "Region",
    "MIN_RED_PX",
    "storage_full",
    "free_count",
    "cost_is_red",
]


def _valid(frame, region: Region) -> bool:
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        return False
    if frame.shape[0] < 10 or frame.shape[1] < 10:
        return False
    return region[2] > region[0] and region[3] > region[1]


def cost_is_red(frame: np.ndarray, region: Region) -> bool:
    """True if the price in `region` is in the game's 'cannot pay' colour. Digits are either white (payable) or
    salmon (not payable, about 255,110,110), so the red pixels are compared with the white ones (at least half as
    many) instead of with the size of the region: a short price in a big region must not read as payable."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        return False
    if frame.shape[0] < 10 or frame.shape[1] < 10:
        return False
    x0, y0, x1, y1 = region
    if x1 <= x0 or y1 <= y0:
        return False
    crop = ocr._crop(frame, region)
    if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return False
    px = crop.astype(int)
    b, g, r = px[..., 0], px[..., 1], px[..., 2]
    red = int(np.count_nonzero((r > 180) & ((r - np.maximum(g, b)) > 70)))
    white = int(np.count_nonzero((np.minimum(np.minimum(r, g), b) > 200) & ((px.max(axis=2) - px.min(axis=2)) < 40)))
    return red >= MIN_RED_PX and red * 2 >= white       # payable digits are white and leave no red at all


def storage_full(frame: np.ndarray, region: Region, hue: tuple[int, int] | None = None) -> bool | None:
    """True if the bar is full. The game fills it from the icon (right) towards the left, so full means the
    LEFT end is fill (HSV S>90, V>120, and OpenCV hue inside `hue` when given); False if that end is still
    track, None if ambiguous or empty. The region must cover the bar only: the coin / drop icon at its right
    end is saturated and would always read as fill."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        return None
    if frame.shape[0] < 10 or frame.shape[1] < 10:
        return None
    x0, y0, x1, y1 = region
    if x1 <= x0 or y1 <= y0:
        return None
    crop = ocr._crop(frame, region)
    if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return None

    h, w = crop.shape[:2]
    y0_band = int(h * 0.25)
    y1_band = int(h * 0.75)
    if y1_band <= y0_band:
        y0_band = 0
        y1_band = h

    band = crop[y0_band:y1_band, :]
    if band.size == 0:
        return None

    col_start, col_end = min(w - 1, int(w * 0.06)), max(int(w * 0.12), int(w * 0.06) + 2)
    right_band = band[:, col_start:col_end]
    if right_band.size == 0:
        return None

    right_hsv = cv2.cvtColor(right_band, cv2.COLOR_BGR2HSV)
    n_cols = right_band.shape[1]
    fill_cols = 0
    track_cols = 0

    for c in range(n_cols):
        s = right_hsv[:, c, 1]
        v = right_hsv[:, c, 2]
        saturated = (s > 90) & (v > 120)
        wrong_hue = np.zeros_like(saturated)
        if hue is not None:
            hue_col = right_hsv[:, c, 0]
            wrong_hue = (hue_col < hue[0]) | (hue_col > hue[1])
        fill_share = np.mean(saturated & ~wrong_hue)
        track_share = np.mean((v < 90) | (s < 60) | (saturated & wrong_hue))
        if fill_share >= 0.7:
            fill_cols += 1
        elif track_share >= 0.7:
            track_cols += 1

    if fill_cols / n_cols >= 0.8:
        return True
    if track_cols / n_cols >= 0.8:
        return False
    return None


ZERO_FILE = Path(__file__).with_name("counter_zero.npz")
MIN_COUNTER_GLYPH_H = 9    # px at 1296 wide: village counters are 14 tall, the ones inside the menu 10
ZERO_MAX_DIST = 0.30   # measured: another '0' of the counter ~0.1, any other digit >= 0.6
_zero: tuple[np.ndarray, float] | None = None


def _zero_ref() -> tuple[np.ndarray, float]:
    global _zero
    if _zero is None:
        z = np.load(ZERO_FILE)
        _zero = (z["img"], float(z["aspect"]))
    return _zero


def free_count(frame: np.ndarray, region: Region) -> int | None:
    """Free slots of a 'free/total' counter: 0 when its first digit is the counter's '0', otherwise 1
    (at least one free; the exact number is not needed). None when nothing readable is there.

    The counter font differs from the loot font that ocr.classify knows, so only the zero is recognised
    (by shape, against a reference cut from the real game) and any other digit just means 'some free'.
    """
    if not _valid(frame, region):
        return None
    crop = ocr._crop(frame, region)
    if not ocr._usable(crop):
        return None
    ref, ref_aspect = _zero_ref()
    for thresh in (ocr.THRESH, *ocr.FALLBACK_THRESH):
        glyphs = [g for g in ocr.segment(crop, thresh=thresh) if g.size]
        if not 3 <= len(glyphs) <= 5:      # a counter is digit, slash, digit (up to two digits each)
            continue
        if min(g.shape[0] for g in glyphs) < MIN_COUNTER_GLYPH_H:     # small print of lists and timers is not a counter
            continue
        feat, asp = ocr.features(glyphs[0])
        dist = float(np.abs(feat - ref).mean() + ocr.ASPECT_W * abs(asp - ref_aspect))
        return 0 if dist <= ZERO_MAX_DIST else 1
    return None


WALL_HSV_LOW, WALL_HSV_HIGH = (85, 25, 110), (110, 95, 215)    # steel-blue walls, measured on real captures
WALL_MIN_AREA = 8000                                            # px at 1296 wide; the block is 25 000+
HUD_ZONES = (                  # the game's own buttons: never click a wall spot inside them
    (0.78, 0.0, 1.0, 0.33),    # resource bars, gems, shield timer
    (0.0, 0.0, 0.14, 0.24),    # profile
    (0.0, 0.24, 0.12, 0.66),   # chat, league, events on the left
    (0.0, 0.80, 0.30, 1.0),    # Batalla and the bottom-left buttons
    (0.84, 0.76, 1.0, 1.0),    # Construir and the shop
)
WALL_RISE_PX = 14                                               # click this far above the block's lowest point


def find_wall_spot(frame: np.ndarray) -> tuple[float, float] | None:
    """Relative (x, y) of a wall just above the lowest point of the big block of walls, wherever the camera
    is. None when no block is on screen. The player starts from the lower edge and works upwards."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[0] < 10 or frame.shape[1] < 10:
        return None
    mask = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), WALL_HSV_LOW, WALL_HSV_HIGH)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[best, cv2.CC_STAT_AREA] < WALL_MIN_AREA * (frame.shape[1] / 1296) ** 2:
        return None
    ys, xs = np.nonzero(labels == best)
    low = ys.max()
    x = float(xs[ys >= low - 4].mean())
    h, w = frame.shape[:2]
    spot = x / w, max(0, low - WALL_RISE_PX) / h
    if any(zx0 <= spot[0] <= zx1 and zy0 <= spot[1] <= zy1 for zx0, zy0, zx1, zy1 in HUD_ZONES):
        return None          # the block is under the game's own buttons: pressing there opens the shop
    return spot


LIST_X = (0.80, 0.99)          # the Construir list column (a bit inside the red X side panel)
LIST_Y = (0.07, 0.88)          # below the title, above the four tabs
ROW_MIN_H = 0.008              # the first sand piece of a row is at least ~6 px tall at 729 high
ROW_Y_MAX = 0.84               # a centre below this is on the tabs, not on a row
ROW_H = 0.066                  # a row is ~48 px at 729 high
ROW_X = 0.867


def first_upgrade_row(frame: np.ndarray) -> tuple[float, float] | None:
    """Relative (x, y) of the centre of the first AVAILABLE row of the Construir list. Rows are sand-coloured
    cards; the progress bars of what is already being upgraded are darker or green and the 'Filtrado' /
    'Asignado' banners are other colours, so the first sand band is the top of the first row on any tab (a
    picture or text may split a row into pieces, so only its top edge is used and half a row is added).
    None if the list is not on screen."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[0] < 20 or frame.shape[1] < 20:
        return None
    h, w = frame.shape[:2]
    band = cv2.cvtColor(frame[:, int(w * LIST_X[0]):int(w * LIST_X[1])], cv2.COLOR_BGR2HSV)
    sand = ((band[..., 0] >= 9) & (band[..., 0] <= 17) & (band[..., 1] >= 85) & (band[..., 1] <= 140)
            & (band[..., 2] >= 135))
    frac = sand.mean(axis=1)
    start, bottom = None, int(h * LIST_Y[1])
    for y in range(int(h * LIST_Y[0]), bottom + 1):
        sand_here = y < bottom and frac[y] >= 0.35
        if sand_here and start is None:
            start = y
        elif not sand_here and start is not None:
            if y - start >= h * ROW_MIN_H:
                centre = start / h + ROW_H / 2
                return (ROW_X, centre) if centre <= ROW_Y_MAX else None
            start = None
    return None
