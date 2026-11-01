"""Capture the game window every N seconds while the user plays normally.
Usage: capture_session.py OUT_DIR SECONDS [INTERVAL=1.5]"""
import sys
import time
from pathlib import Path

import cv2

from cocmacro import winctl

out = Path(sys.argv[1])
total = float(sys.argv[2])
interval = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
out.mkdir(parents=True, exist_ok=True)
win = winctl.find_game_window()
end, i = time.time() + total, 0
while time.time() < end:
    cv2.imwrite(str(out / f"f{i:04d}.png"), winctl.capture(win))
    i += 1
    time.sleep(interval)
print(f"{i} frames in {out}")
