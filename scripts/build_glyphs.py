"""Learn digit glyph templates from tests/fixtures/labels.json -> cocmacro/glyphs.npz.
Run: python scripts/build_glyphs.py   (needs PYTHONPATH=.)"""
import json
from pathlib import Path

import cv2
import numpy as np

from cocmacro import ocr

FIX = Path("tests/fixtures")
data = json.loads((FIX / "labels.json").read_text())
samples: dict[str, list] = {}
for fname, key, value in data["labels"]:
    img = cv2.imread(str(FIX / fname))
    glyphs = ocr.segment(ocr._crop(img, tuple(data["regions"][key])))
    digits = str(value)
    if len(glyphs) != len(digits):
        raise SystemExit(f"{fname}/{key}: {len(glyphs)} glyphs for '{digits}'")
    for g, ch in zip(glyphs, digits):
        samples.setdefault(ch, []).append(ocr.features(g))
labels = sorted(samples)
imgs = np.stack([np.mean([f[0] for f in samples[c]], axis=0) for c in labels])
aspect = np.array([np.mean([f[1] for f in samples[c]]) for c in labels])
np.savez(ocr.GLYPH_FILE, imgs=imgs, aspect=aspect, labels=np.array(labels))
print("classes:", "".join(labels), "samples:", {c: len(samples[c]) for c in labels})
