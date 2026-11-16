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
    "dark_storage_full",
    "free_count",
    "cost_is_red",
    "native_dialog",
]

# --- native_dialog thresholds (from the inactivity dialog crop; no server-error capture exists yet) ---
DIALOG_BGR = (30, 28, 25)  # dark grey/brown of the dialog box
DIALOG_TOL = 8             # channel tolerance for dialog dark pixels
DIALOG_MIN_W_FRAC = 0.25   # width 25%-75% of the frame
DIALOG_MAX_W_FRAC = 0.75
DIALOG_MIN_H_FRAC = 0.12   # height 12%-60% of the frame
DIALOG_MAX_H_FRAC = 0.60
DIALOG_CENTRE_MIN = 0.35   # centre within 0.35-0.65 in both axes
DIALOG_CENTRE_MAX = 0.65
DIALOG_MIN_FILL_FRAC = 0.75 # at least 75% of bounding box must be mask pixels
DIALOG_LOWER_FRAC = 0.40   # button text is searched in the lower 40% of the box
DIALOG_BUTTON_B_MIN = 150  # blue text pixels: B >= 150
DIALOG_BUTTON_BR_MIN = 20  # B - R >= 20
DIALOG_BUTTON_R_MAX = 215  # R <= 215 (filters out near-white text)
DIALOG_BUTTON_MIN_PX = 150 # at least 150 blue text pixels


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
    if not region or len(region) != 4:
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


def dark_storage_full(frame: np.ndarray, region: Region) -> bool | None:
    """Dark elixir bar: same idea as `storage_full` (fills from the icon on the right, full = the LEFT end is
    fill) but its fill is dark purple (OpenCV hue ~141, S>130, V 30-100), too dark for the gold / elixir
    gate, and only the lower rows of the bar show it flat (the upper ones carry a highlight). The track
    (not full) is greenish-grey or a different hue. None if the region is invalid or ambiguous."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        return None
    x0, y0, x1, y1 = region
    if x1 <= x0 or y1 <= y0 or frame.shape[0] < 10 or frame.shape[1] < 10:
        return None
    crop = ocr._crop(frame, region)
    if crop.size == 0:
        return None
    h, w = crop.shape[:2]
    band = crop[int(h * 0.62):int(h * 0.92), int(w * 0.02):max(int(w * 0.10), int(w * 0.02) + 2)]
    if band.size == 0:
        return None
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    fill = (hue >= 125) & (hue <= 160) & (sat > 130) & (val >= 30) & (val <= 100)
    share = float(np.mean(fill))
    if share >= 0.8:
        return True
    if share <= 0.2:
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
# Walls of a high level are drawn gold and cream (live 2026-11-16: a 55 000 px block of them was invisible to the blue
# range and walls mode never upgraded anything). Gold is common in a village (buildings, the Batalla button, sand
# skins), so it is only a fallback for when no blue block exists, and a "block" of it that covers a big share of the
# screen is terrain, not walls.
GOLD_WALL_HSV_LOW, GOLD_WALL_HSV_HIGH = (15, 60, 150), (35, 255, 255)
GOLD_WALL_MAX_SHARE = 0.20
GOLD_WALL_DOMINANCE = 3     # gold beats a blue block only when it is this many times bigger (blue clutter, e.g. ice buildings, is not walls)
WALL_MIN_AREA = 8000                                            # px at 1296 wide; the block is 25 000+
HUD_ZONES = (                  # the game's own buttons: never click a wall spot inside them
    (0.78, 0.0, 1.0, 0.33),    # resource bars, gems, shield timer
    (0.0, 0.0, 0.14, 0.24),    # profile
    (0.0, 0.24, 0.12, 0.66),   # chat, league, events on the left
    (0.0, 0.80, 0.30, 1.0),    # Batalla and the bottom-left buttons
    (0.84, 0.76, 1.0, 1.0),    # Construir and the shop
)
WALL_RISE_PX = 14                                               # click this far above the block's lowest point


def _wall_block(frame: np.ndarray, low, high, max_share: float | None = None):
    """(labels, index, area) of the biggest blob of pixels in the colour range that is big enough to be the wall
    block, else None. `max_share` rejects a blob covering more than that share of the frame."""
    mask = cv2.inRange(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV), low, high)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    area = stats[best, cv2.CC_STAT_AREA]
    if area < WALL_MIN_AREA * (frame.shape[1] / 1296) ** 2:
        return None
    if max_share is not None and area > max_share * frame.shape[0] * frame.shape[1]:
        return None
    return labels, best, int(area)


def find_wall_spot(frame: np.ndarray) -> tuple[float, float] | None:
    """Relative (x, y) of a wall just above the lowest point of the big block of walls, wherever the camera
    is. None when no block is on screen. The player starts from the lower edge and works upwards."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[0] < 10 or frame.shape[1] < 10:
        return None
    blue = _wall_block(frame, WALL_HSV_LOW, WALL_HSV_HIGH)
    gold = _wall_block(frame, GOLD_WALL_HSV_LOW, GOLD_WALL_HSV_HIGH, GOLD_WALL_MAX_SHARE)
    # Blue is the case that was always verified: it wins unless gold is clearly the wall block (live: a 55 000 px
    # gold block next to a 6 500 px blue clump of ice buildings).
    use_gold = gold is not None and (blue is None or gold[2] > GOLD_WALL_DOMINANCE * blue[2])
    found = gold if use_gold else blue
    if found is None:
        return None
    labels, best, _ = found
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


def native_dialog(frame) -> tuple[float, float] | None:
    """Find a native Android dialog (inactivity, server error) by shape and return the relative
    (0-1) centre of its blue text button, or None if no dialog is found.

    Thresholds come from the measurements of F7 (inactivity dialog crop; no server-error capture exists yet).
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        return None
    h, w = frame.shape[:2]
    if h < 10 or w < 10:
        return None

    # mask of "dialog dark" pixels = every channel within DIALOG_TOL of DIALOG_BGR
    px = frame.astype(np.int16)
    b, g, r = px[..., 0], px[..., 1], px[..., 2]
    dark_mask = (
        (np.abs(b - DIALOG_BGR[0]) <= DIALOG_TOL)
        & (np.abs(g - DIALOG_BGR[1]) <= DIALOG_TOL)
        & (np.abs(r - DIALOG_BGR[2]) <= DIALOG_TOL)
    ).astype(np.uint8) * 255

    # largest connected component
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark_mask)
    if n < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    bx = stats[best, cv2.CC_STAT_LEFT]
    by = stats[best, cv2.CC_STAT_TOP]
    bw = stats[best, cv2.CC_STAT_WIDTH]
    bh = stats[best, cv2.CC_STAT_HEIGHT]

    # size check: width 25%-75%, height 12%-60%
    if not (DIALOG_MIN_W_FRAC <= bw / w <= DIALOG_MAX_W_FRAC):
        return None
    if not (DIALOG_MIN_H_FRAC <= bh / h <= DIALOG_MAX_H_FRAC):
        return None

    # centre check: centre within 0.35-0.65 of the frame in both axes
    cx = (bx + bw / 2.0) / w
    cy = (by + bh / 2.0) / h
    if not (DIALOG_CENTRE_MIN <= cx <= DIALOG_CENTRE_MAX and DIALOG_CENTRE_MIN <= cy <= DIALOG_CENTRE_MAX):
        return None

    # fill check: at least 75% of the bounding box must be mask pixels
    box_mask = dark_mask[by:by + bh, bx:bx + bw]
    if float(np.mean(box_mask > 0)) < DIALOG_MIN_FILL_FRAC:
        return None

    # inside the lower 40% of that box look for "button blue" text pixels
    lower_top = by + int(bh * (1.0 - DIALOG_LOWER_FRAC))
    lower = frame[lower_top:by + bh, bx:bx + bw]
    if lower.size == 0:
        return None

    lb = lower[..., 0].astype(np.int16)
    lg = lower[..., 1].astype(np.int16)
    lr = lower[..., 2].astype(np.int16)

    blue_mask = (
        (lb >= DIALOG_BUTTON_B_MIN)
        & (lb > lg)
        & (lg > lr)
        & ((lb - lr) >= DIALOG_BUTTON_BR_MIN)
        & (lr <= DIALOG_BUTTON_R_MAX)
    )
    if not np.any(blue_mask):
        return None

    # dilate the blue mask with a 15x5 px rectangle (cv2.dilate) so the letters of one line join
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    dilated = cv2.dilate(blue_mask.astype(np.uint8) * 255, kernel)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(dilated)
    if n_labels < 2:
        return None

    # A cluster is a button when it holds enough ORIGINAL (undilated) blue pixels. With two buttons
    # (CANCELAR / REINTENTAR) the rightmost is taken: Android puts the affirmative action on the right.
    buttons = [i for i in range(1, n_labels)
               if int(np.count_nonzero(blue_mask & (labels == i))) >= DIALOG_BUTTON_MIN_PX]
    if not buttons:
        return None
    best = max(buttons, key=lambda i: stats[i, cv2.CC_STAT_LEFT] + stats[i, cv2.CC_STAT_WIDTH])
    comp_ys, comp_xs = np.nonzero(blue_mask & (labels == best))
    btn_cx = (bx + float(comp_xs.min() + comp_xs.max()) / 2.0) / w
    btn_cy = (lower_top + float(comp_ys.min() + comp_ys.max()) / 2.0) / h
    return (btn_cx, btn_cy)
