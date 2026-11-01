from cocmacro import overlay

SIZE = (951, 535)
BANNER_H = 56


def px(rect):
    return (rect[0] * SIZE[0], rect[1] * SIZE[1], rect[2] * SIZE[0], rect[3] * SIZE[1])


def overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_banner_never_covers_the_zone_to_mark():
    zones = {"timer": (0.451, 0.045, 0.552, 0.082), "gold": (0.04, 0.106, 0.135, 0.133),
             "damage": (0.922, 0.774, 0.971, 0.809)}
    for name, rect in zones.items():
        box = overlay.banner_box(SIZE, BANNER_H, 520, avoid=px(rect), order=("middle", "top", "bottom"))
        assert not overlaps(box, px(rect)), name
        assert 0 <= box[0] and box[2] <= SIZE[0] and 0 <= box[1] and box[3] <= SIZE[1], name


def test_banner_prefers_top_when_nothing_is_in_the_way():
    box = overlay.banner_box(SIZE, BANNER_H, 520, avoid=None, order=("top", "middle", "bottom"))
    assert box[1] < 60


def test_banner_falls_back_when_the_first_slot_is_taken():
    top_zone = (0.3, 0.0, 0.7, 0.15)                       # sits where "top" would be
    box = overlay.banner_box(SIZE, BANNER_H, 520, avoid=px(top_zone), order=("top", "middle", "bottom"))
    assert box[1] > 100
