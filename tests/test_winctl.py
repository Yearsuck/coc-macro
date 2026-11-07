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


def test_taps_of_two_windows_never_interleave(monkeypatch):
    """The press and the release of a tap are one unit: another window's tap cannot land in between."""
    import threading
    import time
    log, lock = [], threading.Lock()

    def fake_post(win, kind, x, y):
        with lock:
            log.append((win.hwnd, kind))
        time.sleep(0.01)
    monkeypatch.setattr(winctl, "post_mouse", fake_post)
    threads = [threading.Thread(target=lambda h=h: [winctl.click(winctl.GameWindow(h, 1, 1), 0.5, 0.5, hold_s=0.01)
                                                    for _ in range(10)]) for h in (1, 2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    pairs = list(zip(log[0::2], log[1::2]))
    assert len(log) == 40 and all(a[0] == b[0] and a[1] == "down" and b[1] == "up" for a, b in pairs)


def test_exclusive_input_makes_the_second_holder_wait():
    import threading
    import time
    order = []

    def second():
        with winctl.exclusive_input() as got:
            order.append(("second", got))

    with winctl.exclusive_input() as got:
        assert got is True
        t = threading.Thread(target=second)
        t.start()
        time.sleep(0.3)
        assert order == []                      # still waiting while the first holds it
        with winctl.exclusive_input() as again:   # re-entrant for the holder
            assert again is True
    t.join(2)
    assert order == [("second", True)]


def test_exclusive_input_gives_up_when_stop_is_set_while_waiting():
    import threading
    stop = threading.Event()
    result = []

    def waiter():
        with winctl.exclusive_input(stop, poll=0.05) as got:
            result.append(got)

    with winctl.exclusive_input():
        t = threading.Thread(target=waiter)
        t.start()
        stop.set()
        t.join(2)
    assert result == [False]


def test_covering_window_picks_the_highest_overlapping_clash_window_above():
    rects = {1: (0, 0, 100, 100), 2: (50, 50, 150, 150), 3: (500, 500, 600, 600), 4: (60, 60, 160, 160)}
    order = [3, 4, 2, 1]                                   # top first
    assert winctl.covering_window(order, rects, 1) == 4     # 4 is the highest one above 1 that overlaps it
    assert winctl.covering_window(order, rects, 2) == 4
    assert winctl.covering_window(order, rects, 4) is None  # nothing overlapping is above it
    assert winctl.covering_window(order, rects, 3) is None  # 3 is on top and elsewhere
    assert winctl.covering_window([2, 1], {1: (0, 0, 10, 10), 2: (20, 20, 30, 30)}, 1) is None  # no overlap
    assert winctl.covering_window(order, rects, 99) is None  # not a Clash window


def test_a_tap_raises_a_covered_window_before_pressing(monkeypatch):
    calls = []
    monkeypatch.setattr(winctl, "raise_above_overlapping", lambda win: calls.append("raise"))
    monkeypatch.setattr(winctl, "post_mouse", lambda win, kind, x, y: calls.append(kind))
    winctl.click(winctl.GameWindow(1, 10, 10), 0.5, 0.5, hold_s=0)
    assert calls == ["raise", "down", "up"]


def test_raising_ignores_a_window_that_is_not_a_clash_window(monkeypatch):
    monkeypatch.setattr(winctl, "_game_hwnds", lambda: [7, 8])
    assert winctl.raise_above_overlapping(winctl.GameWindow(1, 10, 10)) is False
    assert winctl.raise_above_overlapping(object()) is False
    assert winctl.overlapping_titles(winctl.GameWindow(1, 10, 10)) == []


def test_finding_the_game_windows_never_reads_window_titles(monkeypatch):
    """Reading a title blocks on a window whose thread does not pump messages (the Tk root of the app/tests)."""
    def no_titles(hwnd):
        raise AssertionError("window title read while looking for game windows")
    monkeypatch.setattr(winctl, "_title", no_titles)
    monkeypatch.setattr(winctl, "_games_cache", (0.0, []))
    assert isinstance(winctl._game_hwnds(), list)


def test_raising_from_a_thread_while_the_main_thread_is_blocked_does_not_hang(monkeypatch):
    """The first version hung here: the worker enumerated windows while the main thread sat in join()."""
    import threading
    monkeypatch.setattr(winctl, "_games_cache", (0.0, []))
    result = []
    t = threading.Thread(target=lambda: result.append(winctl.raise_above_overlapping(winctl.GameWindow(1, 10, 10))))
    t.start()
    t.join(20)
    assert not t.is_alive() and result == [False]


class _FakeUser32:
    def __init__(self, above=99):
        self.above, self.set_calls = above, []

    def GetWindow(self, hwnd, cmd):
        assert cmd == winctl.GW_HWNDPREV
        return self.above

    def SetWindowPos(self, hwnd, after, x, y, w, h, flags):
        self.set_calls.append((hwnd, after, flags))


def _arrange(monkeypatch, order, rects, above=99):
    fake = _FakeUser32(above)
    monkeypatch.setattr(winctl, "user32", fake)
    monkeypatch.setattr(winctl, "_game_hwnds", lambda: list(order))
    monkeypatch.setattr(winctl, "_zorder_top_first", lambda: [5] + list(order))
    monkeypatch.setattr(winctl, "_rect_of", lambda h: rects[h])
    monkeypatch.setattr(winctl.time, "sleep", lambda s: None)
    return fake


def test_raising_puts_the_window_directly_above_the_covering_one(monkeypatch):
    fake = _arrange(monkeypatch, [1, 2], {1: (0, 0, 100, 100), 2: (50, 0, 150, 100)}, above=99)
    assert winctl.raise_above_overlapping(winctl.GameWindow(2, 10, 10)) is True
    assert fake.set_calls == [(2, 99, winctl.SWP_NOSIZE | winctl.SWP_NOMOVE | winctl.SWP_NOACTIVATE)]


def test_raising_uses_the_top_when_nothing_is_above_the_covering_window(monkeypatch):
    fake = _arrange(monkeypatch, [1, 2], {1: (0, 0, 100, 100), 2: (50, 0, 150, 100)}, above=0)
    assert winctl.raise_above_overlapping(winctl.GameWindow(2, 10, 10)) is True
    assert fake.set_calls[0][1] == winctl.HWND_TOP


def test_a_window_already_above_or_apart_is_not_touched(monkeypatch):
    fake = _arrange(monkeypatch, [1, 2], {1: (0, 0, 100, 100), 2: (50, 0, 150, 100)})
    assert winctl.raise_above_overlapping(winctl.GameWindow(1, 10, 10)) is False       # it is the one on top
    fake2 = _arrange(monkeypatch, [1, 2], {1: (0, 0, 100, 100), 2: (500, 0, 600, 100)})
    assert winctl.raise_above_overlapping(winctl.GameWindow(2, 10, 10)) is False       # side by side
    assert fake.set_calls == [] and fake2.set_calls == []


def test_a_window_missing_from_a_stale_list_is_looked_for_again(monkeypatch):
    fake = _arrange(monkeypatch, [1, 2], {1: (0, 0, 100, 100), 2: (50, 0, 150, 100)})
    lists = iter([[1], [1, 2]])                         # the cached list lacks window 2; the fresh one has it
    monkeypatch.setattr(winctl, "_game_hwnds", lambda: next(lists))
    monkeypatch.setattr(winctl, "_zorder_top_first", lambda: [1, 2])
    assert winctl.raise_above_overlapping(winctl.GameWindow(2, 10, 10)) is True
    assert len(fake.set_calls) == 1


def test_overlapping_titles_lists_only_the_windows_that_overlap(monkeypatch):
    monkeypatch.setattr(winctl, "_game_hwnds", lambda: [1, 2, 3])
    rects = {1: (0, 0, 100, 100), 2: (50, 0, 150, 100), 3: (500, 0, 600, 100)}
    monkeypatch.setattr(winctl, "_rect_of", lambda h: rects[h])
    monkeypatch.setattr(winctl, "_title", lambda h: f"Clash of Clans - {h}")
    assert winctl.overlapping_titles(winctl.GameWindow(1, 10, 10)) == ["Clash of Clans - 2"]
    assert winctl.overlapping_titles(winctl.GameWindow(3, 10, 10)) == []
