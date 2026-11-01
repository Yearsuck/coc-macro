import threading

from cocmacro import player, recorder
from cocmacro.recorder import Event, Recording


def sample():
    return Recording("atk", 1.78, [
        Event(0.0, "down", 0.1, 0.2),
        Event(0.2, "move", 0.2, 0.3),
        Event(0.3, "up", 0.2, 0.3),
        Event(0.5, "down", 0.5, 0.5),
        Event(0.1, "up", 0.5, 0.5),
    ])


def test_save_load_roundtrip(tmp_path):
    rec = sample()
    recorder.save_recording(rec, tmp_path)
    assert recorder.load_recording("atk", tmp_path) == rec


def test_list_recordings_sorted(tmp_path):
    for n in ("zeta", "alfa", "medio"):
        recorder.save_recording(Recording(n, 1.78, []), tmp_path)
    assert recorder.list_recordings(tmp_path) == ["alfa", "medio", "zeta"]
    assert recorder.list_recordings(tmp_path / "nope") == []


def test_play_sends_events_in_order():
    posted, slept = [], []
    ok = player.play(object(), sample(), threading.Event(), sleep=slept.append,
                     post=lambda win, k, x, y: posted.append((k, x, y)))
    assert ok is True
    assert [p[0] for p in posted] == ["down", "move", "up", "down", "up"]
    assert posted[1] == ("move", 0.2, 0.3)
    assert abs(sum(slept) - 1.1) < 1e-9


def test_stop_releases_button():
    stop = threading.Event()
    posted = []

    def post(win, k, x, y):
        posted.append((k, x, y))
        if k == "move":
            stop.set()

    ok = player.play(object(), sample(), stop, sleep=lambda s: None, post=post)
    assert ok is False
    assert posted[-1] == ("up", 0.2, 0.3)


def test_recorder_feed_filters_outside_and_idle_moves():
    clock = iter([10.0, 10.5, 10.7, 11.0])
    inside = lambda sx, sy: (sx / 100, sy / 100) if 0 <= sx <= 100 and 0 <= sy <= 100 else None
    rec = recorder.Recorder(inside, "x", now=lambda: next(clock), aspect=1.78)
    rec.feed("move", 50, 50, pressed=False)        # idle move: ignored (no clock use)
    rec.feed("down", 150, 50, pressed=True)        # outside: ignored
    rec.feed("down", 10, 20, pressed=True)         # t=10.0 -> dt 0
    rec.feed("move", 20, 30, pressed=True)         # t=10.5 -> dt .5
    rec.feed("up", 20, 30, pressed=False)          # t=10.7 -> dt .2
    out = rec.result()
    assert [e.kind for e in out.events] == ["down", "move", "up"]
    assert out.events[0].dt == 0.0
    assert abs(out.events[1].dt - 0.5) < 1e-9
    assert abs(out.events[2].dt - 0.2) < 1e-9
    assert out.events[0].x == 0.1 and out.events[0].y == 0.2


def test_recorder_records_wheel_inside_window_only():
    clock = iter([1.0, 1.4])
    inside = lambda sx, sy: (sx / 100, sy / 100) if 0 <= sx <= 100 and 0 <= sy <= 100 else None
    rec = recorder.Recorder(inside, "x", now=lambda: next(clock), aspect=1.78)
    rec.feed("wheel", 150, 50, pressed=False, delta=120)    # outside: ignored
    rec.feed("wheel", 40, 60, pressed=False, delta=120)     # t=1.0
    rec.feed("wheel", 40, 60, pressed=False, delta=-240)    # t=1.4
    ev = rec.result().events
    assert [(e.kind, e.delta) for e in ev] == [("wheel", 120), ("wheel", -240)]
    assert (ev[0].x, ev[0].y) == (0.4, 0.6)
    assert abs(ev[1].dt - 0.4) < 1e-9


def test_old_recording_without_delta_still_loads(tmp_path):
    (tmp_path / "old.json").write_text(
        '{"name":"old","aspect":1.78,"events":[{"dt":0.0,"kind":"down","x":0.1,"y":0.2}]}', encoding="utf-8")
    assert recorder.load_recording("old", tmp_path).events == [Event(0.0, "down", 0.1, 0.2)]


def test_wheel_roundtrip(tmp_path):
    rec = Recording("w", 1.78, [Event(0.1, "wheel", 0.3, 0.4, -120)])
    recorder.save_recording(rec, tmp_path)
    assert recorder.load_recording("w", tmp_path) == rec


def test_play_sends_wheel_with_delta():
    rec = Recording("w", 1.78, [Event(0.0, "down", 0.1, 0.2), Event(0.2, "wheel", 0.3, 0.4, 120),
                                Event(0.1, "up", 0.1, 0.2)])
    posted, wheeled = [], []
    ok = player.play(object(), rec, threading.Event(), sleep=lambda s: None,
                     post=lambda win, k, x, y: posted.append(k),
                     post_wheel=lambda win, x, y, d: wheeled.append((x, y, d)))
    assert ok is True
    assert posted == ["down", "up"] and wheeled == [(0.3, 0.4, 120)]
