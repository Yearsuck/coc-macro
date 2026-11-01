"""Frames at a fixed reference size, whatever the size of the game window.

Button templates and OCR glyphs are pixel-scale dependent and were cut at 1296 px wide.
The window can be resized (same aspect ratio), so every capture is rescaled to that width
before matching or reading.
"""
import cv2
import numpy as np

from cocmacro import winctl

REF_W = 1296


def normalize(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if w == REF_W:
        return frame
    interp = cv2.INTER_AREA if w > REF_W else cv2.INTER_CUBIC
    return cv2.resize(frame, (REF_W, round(h * REF_W / w)), interpolation=interp)


def grab(win: winctl.GameWindow) -> np.ndarray:
    return normalize(winctl.capture(win))
