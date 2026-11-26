"""The Construir list and its filter popup, matched on real captures (see tests/fixtures/README.md)."""
from pathlib import Path

import cv2
import pytest

from cocmacro import templates

UI = Path(__file__).parent / "fixtures" / "ui"
TPL = Path(__file__).resolve().parent.parent / "cocmacro" / "defaults" / "templates"


def _frame(name):
    frame = cv2.imread(str(UI / name))
    assert frame is not None, name
    return frame


@pytest.mark.parametrize("fixture, expected", [
    ("build_list_wall_rows.png", [0.316, 0.474, 0.633]),
    ("build_list_walls_scrolled.png", [0.218, 0.378]),
    ("build_list_elixir_costmin.png", [0.479]),
    ("build_list_no_walls.png", []),
    ("build_list_top_no_walls.png", []),
    ("wall_selected_menu_closed.png", []),
])
def test_wall_rows_are_found_top_to_bottom_on_the_name_column(fixture, expected):
    hits = templates.find_all(_frame(fixture), "wall_row_name", TPL)
    assert len(hits) == len(expected)
    for (x, y), want in zip(hits, expected):
        assert y == pytest.approx(want, abs=0.01) and x == pytest.approx(0.795, abs=0.01)


@pytest.mark.parametrize("fixture, on", [("filter_popup_gold_on.png", "gold"), ("filter_popup_elixir_on.png", "elixir"),
                                         ("filter_popup_dark_on.png", "dark"), ("filter_popup_resources_off.png", None)])
def test_the_resource_filter_that_is_on_is_told_from_the_others(fixture, on):
    frame = _frame(fixture)
    for res in ("gold", "elixir", "dark"):
        assert templates.match(frame, f"filter_{res}_on", TPL) is (res == on), res
        assert templates.match(frame, f"filter_{res}", TPL) is (res != on), res
