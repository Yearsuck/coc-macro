import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from cocmacro import ocr

FIX = Path(__file__).parent / "fixtures"
DATA = json.loads((FIX / "labels.json").read_text())


@pytest.mark.parametrize("text,expected", [
    ("3 482 103", 3482103), ("335.532", 335532), ("1545", 1545),
    ("3 482 103", 3482103), ("12O", None), ("", None), ("  ", None),
])
def test_parse_digits(text, expected):
    assert ocr.parse_digits(text) == expected


@pytest.mark.parametrize("fname,key,value", DATA["labels"])
def test_fixture_numbers(fname, key, value):
    img = cv2.imread(str(FIX / fname))
    assert ocr.read_number(img, tuple(DATA["regions"][key])) == value


def test_blank_region_is_none():
    img = np.zeros((729, 1296, 3), dtype=np.uint8)
    assert ocr.read_number(img, tuple(DATA["regions"]["gold"])) is None


def test_non_digit_shapes_are_none():
    img = np.zeros((729, 1296, 3), dtype=np.uint8)
    x0, y0, x1, y1 = (int(v) for v in (52, 77, 175, 97))
    cv2.circle(img, (110, 87), 8, (255, 255, 255), -1)       # one white blob, not a digit
    cv2.rectangle(img, (130, 78), (160, 96), (255, 255, 255), -1)
    assert ocr.read_number(img, tuple(DATA["regions"]["gold"])) is None


@pytest.mark.parametrize("fname,seconds", [("f004.png", 28), ("f019.png", 171), ("f030.png", 162),
                                           ("f051.png", 156), ("f052.png", 148)])
def test_read_time_left(fname, seconds):
    img = cv2.imread(str(FIX / fname))
    assert ocr.read_time_left(img, tuple(DATA["regions"]["timer"])) == seconds


def test_read_time_left_none_when_no_timer():
    assert ocr.read_time_left(np.zeros((729, 1296, 3), np.uint8), tuple(DATA["regions"]["timer"])) is None


@pytest.mark.parametrize("digits_before,digits_after,expected", [
    ("2", "51", 171), ("", "45", 45), ("0", "05", 5), ("2", "75", None), ("", "", None), ("22", "10", None)])
def test_time_from_groups(digits_before, digits_after, expected):
    assert ocr.time_from_groups(digits_before, digits_after) == expected


@pytest.mark.parametrize("region", [(0.5, 0.5, 0.5, 0.5), (0.5, 0.5, 0.501, 0.501), (0.6, 0.6, 0.5, 0.5)])
def test_degenerate_regions_give_none_not_a_crash(region):
    img = np.zeros((729, 1296, 3), dtype=np.uint8)
    assert ocr.read_number(img, region) is None
    assert ocr.read_time_left(img, region) is None


CROPS = sorted((FIX / "crops").glob("*.png"))


@pytest.mark.parametrize("path", CROPS, ids=[p.stem for p in CROPS])
def test_real_crops_that_used_to_fail(path):
    """Loot crops from villages with different skins that the bot could not read (or misread:
    2 660 193 came out as 2860193). The expected number is in the file name."""
    expected = int(path.stem.rsplit("_", 1)[1])
    assert ocr.read_crop(cv2.imread(str(path))) == expected


def test_touching_digits_are_split():
    two = np.hstack([np.ones((20, 11), np.uint8), np.ones((20, 12), np.uint8)])    # two glyphs fused, no gap
    two[:, 10:13] = 0
    two[8:12, 10:13] = 1                                                          # a thin bridge between them
    pieces = ocr._split_touching(two, ref_w=11.5)
    assert len(pieces) == 2
    assert ocr._split_touching(np.ones((20, 11), np.uint8), ref_w=11.5)[0].shape == (20, 11)   # one digit stays one


def test_ambiguous_digit_is_rejected_not_guessed():
    g = np.zeros((18, 12), np.uint8)
    g[2:16, 3:9] = 1
    f, a = ocr.features(g)
    imgs = np.stack([f, f + 0.001])                      # a '6' and an '8' that look the same to us
    assert ocr.classify_in(g, imgs, np.array([a, a]), np.array(["6", "8"])) is None
    assert ocr.classify_in(g, imgs[:1], np.array([a]), np.array(["6"])) == "6"      # only one candidate: fine
