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


def _price_case(tmp_path, name):
    """Same button label, different price line (bottom ~45% of the crop)."""
    saved = noise(7)
    templates.save_template(name, saved, (0.5, 0.5), (0.2, 0.3), tmp_path)
    other = saved.copy()
    h, w = other.shape[:2]
    y0, y1 = int(0.5 * h - 0.15 * h), int(0.5 * h + 0.15 * h)
    x0, x1 = int(0.5 * w - 0.1 * w), int(0.5 * w + 0.1 * w)
    cut = y0 + int((y1 - y0) * 0.60)                       # below the label: the price changes
    other[cut:y1, x0:x1] = noise(99)[cut:y1, x0:x1]
    return other


def test_next_button_ignores_the_price_line(tmp_path):
    """Real bug: 'Siguiente 1700' vs 'Siguiente 1600' on another account."""
    assert templates.match(_price_case(tmp_path, "next"), "next", tmp_path) is True


def test_other_buttons_are_still_matched_whole(tmp_path):
    assert templates.match(_price_case(tmp_path, "ok"), "ok", tmp_path) is False
