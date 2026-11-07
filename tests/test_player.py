import contextlib
import threading
import time

import pytest

from cocmacro import player
from cocmacro.recorder import Event, Recording


def _rec(n=6):
    return Recording("d", 1.78, [Event(0.0 if i == 0 else 0.01, "down" if i % 2 == 0 else "up", 0.5, 0.5)
                                 for i in range(n)])




def test_a_stopped_bot_does_not_wait_for_the_other_deployment():
    from cocmacro import winctl
    stop = threading.Event()
    stop.set()
    with winctl.exclusive_input():              # another account is deploying
        result = []
        t = threading.Thread(target=lambda: result.append(
            player.play(object(), _rec(), stop, sleep=lambda s: None, post=lambda *a: None, post_wheel=lambda *a: None)))
        t.start()
        t.join(2)
    assert result == [False] and not t.is_alive()


def test_the_input_lock_is_released_when_a_replay_raises():
    from cocmacro import winctl

    def boom(win, kind, x, y):
        raise RuntimeError("window gone")
    try:
        player.play(object(), _rec(), threading.Event(), sleep=lambda s: None, post=boom, post_wheel=lambda *a: None)
    except RuntimeError:
        pass
    with winctl.exclusive_input(poll=0.05) as got:       # would wait forever if the lock had leaked
        assert got is True


def test_a_deployment_marks_its_window_active_first(monkeypatch):
    from cocmacro import winctl
    events = []
    monkeypatch.setattr(winctl, "activate_instance", lambda win: events.append("activate"))
    player.play(object(), _rec(2), threading.Event(), sleep=lambda s: None,
                post=lambda *a: events.append("post"), post_wheel=lambda *a: None)
    assert events == ["activate", "post", "post"]


def test_two_deployments_at_once_never_mix_a_gesture():
    """Each account's press and release stay together; the two replays interleave only between gestures."""
    log, lock = [], threading.Lock()

    def make_post(name):
        def post(win, kind, x, y):
            with lock:
                log.append((name, kind))
            time.sleep(0.005)
        return post

    def run(name):
        player.play(object(), _rec(), threading.Event(), sleep=lambda s: time.sleep(0.01),
                    post=make_post(name), post_wheel=lambda *a: None)

    threads = [threading.Thread(target=run, args=(n,)) for n in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(log) == 12
    pairs = list(zip(log[0::2], log[1::2]))
    assert all(a[0] == b[0] and a[1] == "down" and b[1] == "up" for a, b in pairs)       # never split


def test_a_tap_of_the_other_account_gets_in_between_the_gestures_of_a_long_replay():
    """Scouting only lasts 30 s: 'Siguiente' must not wait for the whole 22 s deployment of the other account."""
    from cocmacro import winctl
    log, lock = [], threading.Lock()

    def post(win, kind, x, y):
        with lock:
            log.append((getattr(win, "name", "other"), kind))
        time.sleep(0.002)

    class Win:
        name = "tapper"
    started = threading.Event()

    def deploy():
        events = []
        for i in range(40):
            events += [Event(0.02, "down", 0.5, 0.5), Event(0.01, "up", 0.5, 0.5)]
        started.set()
        player.play(object(), Recording("d", 1.78, events), threading.Event(), sleep=lambda s: time.sleep(s),
                    post=post, post_wheel=lambda *a: None)

    t = threading.Thread(target=deploy)
    t.start()
    started.wait(2)
    time.sleep(0.15)
    real_post = winctl.post_mouse
    winctl.post_mouse = post
    try:
        winctl.click(Win(), 0.5, 0.5, hold_s=0.0)
    finally:
        winctl.post_mouse = real_post
    t.join(5)
    kinds = [k for n, k in log]
    mine = [i for i, (n, k) in enumerate(log) if n == "tapper"]
    assert len(mine) == 4 and mine == list(range(mine[0], mine[0] + 4))     # hover, hover, down, up: one block
    assert [log[i][1] for i in mine] == ["hover", "hover", "down", "up"]
    assert 0 < mine[0] < len(log) - 8                                       # in the middle of the replay, not after it
    assert len(kinds) == 40 * 2 + 4


def test_a_wheel_turn_is_its_own_gesture(monkeypatch):
    from cocmacro import winctl
    held = []
    real = winctl.exclusive_input

    @contextlib.contextmanager
    def spy(stop=None, poll=0.2):
        held.append("take")
        with real(stop, poll) as got:
            yield got
        held.append("release")
    monkeypatch.setattr(winctl, "exclusive_input", spy)
    rec = Recording("d", 1.78, [Event(0.0, "wheel", 0.5, 0.5, -120), Event(0.0, "wheel", 0.5, 0.5, -120)])
    player.play(object(), rec, threading.Event(), sleep=lambda s: None, post=lambda *a: None,
                post_wheel=lambda *a: held.append("wheel"))
    assert held == ["take", "wheel", "release", "take", "wheel", "release"]


def test_stopping_in_the_middle_of_a_drag_releases_the_button_while_holding_the_channel(monkeypatch):
    from cocmacro import winctl
    held = []
    real = winctl.exclusive_input
    stop = threading.Event()
    posts = []

    @contextlib.contextmanager
    def spy(stop_=None, poll=0.2):
        with real(stop_, poll) as got:
            held.append(True)
            yield got
        held.append(False)

    def post(win, kind, x, y):
        posts.append((kind, held[-1]))                    # was the channel held when this was posted?
        if kind == "move":
            stop.set()                                     # F8 in the middle of the drag
    monkeypatch.setattr(winctl, "exclusive_input", spy)
    rec = Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5), Event(0.01, "move", 0.4, 0.5), Event(0.01, "move", 0.3, 0.5),
                                Event(0.01, "up", 0.3, 0.5)])
    assert player.play(object(), rec, stop, sleep=lambda s: None, post=post, post_wheel=lambda *a: None) is False
    assert [k for k, _ in posts][-1] == "up" and all(h for _, h in posts)       # the button is let go, under the channel


def test_a_recording_cut_after_a_press_still_releases_it():
    posts = []
    rec = Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5), Event(0.01, "move", 0.4, 0.5)])
    assert player.play(object(), rec, threading.Event(), sleep=lambda s: None,
                       post=lambda w, k, x, y: posts.append(k), post_wheel=lambda *a: None) is True
    assert posts == ["down", "move", "up"]


def test_a_wheel_turn_inside_a_drag_does_not_let_go_of_the_channel(monkeypatch):
    from cocmacro import winctl
    events = []
    real = winctl.exclusive_input

    @contextlib.contextmanager
    def spy(stop=None, poll=0.2):
        events.append("take")
        with real(stop, poll) as got:
            yield got
        events.append("release")
    monkeypatch.setattr(winctl, "exclusive_input", spy)
    rec = Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5), Event(0.01, "wheel", 0.5, 0.5, -120), Event(0.01, "up", 0.5, 0.5)])
    player.play(object(), rec, threading.Event(), sleep=lambda s: None, post=lambda *a: events.append("post"),
                post_wheel=lambda *a: events.append("wheel"))
    assert events == ["take", "post", "wheel", "post", "release"]


def test_the_first_press_and_a_repeated_spot_get_a_pointer_move_first_in_production(monkeypatch):
    from cocmacro import winctl
    seen = []
    monkeypatch.setattr(winctl, "activate_instance", lambda win: None)
    monkeypatch.setattr(winctl, "hover_to", lambda win, x, y: seen.append(("hover", x, y)))
    fake = lambda win, kind, x, y: seen.append((kind, x, y))
    monkeypatch.setattr(winctl, "post_mouse", fake)
    rec = Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5), Event(0.01, "up", 0.5, 0.5),
                                Event(0.01, "down", 0.5, 0.5), Event(0.01, "up", 0.5, 0.5),
                                Event(0.01, "down", 0.2, 0.2), Event(0.01, "up", 0.2, 0.2)])
    player.play(object(), rec, threading.Event(), sleep=lambda s: None, post=fake, post_wheel=lambda *a: None)
    kinds = [k for k, *_ in seen]
    assert kinds == ["hover", "down", "up", "hover", "down", "up", "down", "up"]    # not before the press at a NEW spot
