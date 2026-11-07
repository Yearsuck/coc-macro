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


class FakeFocusApi:
    """user32 stand-in for focused(): remembers who has the focus."""

    def __init__(self, foreground=5):
        self.fg, self.calls = foreground, []

    def GetForegroundWindow(self):
        return self.fg

    def keybd_event(self, vk, scan, flags, extra):
        self.calls.append(("key", vk, flags))

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("fg", hwnd))
        self.fg = hwnd
        return 1

    def IsWindow(self, hwnd):
        return 1


def test_focused_takes_the_focus_and_gives_it_back():
    api = FakeFocusApi(foreground=5)
    with winctl.focused(winctl.GameWindow(9, 10, 10), api=api, sleep=lambda s: None):
        assert api.fg == 9
    assert api.fg == 5
    assert [c for c in api.calls if c[0] == "fg"] == [("fg", 9), ("fg", 5)]
    assert ("key", winctl.VK_MENU, 0) in api.calls                     # the Alt tap that unlocks it


def test_focused_leaves_an_already_active_window_alone():
    api = FakeFocusApi(foreground=9)
    with winctl.focused(winctl.GameWindow(9, 10, 10), api=api, sleep=lambda s: None):
        pass
    assert api.calls == []


def test_focused_gives_the_focus_back_even_if_the_body_raises():
    api = FakeFocusApi(foreground=5)
    with pytest.raises(RuntimeError):
        with winctl.focused(winctl.GameWindow(9, 10, 10), api=api, sleep=lambda s: None):
            raise RuntimeError("boom")
    assert api.fg == 5


def test_visible_window_is_left_alone():
    api = FakeUser32(iconic=False)
    assert winctl.restore_if_minimized(winctl.GameWindow(1, 10, 10), api=api, sleep=lambda s: None) is False
    assert api.calls == []


def test_window_that_stays_minimized_raises():
    api = FakeUser32(restores=False)
    with pytest.raises(winctl.WindowMinimized):
        winctl.restore_if_minimized(winctl.GameWindow(1, 0, 0), api=api, sleep=lambda s: None)


def test_pick_window_empty_title():
    w1 = winctl.WindowInfo(1, "Clash of Clans - Ernestitogamer04", 1280, 720)
    w2 = winctl.WindowInfo(2, "Clash of Clans - Yearsuckk", 1280, 720)
    assert winctl.pick_window([w1], "") == w1
    assert winctl.pick_window([w1], "   ") == w1
    with pytest.raises(winctl.WindowNotFound):
        winctl.pick_window([], "")
    with pytest.raises(winctl.AmbiguousWindow):
        winctl.pick_window([w1, w2], "")


def test_pick_window_exact_beats_contains_and_ambiguous_is_window_not_found():
    w1 = winctl.WindowInfo(1, "Clash of Clans - Yearsuck", 1280, 720)
    w2 = winctl.WindowInfo(2, "Clash of Clans - Yearsuckk", 1280, 720)
    # Exact match beats the contains match on w2
    assert winctl.pick_window([w1, w2], "Clash of Clans - Yearsuck") == w1
    # AmbiguousWindow inherits from WindowNotFound
    assert issubclass(winctl.AmbiguousWindow, winctl.WindowNotFound)
    with pytest.raises(winctl.WindowNotFound):
        winctl.pick_window([w1, w2], "")


def test_pick_window_contains_case_insensitive():
    w1 = winctl.WindowInfo(1, "Clash of Clans - Ernestitogamer04", 1280, 720)
    w2 = winctl.WindowInfo(2, "Clash of Clans - Yearsuckk", 1280, 720)
    assert winctl.pick_window([w1, w2], "yearsuckk") == w2
    assert winctl.pick_window([w1, w2], "YEARSUCKK") == w2
    with pytest.raises(winctl.AmbiguousWindow):
        winctl.pick_window([w1, w2], "Clash")
    with pytest.raises(winctl.WindowNotFound):
        winctl.pick_window([w1, w2], "nonexistent")


def test_find_game_window_and_list_game_windows(monkeypatch):
    w1 = winctl.WindowInfo(10, "Clash of Clans - Ernestitogamer04", 1280, 720)
    w2 = winctl.WindowInfo(20, "Clash of Clans - Yearsuckk", 1920, 1080)
    monkeypatch.setattr(winctl, "_enum_game_windows", lambda: [w1])
    assert winctl.list_game_windows() == [w1]
    gw = winctl.find_game_window()
    assert gw == winctl.GameWindow(10, 1280, 720)

    monkeypatch.setattr(winctl, "_enum_game_windows", lambda: [w1, w2])
    assert winctl.find_game_window("yearsuckk") == winctl.GameWindow(20, 1920, 1080)
    with pytest.raises(winctl.AmbiguousWindow):
        winctl.find_game_window()
