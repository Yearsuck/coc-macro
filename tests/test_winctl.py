import pytest

from cocmacro import winctl


class FakeUser32:
    """Minimal user32 stand-in: a minimized window that does (or does not) come back."""

    def __init__(self, iconic=True, restores=True):
        self.iconic, self.restores, self.calls = iconic, restores, []

    def IsIconic(self, hwnd):
        return 1 if self.iconic else 0

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("show", cmd))
        if self.restores:
            self.iconic = False

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):
        self.calls.append(("pos", after, flags))


def test_minimized_window_is_restored_without_taking_focus():
    api = FakeUser32()
    assert winctl.restore_if_minimized(winctl.GameWindow(1, 0, 0), api=api, sleep=lambda s: None) is True
    assert ("show", winctl.SW_SHOWNOACTIVATE) in api.calls   # never SW_RESTORE/SHOW: those activate
    pos = [c for c in api.calls if c[0] == "pos"][0]
    assert pos[1] == winctl.HWND_BOTTOM and pos[2] & winctl.SWP_NOACTIVATE


def test_visible_window_is_left_alone():
    api = FakeUser32(iconic=False)
    assert winctl.restore_if_minimized(winctl.GameWindow(1, 10, 10), api=api, sleep=lambda s: None) is False
    assert api.calls == []


def test_window_that_stays_minimized_raises():
    api = FakeUser32(restores=False)
    with pytest.raises(winctl.WindowMinimized):
        winctl.restore_if_minimized(winctl.GameWindow(1, 0, 0), api=api, sleep=lambda s: None)
