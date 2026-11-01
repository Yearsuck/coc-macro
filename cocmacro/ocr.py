"""Read the game's numbers (loot, damage %) with glyph templates.

The game font is fixed, so each digit is segmented as a connected component of the
near-white pixels and matched against averaged glyph templates learned from real
captures (scripts/build_glyphs.py -> cocmacro/glyphs.npz). Generic OCR (RapidOCR)
was tried first and misread this font (e.g. "736 480" -> "08t 952"). Leave-one-frame-out check
on 116 labelled digits: 0 errors, so the in-sample fixture tests are not just memorisation.
"""
from pathlib import Path

import cv2
import numpy as np

GLYPH_FILE = Path(__file__).with_name("glyphs.npz")
THRESH = 150          # min(B,G,R) above this = white text
GW, GH = 12, 18       # normalised glyph size
MAX_DIST = 0.28       # mean abs diff above this -> glyph unknown -> None
ASPECT_W = 0.5


def parse_digits(text: str) -> int | None:
    """'3 482 103' / '335.532' / '1545' -> int; anything else -> None."""
    cleaned = "".join(ch for ch in text if ch not in "   .,")
    return int(cleaned) if cleaned.isdigit() else None


def _crop(img: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = region
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def segment(crop: np.ndarray) -> list[np.ndarray]:
    """Left-to-right list of binary glyph images (tight bounding boxes)."""
    mask = (crop.min(axis=2) > THRESH).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [(stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH],
              stats[i, cv2.CC_STAT_HEIGHT], i) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 6]
    if not comps:
        return []
    tallest = max(c[3] for c in comps)
    comps = [c for c in comps if c[3] >= 0.75 * tallest]
    comps.sort(key=lambda c: c[0])
    return [(labels[y:y + h, x:x + w] == i).astype(np.uint8) for x, y, w, h, i in comps]


def features(glyph: np.ndarray) -> tuple[np.ndarray, float]:
    small = cv2.resize(glyph.astype(np.float32), (GW, GH), interpolation=cv2.INTER_AREA)
    return small, glyph.shape[1] / glyph.shape[0]


_templates: dict | None = None


def _load() -> dict:
    global _templates
    if _templates is None:
        z = np.load(GLYPH_FILE)
        _templates = {"imgs": z["imgs"], "aspect": z["aspect"], "labels": z["labels"]}
    return _templates


def classify(glyph: np.ndarray) -> str | None:
    t = _load()
    feat, asp = features(glyph)
    d = np.abs(t["imgs"] - feat).mean(axis=(1, 2)) + ASPECT_W * np.abs(t["aspect"] - asp)
    i = int(d.argmin())
    return str(t["labels"][i]) if d[i] <= MAX_DIST else None


def read_number(img: np.ndarray, region: tuple[float, float, float, float]) -> int | None:
    glyphs = segment(_crop(img, region))
    if not glyphs:
        return None
    chars = [classify(g) for g in glyphs]
    if None in chars:
        return None
    return parse_digits("".join(chars))


def time_from_groups(minutes: str, seconds: str) -> int | None:
    """Digits before the 'm' and before the 's' of the battle clock -> seconds left."""
    if not seconds.isdigit() or (minutes and not minutes.isdigit()):
        return None
    if minutes and (len(minutes) != 1 or len(seconds) != 2):
        return None
    if not minutes and len(seconds) > 2:
        return None
    sec = int(seconds)
    if sec > 59:
        return None
    return (int(minutes) * 60 if minutes else 0) + sec


def read_time_left(img: np.ndarray, region: tuple[float, float, float, float]) -> int | None:
    """Battle clock ('2m 51s' or '45s') -> seconds left. The letters m/s are shorter than the
    digits (~0.85 of their height), so they are told apart by height and used only as
    separators; smaller specks are ignored."""
    crop = _crop(img, region)
    mask = (crop.min(axis=2) > THRESH).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [(stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH],
              stats[i, cv2.CC_STAT_HEIGHT], i) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 6]
    if not comps:
        return None
    tallest = max(c[3] for c in comps)
    comps = sorted((c for c in comps if c[3] >= 0.65 * tallest), key=lambda c: c[0])
    groups, current = [], ""
    for x, y, w, h, i in comps:
        if h >= 0.92 * tallest:
            ch = classify((labels[y:y + h, x:x + w] == i).astype(np.uint8))
            if ch is None:
                return None
            current += ch
        else:                      # 'm' or 's'
            groups.append(current)
            current = ""
    groups.append(current)         # whatever follows the last letter must be empty
    if groups[-1] != "":
        return None
    if len(groups) == 3:
        return time_from_groups(groups[0], groups[1])
    if len(groups) == 2:
        return time_from_groups("", groups[0])
    return None
