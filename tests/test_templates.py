import numpy as np

from cocmacro import templates


def noise(seed, h=120, w=200):
    return np.random.default_rng(seed).integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_match_finds_saved_button(tmp_path):
    frame = noise(1)
    templates.save_template("next", frame, (0.5, 0.5), (0.2, 0.3), tmp_path)
    assert templates.match(frame, "next", tmp_path) is True


def test_match_rejects_other_screen(tmp_path):
    templates.save_template("surrender", noise(1), (0.5, 0.5), (0.2, 0.3), tmp_path)
    assert templates.match(noise(2), "surrender", tmp_path) is False


def test_match_missing_template_is_false(tmp_path):
    assert templates.match(noise(1), "nada", tmp_path) is False
