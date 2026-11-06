"""Vision helpers for the village screen (storage bars, builder counters, cost colors)."""
from pathlib import Path

import cv2
import numpy as np

from cocmacro import ocr

Region = tuple[float, float, float, float]
RED_SHARE = 0.08

__all__ = [
    "Region",
    "RED_SHARE",
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
    """True if red-dominant pixels (R>180 and R at least 70 above G and B) are at least RED_SHARE of region."""
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

    b = crop[:, :, 0]
    g = crop[:, :, 1]
    r = crop[:, :, 2]
    # the game's 'cannot pay' red is salmon (about 255,110,110), white text has R close to G and B
    red_mask = (r > 180) & ((r.astype(int) - np.maximum(g, b)) > 70)
    total_pixels = crop.shape[0] * crop.shape[1]
    share = np.count_nonzero(red_mask) / total_pixels
    return bool(share >= RED_SHARE)


def storage_full(frame: np.ndarray, region: Region, hue: tuple[int, int] | None = None) -> bool | None:
    """True if the right-most 6% of the bar region is fill (HSV S>90, V>120, and OpenCV hue inside `hue`
    when given), False if it is track, None if ambiguous or empty. The region must cover the bar only:
    the coin / drop icon at its right end is saturated and would read as fill."""
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

    col_start = min(w - 1, int(w * 0.94))
    right_band = band[:, col_start:]
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
        if len(glyphs) < 2:      # a counter has at least digit, slash, digit
            continue
        feat, asp = ocr.features(glyphs[0])
        dist = float(np.abs(feat - ref).mean() + ocr.ASPECT_W * abs(asp - ref_aspect))
        return 0 if dist <= ZERO_MAX_DIST else 1
    return None


WALL_HSV_LOW, WALL_HSV_HIGH = (85, 25, 110), (110, 95, 215)    # steel-blue walls, measured on real captures
WALL_MIN_AREA = 8000                                            # px at 1296 wide; the block is 25 000+
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
    return x / w, max(0, low - WALL_RISE_PX) / h
