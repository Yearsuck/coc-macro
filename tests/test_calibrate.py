import pytest

from cocmacro import calibrate


def test_rect_must_be_dragged():
    assert calibrate.validate_rect((0.4, 0.1, 0.5, 0.2)) == (0.4, 0.1, 0.5, 0.2)
    with pytest.raises(ValueError, match="arrastra"):
        calibrate.validate_rect((0.5195, 0.0766, 0.5195, 0.0766))   # what a plain click produced
