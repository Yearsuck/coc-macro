"""Needs the game open: python -m pytest -m integration -v

Minimized-window behaviour (WindowMinimized) is manual-only: do not minimize from tests.
"""
import numpy as np
import pytest

from cocmacro import winctl

pytestmark = pytest.mark.integration


def test_find_window():
    win = winctl.find_game_window()
    assert win.client_w > 500
    assert win.client_h > 300


def test_capture_shape():
    win = winctl.find_game_window()
    img = winctl.capture(win)
    assert img.shape == (win.client_h, win.client_w, 3)
    assert img.dtype == np.uint8
    assert img.max() > 0
