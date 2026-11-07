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


def test_pick_window_empty_title():
    w1 = winctl.WindowInfo(1, "Clash of Clans - PlayerOne", 1280, 720)
    w2 = winctl.WindowInfo(2, "Clash of Clans - PlayerTwoo", 1280, 720)
    assert winctl.pick_window([w1], "") == w1
    assert winctl.pick_window([w1], "   ") == w1
    with pytest.raises(winctl.WindowNotFound):
        winctl.pick_window([], "")
    with pytest.raises(winctl.AmbiguousWindow):
        winctl.pick_window([w1, w2], "")


def test_pick_window_exact_beats_contains_and_ambiguous_is_window_not_found():
    w1 = winctl.WindowInfo(1, "Clash of Clans - PlayerTwo", 1280, 720)
    w2 = winctl.WindowInfo(2, "Clash of Clans - PlayerTwoo", 1280, 720)
    # Exact match beats the contains match on w2
    assert winctl.pick_window([w1, w2], "Clash of Clans - PlayerTwo") == w1
    # AmbiguousWindow inherits from WindowNotFound
    assert issubclass(winctl.AmbiguousWindow, winctl.WindowNotFound)
    with pytest.raises(winctl.WindowNotFound):
        winctl.pick_window([w1, w2], "")


def test_pick_window_contains_case_insensitive():
    w1 = winctl.WindowInfo(1, "Clash of Clans - PlayerOne", 1280, 720)
    w2 = winctl.WindowInfo(2, "Clash of Clans - PlayerTwoo", 1280, 720)
    assert winctl.pick_window([w1, w2], "playertwoo") == w2
    assert winctl.pick_window([w1, w2], "PLAYERTWOO") == w2
    with pytest.raises(winctl.AmbiguousWindow):
        winctl.pick_window([w1, w2], "Clash")
    with pytest.raises(winctl.WindowNotFound):
        winctl.pick_window([w1, w2], "nonexistent")


def test_find_game_window_and_list_game_windows(monkeypatch):
    w1 = winctl.WindowInfo(10, "Clash of Clans - PlayerOne", 1280, 720)
    w2 = winctl.WindowInfo(20, "Clash of Clans - PlayerTwoo", 1920, 1080)
    monkeypatch.setattr(winctl, "_enum_game_windows", lambda: [w1])
    assert winctl.list_game_windows() == [w1]
    gw = winctl.find_game_window()
    assert gw == winctl.GameWindow(10, 1280, 720)

    monkeypatch.setattr(winctl, "_enum_game_windows", lambda: [w1, w2])
    assert winctl.find_game_window("playertwoo") == winctl.GameWindow(20, 1920, 1080)
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


def test_finding_the_game_windows_never_reads_window_titles(monkeypatch):
    """Reading a title blocks on a window whose thread does not pump messages (the Tk root of the app/tests)."""
    def no_titles(hwnd):
        raise AssertionError("window title read while looking for game windows")
    monkeypatch.setattr(winctl, "_title", no_titles)
    monkeypatch.setattr(winctl, "_games_cache", (0.0, []))
    assert isinstance(winctl._game_hwnds(), list)


class _Sender:
    """user32 stand-in recording the activation messages."""

    def __init__(self):
        self.sent = []

    def SendMessageTimeoutW(self, hwnd, msg, wparam, lparam, flags, timeout, result):
        self.sent.append((hwnd, msg, wparam, lparam))
        return 1


def _two_windows(monkeypatch, games=(1, 2)):
    fake = _Sender()
    monkeypatch.setattr(winctl, "user32", fake)
    monkeypatch.setattr(winctl, "_game_hwnds", lambda: list(games))
    monkeypatch.setattr(winctl, "_last_active_hwnd", 0)
    monkeypatch.setattr(winctl.time, "sleep", lambda s: None)
    return fake


def test_activating_an_instance_marks_it_active_and_the_others_inactive(monkeypatch):
    fake = _two_windows(monkeypatch, games=(1, 2, 3))
    assert winctl.activate_instance(winctl.GameWindow(2, 10, 10)) is True
    assert fake.sent == [(2, winctl.WM_ACTIVATE, winctl.WA_ACTIVE, 0),
                         (1, winctl.WM_ACTIVATE, winctl.WA_INACTIVE, 2),
                         (3, winctl.WM_ACTIVATE, winctl.WA_INACTIVE, 2)]


def test_a_single_game_window_or_a_stranger_is_left_alone(monkeypatch):
    fake = _two_windows(monkeypatch, games=(1,))
    assert winctl.activate_instance(winctl.GameWindow(1, 10, 10)) is False        # nobody to arbitrate with
    fake2 = _two_windows(monkeypatch, games=(1, 2))
    assert winctl.activate_instance(winctl.GameWindow(99, 10, 10)) is False       # not a game window
    assert winctl.activate_instance(object()) is False
    assert fake.sent == [] and fake2.sent == []


def test_a_window_missing_from_a_stale_list_is_looked_for_again(monkeypatch):
    fake = _two_windows(monkeypatch)
    lists = iter([[1], [1, 2]])                         # the cached list lacks window 2; the fresh one has it
    monkeypatch.setattr(winctl, "_game_hwnds", lambda: next(lists))
    assert winctl.activate_instance(winctl.GameWindow(2, 10, 10)) is True
    assert len(fake.sent) == 2


def test_the_host_gets_a_moment_to_switch_when_the_instance_changes_or_after_a_while(monkeypatch):
    _two_windows(monkeypatch)
    pauses, clock = [], [100.0]
    monkeypatch.setattr(winctl.time, "sleep", lambda s: pauses.append(s))
    monkeypatch.setattr(winctl.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(winctl, "_last_active_at", 0.0)
    winctl.activate_instance(winctl.GameWindow(1, 10, 10))                        # first time: pause
    clock[0] += 0.2
    winctl.activate_instance(winctl.GameWindow(1, 10, 10))                        # same instance, just now: none
    winctl.activate_instance(winctl.GameWindow(2, 10, 10))                        # another instance: pause
    clock[0] += 5.0
    winctl.activate_instance(winctl.GameWindow(2, 10, 10))                        # same, but the user may have clicked
    assert pauses == [winctl.ACTIVATE_SETTLE_S] * 3


def test_the_windows_call_has_explicit_argument_types():
    """No truncation of handles / lparam through the default int conversion."""
    assert len(winctl.user32.SendMessageTimeoutW.argtypes) == 7


def test_a_tap_marks_its_window_active_before_pressing(monkeypatch):
    calls = []
    monkeypatch.setattr(winctl, "activate_instance", lambda win: calls.append("activate"))
    monkeypatch.setattr(winctl, "post_mouse", lambda win, kind, x, y: calls.append(kind))
    winctl.click(winctl.GameWindow(1, 10, 10), 0.5, 0.5, hold_s=0)
    assert calls == ["activate", "down", "up"]


def test_activating_from_a_thread_while_the_main_thread_is_blocked_does_not_hang(monkeypatch):
    """Looking for the game windows once hung here (title reads block on a non-pumping thread)."""
    import threading
    monkeypatch.setattr(winctl, "_games_cache", (0.0, []))
    result = []
    t = threading.Thread(target=lambda: result.append(winctl.activate_instance(winctl.GameWindow(1, 10, 10))))
    t.start()
    t.join(20)
    assert not t.is_alive() and result == [False]
