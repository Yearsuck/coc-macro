"""Spike: drag with the game in the background. Usage: spike_drag.py x0 y0 x1 y1 [out_prefix]
Coordinates are relative (0-1). Saves <prefix>_before.png and <prefix>_after.png."""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from cocmacro import winctl

x0, y0, x1, y1 = (float(v) for v in sys.argv[1:5])
prefix = sys.argv[5] if len(sys.argv) > 5 else "spike"
win = winctl.find_game_window()
print("foreground is game:", winctl.is_foreground(win))
before = winctl.capture(win)
cv2.imwrite(f"{prefix}_before.png", before)
winctl.post_mouse(win, "down", x0, y0)
for i in range(1, 11):
    time.sleep(0.03)
    winctl.post_mouse(win, "move", x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10)
winctl.post_mouse(win, "up", x1, y1)
time.sleep(1.0)
after = winctl.capture(win)
cv2.imwrite(f"{prefix}_after.png", after)
diff = np.abs(before.astype(int) - after.astype(int)).sum(axis=2)
print("changed pixel ratio:", round(float((diff > 60).mean()), 3))
