"""Read the game's numbers (loot, damage %) with glyph templates.

The game font is fixed, so each digit is segmented as a connected component of the
near-white pixels and matched against averaged glyph templates learned from real
captures (scripts/build_glyphs.py -> cocmacro/glyphs.npz). Generic OCR (RapidOCR)
was tried first and misread this font (e.g. "736 480" -> "08t 952"). Leave-one-frame-out check
on 116 labelled digits: 0 errors, so the in-sample fixture tests are not just memorisation.
"""
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

GLYPH_FILE = Path(__file__).with_name("glyphs.npz")
THRESH = 190          # green and red above this = text (also the cut the glyph samples are made with)
TINT_SLACK = 60       # blue may be this far below the cut: tinted (pale yellow) text, see _text_mask
FALLBACK_THRESH = (170, 150, 205)   # light village skins merge background into the digits at one cut or another
CLOCK_THRESH = 150    # the battle clock sits on a dark bar
GW, GH = 12, 18       # normalised glyph size
MAX_DIST = 0.28       # mean abs diff above this -> glyph unknown -> None
ASPECT_W = 0.5
MIN_MARGIN = 0.02      # nearest other digit must be at least this much further than the best match


def parse_digits(text: str) -> int | None:
    """'3 482 103' / '335.532' / '1545' -> int; anything else -> None."""
    cleaned = "".join(ch for ch in text if ch not in "   .,")
    return int(cleaned) if cleaned.isdigit() else None


def _crop(img: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = region
    return img[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def _split_touching(patch: np.ndarray, ref_w: float) -> list[np.ndarray]:
    """A blob about two (or three) digits wide is touching digits: cut it at the thinnest columns."""
    h, w = patch.shape
    parts = int(round(w / ref_w))
    if parts < 2 or w < 1.55 * ref_w or w < 1.1 * h:      # a lone digit is never wider than it is tall (many thin 1s shrink ref_w)
        return [patch]
    cols = patch.sum(axis=0)
    cuts, prev = [], 0
    for k in range(1, parts):
        centre = int(round(w * k / parts))
        lo, hi = max(prev + 2, centre - max(2, int(0.25 * ref_w))), min(w - 2, centre + max(2, int(0.25 * ref_w)))
        if hi <= lo:
            return [patch]
        cut = lo + int(np.argmin(cols[lo:hi + 1]))
        cuts.append(cut)
        prev = cut
    out, start = [], 0
    for cut in cuts + [w]:
        piece = patch[:, start:cut]
        ys, xs = np.nonzero(piece)
        if len(xs):
            out.append(piece[ys.min():ys.max() + 1, xs.min():xs.max() + 1])
        start = cut
    return out or [patch]


def _text_mask(crop: np.ndarray, thresh: int) -> np.ndarray:
    """Pixels of the number. Green and red must clear the cut; blue only `TINT_SLACK` below it: the game
    tints the loot numbers (gold pale yellow, blue ~195-208 where white text has 255), and a cut on the
    lowest channel broke those digits up or nibbled a 5 into a 9 (live 2026-11: gold unreadable in 22 of
    24 saved failures). The coin icon is a saturated yellow with far less blue and stays out."""
    px = crop.astype(np.int16)
    return ((px[..., 1:].min(axis=2) > thresh) & (px[..., 0] > thresh - TINT_SLACK)).astype(np.uint8)


def segment(crop: np.ndarray, thresh: int = THRESH) -> list[np.ndarray]:
    """Left-to-right list of binary glyph images (tight bounding boxes)."""
    mask = _text_mask(crop, thresh)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [(stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH],
              stats[i, cv2.CC_STAT_HEIGHT], i) for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 6]
    if not comps:
        return []
    tallest = max(c[3] for c in comps)
    comps = [c for c in comps if c[3] >= 0.75 * tallest]
    comps.sort(key=lambda c: c[0])
    ref_w = float(np.median([c[2] for c in comps]))
    out: list[np.ndarray] = []
    for x, y, w, h, i in comps:
        out.extend(_split_touching((labels[y:y + h, x:x + w] == i).astype(np.uint8), ref_w))
    return out


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


def classify_in(glyph: np.ndarray, imgs: np.ndarray, aspect: np.ndarray, labels: np.ndarray) -> str | None:
    """Nearest learned sample. Unknown when too far, or when the nearest sample of another digit is
    almost as close (better to skip a village than to read 2860193 for 2660193)."""
    feat, asp = features(glyph)
    d = np.abs(imgs - feat).mean(axis=(1, 2)) + ASPECT_W * np.abs(aspect - asp)
    i = int(d.argmin())
    if d[i] > MAX_DIST:
        return None
    other = labels != labels[i]
    if other.any() and d[other].min() - d[i] < MIN_MARGIN:
        return None
    return str(labels[i])


def classify(glyph: np.ndarray) -> str | None:
    t = _load()
    return classify_in(glyph, t["imgs"], t["aspect"], t["labels"])


def _usable(crop: np.ndarray) -> bool:
    return crop.shape[0] >= 4 and crop.shape[1] >= 4      # empty/degenerate region: nothing to read


def read_crop(crop: np.ndarray) -> int | None:
    """Digits in an already cropped region of the loot / damage numbers."""
    if not _usable(crop):
        return None
    reads: list[int] = []
    for thresh in (THRESH, *FALLBACK_THRESH):
        glyphs = segment(crop, thresh)
        chars = [classify(g) for g in glyphs]
        if glyphs and None not in chars:
            value = parse_digits("".join(chars).removesuffix("%"))      # the damage zone often includes the % sign
            if value is not None:
                reads.append(value)
    return _agree(reads)


def _agree(reads: list[int]) -> int | None:
    """One value out of the readings of the different cuts. All equal: that one. Readings with fewer digits
    than the longest are a speck or a number that lost a glyph at a strict cut: they never win, and the
    longest then needs two cuts behind it. When cuts disagree on a number of the same length (one cut
    nibbled a 5 into a 9) the value needs three cuts against the dissenting one: two cuts close together
    can make the same mistake, and a wrong number is worse than a skipped village."""
    if not reads:
        return None
    if len(set(reads)) == 1:
        return reads[0]
    digits = max(len(str(v)) for v in reads)
    ranked = Counter(v for v in reads if len(str(v)) == digits).most_common()
    value, votes = ranked[0]
    return value if votes >= (2 if len(ranked) == 1 else 3) else None


def read_number(img: np.ndarray, region: tuple[float, float, float, float]) -> int | None:
    return read_crop(_crop(img, region))


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
    if not _usable(crop):
        return None
    mask = (crop.min(axis=2) > CLOCK_THRESH).astype(np.uint8)
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
