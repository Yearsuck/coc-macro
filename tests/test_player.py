import threading
import time

from cocmacro import player
from cocmacro.recorder import Event, Recording


def _rec(n=6):
    return Recording("d", 1.78, [Event(0.0 if i == 0 else 0.01, "down" if i % 2 == 0 else "up", 0.5, 0.5)
                                 for i in range(n)])


def test_two_deployments_at_once_take_turns():
    """Live, two tabs deploying at the same time mixed their drags up: only one account deployed at a time."""
    log, lock = [], threading.Lock()

    def make_post(name):
        def post(win, kind, x, y):
            with lock:
                log.append(name)
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
    assert log in (["A"] * 6 + ["B"] * 6, ["B"] * 6 + ["A"] * 6)       # one whole replay, then the other


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
