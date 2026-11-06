import cv2
import numpy as np
import pytest

from pathlib import Path

from cocmacro import ocr, vision

FIXTURES = Path(__file__).parent / "fixtures" / "ui"


def test_cost_is_red_twenty_percent():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    frame[:20, :, :] = (0, 0, 255)
    assert vision.cost_is_red(frame, (0.0, 0.0, 1.0, 1.0)) is True


def test_cost_is_red_all_white():
    frame = np.full((100, 300, 3), 255, dtype=np.uint8)
    assert vision.cost_is_red(frame, (0.0, 0.0, 1.0, 1.0)) is False


def test_cost_is_red_all_black():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    assert vision.cost_is_red(frame, (0.0, 0.0, 1.0, 1.0)) is False


def test_cost_is_red_below_threshold():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    frame[:5, :, :] = (0, 0, 255)
    assert vision.cost_is_red(frame, (0.0, 0.0, 1.0, 1.0)) is False


def test_cost_is_red_subregion():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    region = (0.1, 0.1, 0.9, 0.9)
    # Inside region: y is 10..90 (80px), x is 30..270 (240px) -> total 19200 px
    # Color 20% of the region (16 rows) pure red
    frame[10:26, 30:270, :] = (0, 0, 255)
    assert vision.cost_is_red(frame, region) is True


def test_storage_full_gold_yellow_full_width():
    frame = np.full((50, 200, 3), (30, 200, 240), dtype=np.uint8)
    assert vision.storage_full(frame, (0.0, 0.0, 1.0, 1.0)) is True


def test_storage_full_elixir_full_width():
    frame = np.full((50, 200, 3), (180, 50, 200), dtype=np.uint8)
    assert vision.storage_full(frame, (0.0, 0.0, 1.0, 1.0)) is True


def test_storage_fills_from_the_icon_so_a_half_bar_is_not_full():
    """The game fills the bar from the right (icon side) leftwards: fill only on the right half = not full."""
    frame = np.full((50, 200, 3), (20, 20, 20), dtype=np.uint8)
    frame[:, 100:, :] = (30, 200, 240)
    assert vision.storage_full(frame, (0.0, 0.0, 1.0, 1.0)) is False


def test_storage_with_fill_reaching_the_left_end_is_full():
    frame = np.full((50, 200, 3), (20, 20, 20), dtype=np.uint8)
    frame[:, 4:, :] = (30, 200, 240)       # a 4 px border on the left, fill everywhere else
    assert vision.storage_full(frame, (0.0, 0.0, 1.0, 1.0)) is True


def test_storage_full_empty_region():
    frame = np.full((50, 200, 3), (30, 200, 240), dtype=np.uint8)
    assert vision.storage_full(frame, (0.5, 0.5, 0.5, 0.5)) is None


def test_storage_full_ambiguous():
    amb_hsv = np.uint8([[[20, 75, 105]]])
    amb_bgr = cv2.cvtColor(amb_hsv, cv2.COLOR_HSV2BGR)[0, 0]
    frame = np.full((50, 200, 3), amb_bgr, dtype=np.uint8)
    assert vision.storage_full(frame, (0.0, 0.0, 1.0, 1.0)) is None


def test_free_count_blank_black_frame():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    assert vision.free_count(frame, (0.0, 0.0, 1.0, 1.0)) is None


def test_free_count_empty_region():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    assert vision.free_count(frame, (0.5, 0.5, 0.5, 0.5)) is None


def _live_frame():
    """Black frame with the real counters strip (0/7 builders, 0/2 researchers) pasted where it sits."""
    strip = cv2.imread(str(FIXTURES / "counters_0_of_7_and_0_of_2.png"))
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    frame[570:605, 1165:1290] = strip
    return frame


from cocmacro import defaults

BUILDERS = defaults.REGIONS["free_builders"]          # the regions the program really uses
RESEARCHERS = defaults.REGIONS["free_researchers"]


def test_free_count_reads_zero_on_the_real_counters():
    frame = _live_frame()
    assert vision.free_count(frame, BUILDERS) == 0
    assert vision.free_count(frame, RESEARCHERS) == 0


def test_free_count_other_first_digit_means_some_free():
    frame = _live_frame()
    seven = ocr._load()["imgs"][list(ocr._load()["labels"]).index("7")]   # loot-font 7, a clearly non-zero shape
    patch = (cv2.resize((seven > 0.5).astype(np.uint8) * 255, (13, 14)))
    y0, x0 = 581, 1173
    frame[y0:y0 + 14, x0:x0 + 13] = np.stack([patch] * 3, axis=-1)    # replaces the first glyph
    assert vision.free_count(frame, BUILDERS) == 1


@pytest.mark.parametrize("shape", [(9, 9, 3), (5, 5, 3), (1, 1, 3), (0, 0, 3)])
def test_frame_smaller_than_10x10_returns_neutral(shape):
    frame = np.zeros(shape, dtype=np.uint8)
    region = (0.0, 0.0, 1.0, 1.0)
    assert vision.cost_is_red(frame, region) is False
    assert vision.storage_full(frame, region) is None
    assert vision.free_count(frame, region) is None


@pytest.mark.parametrize("region", [
    (0.6, 0.6, 0.4, 0.4),
    (0.8, 0.2, 0.2, 0.8),
    (0.2, 0.8, 0.8, 0.2),
    (0.5, 0.5, 0.5, 0.5),
])
def test_inverted_or_empty_region_returns_neutral(region):
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    assert vision.cost_is_red(frame, region) is False
    assert vision.storage_full(frame, region) is None
    assert vision.free_count(frame, region) is None


GOLD_HUE, ELIXIR_HUE = (18, 40), (135, 175)


def test_storage_full_hue_gate_rejects_the_wrong_colour():
    frame = np.zeros((40, 200, 3), dtype=np.uint8)
    frame[:, :] = (30, 200, 240)    # BGR gold-yellow over the whole bar
    assert vision.storage_full(frame, (0, 0, 1, 1), hue=GOLD_HUE) is True
    assert vision.storage_full(frame, (0, 0, 1, 1), hue=ELIXIR_HUE) is False


def test_storage_not_full_on_the_real_bars():
    frame = cv2.imread(str(FIXTURES / "storage_bars_not_full.png"))
    assert frame is not None
    assert vision.storage_full(frame, (0.815, 0.030, 0.950, 0.060), hue=GOLD_HUE) is False
    # the translucent bar over a busy village can be ambiguous (None); the bot treats None as not full
    assert vision.storage_full(frame, (0.815, 0.085, 0.950, 0.115), hue=ELIXIR_HUE) in (False, None)


def test_cost_is_red_on_the_real_salmon_price():
    """Real capture: 23 100 000 shown in the game's 'cannot pay' colour on both Mejorar buttons."""
    frame = cv2.imread(str(FIXTURES / "wall_panel_cost_red.png"))
    assert vision.cost_is_red(frame, (0.545, 0.745, 0.620, 0.775)) is True
    assert vision.cost_is_red(frame, (0.625, 0.745, 0.700, 0.775)) is True
    assert vision.cost_is_red(frame, (0.05, 0.05, 0.15, 0.10)) is False    # village scenery, no price


def test_free_count_reads_one_free_builder_on_the_real_counter():
    strip = cv2.imread(str(FIXTURES / "counters_1_of_7_and_0_of_2.png"))
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    frame[570:605, 1165:1290] = strip
    assert vision.free_count(frame, BUILDERS) == 1       # '1/7'
    assert vision.free_count(frame, RESEARCHERS) == 0    # '0/2'


def _top(name):
    return cv2.imread(str(FIXTURES / name))


def test_find_wall_spot_follows_the_block_when_the_camera_moves():
    """Same village, two camera positions: the spot is just above the block's lowest point in both."""
    for name, bottom_x, bottom_y in (("wall_block_centered_top.png", 726, 202), ("wall_block_panned_top.png", 722, 134)):
        frame = _top(name)
        x, y = vision.find_wall_spot(frame)
        assert abs(x * frame.shape[1] - bottom_x) < 20, name
        assert 8 <= bottom_y - y * frame.shape[0] <= 22, name        # inside the block, near its bottom edge


def test_find_wall_spot_is_none_without_a_block():
    assert vision.find_wall_spot(np.zeros((300, 600, 3), dtype=np.uint8)) is None
    assert vision.find_wall_spot(np.full((300, 600, 3), (40, 120, 60), dtype=np.uint8)) is None     # plain grass


def test_real_bars_half_filled_from_the_icon_are_not_full():
    """Real capture: 17.6 M gold and 16.1 M elixir fill roughly half of each bar, from the right."""
    frame = cv2.imread(str(FIXTURES / "storage_bars_half_full.png"))
    assert frame is not None
    assert vision.storage_full(frame, (0.815, 0.030, 0.950, 0.060), hue=GOLD_HUE) is False
    assert vision.storage_full(frame, (0.815, 0.085, 0.950, 0.115), hue=ELIXIR_HUE) is False


def test_find_wall_spot_never_points_at_the_game_buttons():
    """Seen live: with the camera zoomed in, the block's lowest visible point was under the gem bars and the
    click opened the shop. A spot inside the HUD is refused."""
    steel = cv2.cvtColor(np.uint8([[[95, 55, 155]]]), cv2.COLOR_HSV2BGR)[0, 0]
    under_hud = np.zeros((729, 1296, 3), dtype=np.uint8)
    under_hud[0:200, 1050:1250] = steel              # lowest point near (0.89, 0.27): inside the top-right bars
    assert vision.find_wall_spot(under_hud) is None
    clear = np.zeros((729, 1296, 3), dtype=np.uint8)
    clear[0:300, 500:900] = steel                    # lowest point near (0.54, 0.41): open village
    assert vision.find_wall_spot(clear) is not None
