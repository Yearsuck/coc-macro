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


def test_score_gives_value_and_place(tmp_path):
    frame = noise(1)
    templates.save_template("next", frame, (0.5, 0.5), (0.2, 0.3), tmp_path)
    score, (x, y) = templates.score(frame, "next", tmp_path)
    assert score > 0.99 and abs(x - 0.5) < 0.1 and abs(y - 0.5) < 0.1      # centre of the match, relative
    assert templates.score(frame, "nada", tmp_path) is None


def test_a_softer_render_of_the_same_button_still_matches(tmp_path):
    """A friend's PC rendered the game slightly softer (scale/GPU): 0.82 similarity must not mean 'not this screen'."""
    import cv2
    frame = cv2.imread(str(__import__("pathlib").Path(__file__).parent / "fixtures" / "f004.png"))
    templates.save_template("next", frame, (0.909, 0.7517), (0.06, 0.07), tmp_path)
    soft = cv2.GaussianBlur(frame, (0, 0), 1.2)
    assert 0.76 < templates.score(soft, "next", tmp_path)[0] < 0.85
    assert templates.match(soft, "next", tmp_path) is True


def test_shipped_buttons_are_never_taken_for_each_other():
    """The threshold is low enough to tolerate soft renders only if the look-alike buttons stay far apart."""
    import cv2
    from cocmacro import defaults
    imgs = {p.stem: cv2.imread(str(p)) for p in defaults.DIR.glob("*.png")}
    for a, ta in imgs.items():
        for b, tb in imgs.items():
            if a == b or ta.shape[0] > tb.shape[0] + 12 or ta.shape[1] > tb.shape[1] + 12:
                continue
            frame = cv2.copyMakeBorder(tb, 6, 6, 6, 6, cv2.BORDER_REPLICATE)
            margin = 0.05 if a in templates.STRICT_NAMES else 0.1    # look-alike filter buttons use the strict cut
            assert cv2.matchTemplate(frame, ta, cv2.TM_CCOEFF_NORMED).max() < templates.threshold_for(a) - margin, (a, b)


def _spots(monkeypatch):
    """Where the synthetic frames below draw the X and the label (relative centres)."""
    monkeypatch.setitem(templates.ALTERNATIVES, "upgrade_window", (
        (("upgrade_window", None),),
        (("upgrade_window_x", (270 / 300, 25 / 200)), ("upgrade_window_confirm", (150 / 300, 162.5 / 200)))))


def _window_frame():
    return np.full((200, 300, 3), 127, dtype=np.uint8)


def test_upgrade_window_is_seen_by_its_x_and_confirm_label_when_the_title_shrinks(tmp_path, monkeypatch):
    _spots(monkeypatch)
    """Long building names shrink the title text, so the title crop misses; the X and the label do not."""
    frame = _window_frame()
    frame[10:40, 250:290] = noise(3, 30, 40)                     # red X
    frame[150:175, 100:200] = noise(4, 25, 100)                  # green button label
    templates.save_template("upgrade_window", noise(9, 30, 100), (0.5, 0.5), (0.3, 0.2), tmp_path)   # not on screen
    templates.save_template("upgrade_window_x", frame, (270 / 300, 25 / 200), (40 / 300, 30 / 200), tmp_path)
    templates.save_template("upgrade_window_confirm", frame, (150 / 300, 162.5 / 200), (100 / 300, 25 / 200), tmp_path)
    assert templates.match(frame, "upgrade_window", tmp_path) is True


def test_upgrade_window_needs_both_the_x_and_the_confirm_label(tmp_path, monkeypatch):
    _spots(monkeypatch)
    frame = _window_frame()
    frame[10:40, 250:290] = noise(3, 30, 40)
    templates.save_template("upgrade_window", noise(9, 30, 100), (0.5, 0.5), (0.3, 0.2), tmp_path)
    templates.save_template("upgrade_window_x", frame, (270 / 300, 25 / 200), (40 / 300, 30 / 200), tmp_path)
    templates.save_template("upgrade_window_confirm", noise(5, 25, 100), (0.5, 0.5), (100 / 300, 25 / 200), tmp_path)
    assert templates.match(frame, "upgrade_window", tmp_path) is False       # a lone red X is any window


def test_upgrade_window_title_alone_still_counts(tmp_path):
    frame = noise(1)
    templates.save_template("upgrade_window", frame, (0.5, 0.5), (0.4, 0.3), tmp_path)
    assert templates.match(frame, "upgrade_window", tmp_path) is True


def test_an_x_and_a_label_in_the_wrong_place_are_another_dialog(tmp_path, monkeypatch):
    """Other dialogs have a red X and a green Confirmar too: they must not pass for the upgrade window."""
    _spots(monkeypatch)
    frame = _window_frame()
    frame[10:40, 250:290] = noise(3, 30, 40)
    frame[150:175, 100:200] = noise(4, 25, 100)
    templates.save_template("upgrade_window", noise(9, 30, 100), (0.5, 0.5), (0.3, 0.2), tmp_path)
    templates.save_template("upgrade_window_x", frame, (270 / 300, 25 / 200), (40 / 300, 30 / 200), tmp_path)
    templates.save_template("upgrade_window_confirm", frame, (150 / 300, 162.5 / 200), (100 / 300, 25 / 200), tmp_path)
    moved = _window_frame()
    moved[100:130, 20:60] = frame[10:40, 250:290]                 # the X far from its corner
    moved[150:175, 100:200] = frame[150:175, 100:200]
    assert templates.match(moved, "upgrade_window", tmp_path) is False
