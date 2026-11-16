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


def test_cost_is_red_ignores_a_speck():
    frame = np.zeros((100, 300, 3), dtype=np.uint8)
    frame[0, :5, :] = (0, 0, 255)
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


def test_free_count_ignores_other_text_where_the_counter_would_be():
    """Seen live: a Construir list ('187 000') sat under the counter regions and was read as 'some free'."""
    strip = cv2.imread(str(FIXTURES / "menu_text_over_counters.png"))
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    frame[565:610, 1160:1296] = strip
    assert vision.free_count(frame, BUILDERS) is None
    assert vision.free_count(frame, RESEARCHERS) is None


def test_find_wall_spot_refuses_the_bottom_buttons_too():
    steel = cv2.cvtColor(np.uint8([[[95, 55, 155]]]), cv2.COLOR_HSV2BGR)[0, 0]
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    frame[500:700, 40:300] = steel                  # a block whose lowest point is over Batalla (~0.1, 0.95)
    assert vision.find_wall_spot(frame) is None
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    frame[500:720, 1150:1280] = steel               # ... or over Construir (~0.94, 0.97)
    assert vision.find_wall_spot(frame) is None


def test_real_full_bars_are_full():
    """Real capture with 29.5 M gold and 30 M elixir: both bars filled to the left end (first time seen)."""
    frame = cv2.imread(str(FIXTURES / "storage_bars_full.png"))
    assert frame is not None
    assert vision.storage_full(frame, (0.815, 0.030, 0.950, 0.060), hue=GOLD_HUE) is True
    assert vision.storage_full(frame, (0.815, 0.085, 0.950, 0.115), hue=ELIXIR_HUE) is True


def test_first_upgrade_row_in_every_tab_of_the_menu():
    """Real captures of the Construir list: the first AVAILABLE row, below the progress bars and headers."""
    for name, row_center_px in (("menu_researchers_tab.png", 120),       # no 'Filtrado' banner on this tab
                                ("menu_builders_tab_filtered.png", 301),  # five busy builders + banner above
                                ("menu_pets_tab.png", 143)):              # 'Asignado' header above
        frame = cv2.imread(str(FIXTURES / name))
        spot = vision.first_upgrade_row(frame)
        assert spot is not None, name
        assert abs(spot[1] * frame.shape[0] - row_center_px) < 9, (name, spot)
        assert 0.80 < spot[0] < 0.95                                    # inside the list column


def test_first_upgrade_row_is_none_without_a_list():
    assert vision.first_upgrade_row(cv2.imread(str(FIXTURES / "village_no_menu.png"))) is None
    assert vision.first_upgrade_row(np.zeros((729, 1296, 3), dtype=np.uint8)) is None
    assert vision.first_upgrade_row(np.zeros((5, 5, 3), dtype=np.uint8)) is None


def test_cost_is_red_for_a_short_price_in_a_big_region():
    """Review finding: a share of the REGION missed short prices. Real salmon price, region three times bigger."""
    frame = cv2.imread(str(FIXTURES / "wall_panel_cost_red.png"))
    assert vision.cost_is_red(frame, (0.53, 0.735, 0.635, 0.79)) is True


def test_cost_is_red_false_for_white_digits_in_a_big_region():
    frame = np.zeros((300, 600, 3), dtype=np.uint8)
    cv2.putText(frame, "840", (250, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    assert vision.cost_is_red(frame, (0.0, 0.0, 1.0, 1.0)) is False
    red = np.zeros((300, 600, 3), dtype=np.uint8)
    cv2.putText(red, "840", (250, 150), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (110, 110, 255), 3)   # BGR salmon
    assert vision.cost_is_red(red, (0.0, 0.0, 1.0, 1.0)) is True


def test_first_upgrade_row_handles_a_thin_top_piece_and_the_end_of_the_list():
    sand = cv2.cvtColor(np.uint8([[[13, 110, 160]]]), cv2.COLOR_HSV2BGR)[0, 0]
    thin = np.zeros((729, 1296, 3), dtype=np.uint8)
    thin[100:107, 1050:1280] = sand                    # a 7 px top piece (icon below it), then more sand
    thin[112:150, 1050:1280] = sand
    spot = vision.first_upgrade_row(thin)
    assert spot is not None and abs(spot[1] * 729 - (100 + 24)) < 4      # anchored on the TOP piece, not the lower one
    tabs = np.zeros((729, 1296, 3), dtype=np.uint8)
    tabs[600:641, 1050:1280] = sand                    # sand that starts too low: that is the tab bar
    assert vision.first_upgrade_row(tabs) is None
    unbroken = np.zeros((729, 1296, 3), dtype=np.uint8)
    unbroken[400:729, 1050:1280] = sand                # sand up to the end of the list area
    assert vision.first_upgrade_row(unbroken) is not None


def _ui(name):
    import cv2
    from pathlib import Path
    return cv2.imread(str(Path(__file__).parent / "fixtures" / "ui" / name))


from cocmacro.defaults import REGIONS as _REGIONS
DARK_REGION = _REGIONS["storage_dark"]


def test_dark_storage_full_on_real_captures():
    assert vision.dark_storage_full(_ui("storage_bars_full.png"), DARK_REGION) is True
    assert vision.dark_storage_full(_ui("storage_bars_not_full.png"), DARK_REGION) is False
    assert vision.dark_storage_full(_ui("storage_bars_half_full.png"), DARK_REGION) is False


def test_dark_storage_full_invalid_inputs():
    assert vision.dark_storage_full(None, DARK_REGION) is None
    assert vision.dark_storage_full(np.zeros((100, 100, 3), np.uint8), (0.5, 0.5, 0.5, 0.5)) is None


def test_native_dialog_village_noisy_frame_returns_none():
    np.random.seed(42)
    frame = np.random.randint(50, 200, (729, 1296, 3), dtype=np.uint8)
    assert vision.native_dialog(frame) is None


def test_native_dialog_synthetic_frame_with_box_and_blue_button_returns_point():
    # 1296x729 village-like noisy frame
    np.random.seed(42)
    frame = np.random.randint(50, 200, (729, 1296, 3), dtype=np.uint8)

    # centred 551x165 box of BGR (30, 28, 25)
    bx0 = (1296 - 551) // 2   # 372
    by0 = (729 - 165) // 2    # 282
    bx1 = bx0 + 551           # 923
    by1 = by0 + 165           # 447
    frame[by0:by1, bx0:bx1] = (30, 28, 25)

    # near-white (235, 233, 232) text rows in its upper part
    frame[by0 + 20:by0 + 35, bx0 + 30:bx0 + 300] = (235, 233, 232)
    frame[by0 + 45:by0 + 60, bx0 + 30:bx0 + 450] = (235, 233, 232)

    # pale-blue (212, 202, 171) text-like block of at least 30x10 px in its lower left
    # Lower 40% starts at by0 + int(165 * 0.6) = by0 + 99
    btn_y0 = by0 + 115
    btn_y1 = btn_y0 + 15
    btn_x0 = bx0 + 30
    btn_x1 = btn_x0 + 40
    frame[btn_y0:btn_y1, btn_x0:btn_x1] = (212, 202, 171)

    spot = vision.native_dialog(frame)
    assert spot is not None
    # relative centre of the button block
    cx_px = spot[0] * 1296
    cy_px = spot[1] * 729
    assert btn_x0 <= cx_px <= btn_x1
    assert btn_y0 <= cy_px <= btn_y1


def test_native_dialog_grey_box_no_blue_returns_none():
    np.random.seed(42)
    frame = np.random.randint(50, 200, (729, 1296, 3), dtype=np.uint8)
    bx0 = (1296 - 551) // 2
    by0 = (729 - 165) // 2
    frame[by0:by0 + 165, bx0:bx0 + 551] = (30, 28, 25)
    frame[by0 + 20:by0 + 35, bx0 + 30:bx0 + 300] = (235, 233, 232)
    assert vision.native_dialog(frame) is None


def test_native_dialog_small_grey_box_in_corner_returns_none():
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    # small box in corner
    frame[10:60, 10:110] = (30, 28, 25)
    frame[40:55, 20:60] = (212, 202, 171)
    assert vision.native_dialog(frame) is None


def test_native_dialog_fully_dark_frame_returns_none():
    frame = np.zeros((729, 1296, 3), dtype=np.uint8)
    assert vision.native_dialog(frame) is None


def test_native_dialog_invalid_inputs_returns_none():
    assert vision.native_dialog(None) is None
    assert vision.native_dialog(np.zeros((729, 1296), dtype=np.uint8)) is None
    assert vision.native_dialog("not a frame") is None
    assert vision.native_dialog(np.zeros((5, 5, 3), dtype=np.uint8)) is None


def test_native_dialog_ignores_stray_blue_pixels_to_the_right():
    # 1296x729 village-like noisy frame
    np.random.seed(42)
    frame = np.random.randint(50, 200, (729, 1296, 3), dtype=np.uint8)

    # centred 551x165 box of BGR (30, 28, 25)
    bx0 = (1296 - 551) // 2   # 372
    by0 = (729 - 165) // 2    # 282
    bx1 = bx0 + 551           # 923
    by1 = by0 + 165           # 447
    frame[by0:by1, bx0:bx1] = (30, 28, 25)

    # near-white text rows
    frame[by0 + 20:by0 + 35, bx0 + 30:bx0 + 300] = (235, 233, 232)
    frame[by0 + 45:by0 + 60, bx0 + 30:bx0 + 450] = (235, 233, 232)

    # main pale-blue button block in lower left (40x15 px = 600 px)
    btn_y0 = by0 + 115
    btn_y1 = btn_y0 + 15
    btn_x0 = bx0 + 30
    btn_x1 = btn_x0 + 40
    frame[btn_y0:btn_y1, btn_x0:btn_x1] = (212, 202, 171)

    # second small blue block (20 px) far to the right in the lower part of the box
    stray_y0 = by0 + 115
    stray_y1 = stray_y0 + 4
    stray_x0 = bx0 + 450
    stray_x1 = stray_x0 + 5
    frame[stray_y0:stray_y1, stray_x0:stray_x1] = (212, 202, 171)

    spot = vision.native_dialog(frame)
    assert spot is not None
    cx_px = spot[0] * 1296
    cy_px = spot[1] * 729
    assert btn_x0 <= cx_px <= btn_x1
    assert btn_y0 <= cy_px <= btn_y1



def test_native_dialog_with_two_buttons_returns_the_right_one():
    """CANCELAR / REINTENTAR: Android puts the affirmative action on the right."""
    frame = np.full((729, 1296, 3), 120, np.uint8)
    bx0, by0 = 372, 282
    frame[by0:by0 + 165, bx0:bx0 + 551] = (30, 28, 25)
    frame[by0 + 20:by0 + 35, bx0 + 30:bx0 + 300] = (235, 233, 232)
    frame[by0 + 120:by0 + 135, bx0 + 30:bx0 + 110] = (212, 202, 171)       # left button, the longer text
    frame[by0 + 120:by0 + 135, bx0 + 420:bx0 + 480] = (212, 202, 171)      # right button
    x, y = vision.native_dialog(frame)
    assert (bx0 + 420) / 1296 <= x <= (bx0 + 480) / 1296 and (by0 + 120) / 729 <= y <= (by0 + 135) / 729


def _dialog_frame(box=(372, 282, 551, 165), blue=(30, 120, 80, 15), fill=1.0, white_low=False):
    """A grey frame with a dialog-like dark box (x, y, w, h) and a pale-blue block (dx, dy, w, h) inside it."""
    frame = np.full((729, 1296, 3), 120, np.uint8)
    x, y, w, h = box
    frame[y:y + h, x:x + int(w * fill)] = (30, 28, 25)
    if blue:
        dx, dy, bw, bh = blue
        frame[y + dy:y + dy + bh, x + dx:x + dx + bw] = (212, 202, 171)
    if white_low:
        frame[y + h - 45:y + h - 30, x + 30:x + 200] = (235, 233, 232)
    return frame


def test_native_dialog_reference_frame_is_found():
    assert vision.native_dialog(_dialog_frame()) is not None


@pytest.mark.parametrize("why,kwargs", [
    ("box too wide", dict(box=(60, 282, 1180, 165))),
    ("box too tall", dict(box=(372, 100, 551, 540), blue=(30, 480, 80, 15))),
    ("box too small", dict(box=(550, 330, 200, 70), blue=(20, 45, 80, 15))),
    ("box off centre", dict(box=(40, 60, 551, 165))),
    ("box only half dark", dict(fill=0.5)),
    ("too few blue pixels", dict(blue=(30, 120, 10, 10))),
    ("blue only in the upper part", dict(blue=(30, 20, 80, 15))),
    ("no blue, near-white text low in the box", dict(blue=None, white_low=True)),
])
def test_native_dialog_guards(why, kwargs):
    assert vision.native_dialog(_dialog_frame(**kwargs)) is None, why


@pytest.mark.parametrize("name,button", [("dialog_connection_lost", (0.337, 0.569)), ("dialog_inactivity", (0.354, 0.569))])
def test_native_dialog_on_real_dialogs(name, button):
    """Real captures (everything but the dialog box blacked out): 'Conexion perdida ... REINTENTAR', seen
    live for the first time after the detector was written from the inactivity dialog alone."""
    x, y = vision.native_dialog(cv2.imread(str(FIXTURES / f"{name}.png")))
    assert abs(x - button[0]) < 0.01 and abs(y - button[1]) < 0.01


@pytest.mark.parametrize("name", ["village_no_menu", "menu_builders_tab_filtered", "menu_pets_tab", "storage_bars_full",
                                  "wall_panel_cost_red", "search_failed"])
def test_native_dialog_is_not_seen_on_game_screens(name):
    assert vision.native_dialog(cv2.imread(str(FIXTURES / f"{name}.png"))) is None


def test_a_block_of_gold_walls_is_found():
    """Live 2026-11-16: walls of a high level are drawn gold and cream, not steel blue. The detector only knew
    the blue ones: the log said 'No veo el bloque de muros' with both storages full and a builder free, and
    walls mode never upgraded anything."""
    frame = cv2.imread(str(FIXTURES / "wall_block_gold.png"))
    x, y = vision.find_wall_spot(frame)
    assert 0.42 <= x <= 0.73 and 0.0 <= y <= 0.41               # inside the golden block, not on a neighbour
    h, w = frame.shape[:2]
    hue = cv2.cvtColor(frame[int(y * h) - 2:int(y * h) + 3, int(x * w) - 2:int(x * w) + 3], cv2.COLOR_BGR2HSV)[..., 0]
    assert 10 <= np.median(hue) <= 35                           # and the pixel under the click is a gold wall


def test_blue_walls_still_win_over_gold_things_in_the_same_village():
    """The gold detector is only a fallback: a village whose block is blue keeps the spot it always had."""
    frame = cv2.imread(str(FIXTURES / "wall_block_centered_top.png"))
    x, y = vision.find_wall_spot(frame)
    assert (round(x, 2), round(y, 2)) == (0.56, 0.63)


@pytest.mark.parametrize("why,paint", [
    ("a whole screen of sand or gold terrain", lambda f: f.__setitem__(slice(None), (60, 190, 230))),
    ("only a gold button in a corner", lambda f: f.__setitem__((slice(600, 729), slice(0, 130)), (60, 190, 230))),
])
def test_gold_that_is_not_a_wall_block_is_ignored(why, paint):
    frame = np.full((729, 1296, 3), (40, 90, 50), np.uint8)       # green grass
    paint(frame)
    assert vision.find_wall_spot(frame) is None, why


def _blocks(blue=None, gold=None, size=(729, 1296)):
    """Grass with a blue block and/or a gold block (x0, y0, x1, y1 in relative terms) painted on it."""
    f = np.full((*size, 3), (40, 90, 50), np.uint8)
    h, w = size
    for colour, box in (((150, 130, 110), blue), ((60, 190, 230), gold)):
        if box:
            x0, y0, x1, y1 = box
            f[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)] = colour
    return f


@pytest.mark.parametrize("why,kwargs,expect", [
    ("blue block bigger: blue", dict(blue=(0.10, 0.30, 0.40, 0.70), gold=(0.55, 0.30, 0.70, 0.55)), "blue"),
    ("a gold blob a bit bigger than a blue block is still not enough to switch", dict(blue=(0.10, 0.30, 0.30, 0.55), gold=(0.45, 0.20, 0.70, 0.55)), "blue"),
    ("a small blue clump next to a big gold block: gold", dict(blue=(0.10, 0.60, 0.18, 0.75), gold=(0.40, 0.05, 0.75, 0.40)), "gold"),
])
def test_blue_wins_unless_gold_is_clearly_the_wall_block(why, kwargs, expect):
    f = _blocks(**kwargs)
    x, y = vision.find_wall_spot(f)
    assert (x < 0.5) == (expect == "blue"), why


def test_gold_over_a_third_of_the_screen_is_terrain_not_walls():
    assert vision.find_wall_spot(_blocks(gold=(0.0, 0.0, 0.62, 0.55))) is None      # ~34% of the frame


def test_the_wall_block_is_found_at_another_frame_size():
    """The minimum area scales with the frame: a block that is 6% of the screen is found at any size."""
    for size in ((535, 951), (450, 800)):
        assert vision.find_wall_spot(_blocks(gold=(0.30, 0.05, 0.62, 0.35), size=size)) is not None
