"""Learn digit glyph samples -> cocmacro/glyphs.npz, then check generalisation.
Sources: tests/fixtures/labels.json (frames + regions) and tests/fixtures/crops/*_<value>.png.
Run: PYTHONPATH=. python scripts/build_glyphs.py"""
import json
from pathlib import Path

import cv2
import numpy as np

from cocmacro import ocr

FIX = Path("tests/fixtures")
data = json.loads((FIX / "labels.json").read_text())

sources = []          # (source name, expected digits, glyph feature list)
for fname, key, value in data["labels"]:
    img = cv2.imread(str(FIX / fname))
    sources.append((f"{fname}/{key}", str(value), ocr.segment(ocr._crop(img, tuple(data["regions"][key])))))
for path in sorted((FIX / "crops").glob("*.png")):
    sources.append((path.name, path.stem.rsplit("_", 1)[1], ocr.segment(cv2.imread(str(path)))))

imgs, aspect, labels, owner = [], [], [], []
for name, digits, glyphs in sources:
    if len(glyphs) != len(digits):
        raise SystemExit(f"{name}: {len(glyphs)} glyphs for '{digits}'")
    for g, ch in zip(glyphs, digits):
        f, a = ocr.features(g)
        imgs.append(f); aspect.append(a); labels.append(ch); owner.append(name)
imgs, aspect, labels, owner = np.stack(imgs), np.array(aspect), np.array(labels), np.array(owner)
np.savez(ocr.GLYPH_FILE, imgs=imgs, aspect=aspect, labels=labels)
print("samples:", len(labels), "classes:", "".join(sorted(set(labels))))

# leave-one-source-out: classify each source's glyphs using only the other sources
wrong = rejected = total = 0
for name, digits, glyphs in sources:
    keep = owner != name
    for g, ch in zip(glyphs, digits):
        total += 1
        out = ocr.classify_in(g, imgs[keep], aspect[keep], labels[keep])
        if out is None:
            rejected += 1
        elif out != ch:
            wrong += 1
            print("WRONG", name, "want", ch, "got", out)
print(f"leave-one-source-out: {total} digits, {wrong} wrong, {rejected} rejected (skipped village)")
