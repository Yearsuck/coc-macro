import pytest

from cocmacro import calibrate


def test_rect_must_be_dragged():
    assert calibrate.validate_rect((0.4, 0.1, 0.5, 0.2)) == (0.4, 0.1, 0.5, 0.2)
    with pytest.raises(ValueError, match="arrastra"):
        calibrate.validate_rect((0.5195, 0.0766, 0.5195, 0.0766))   # what a plain click produced


def test_tracker_follows_the_drag_live_and_normalises():
    seen = []
    t = calibrate.RectTracker(seen.append)
    t.move((0.9, 0.9))                       # moving without pressing: nothing
    assert seen == []
    t.down((0.5, 0.5))
    t.move((0.3, 0.2))                       # dragging up-left: rectangle is still ordered
    final = t.up((0.2, 0.1))
    assert seen[-1] == (0.2, 0.1, 0.5, 0.5) == final
    assert len(seen) == 3                    # down, move, up


def test_tracker_resets_after_release():
    seen = []
    t = calibrate.RectTracker(seen.append)
    t.down((0.1, 0.1)); t.up((0.2, 0.2))
    n = len(seen)
    t.move((0.9, 0.9))
    assert len(seen) == n
