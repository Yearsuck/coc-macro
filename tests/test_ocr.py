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
