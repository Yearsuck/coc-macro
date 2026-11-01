"""Relative (0-1) <-> pixel coordinate helpers for the game client area."""


def to_px(rel: tuple[float, float], size: tuple[int, int]) -> tuple[int, int]:
    return round(rel[0] * size[0]), round(rel[1] * size[1])


def to_rel(px: tuple[int, int], size: tuple[int, int]) -> tuple[float, float]:
    return px[0] / size[0], px[1] / size[1]


def aspect(size: tuple[int, int]) -> float:
    return size[0] / size[1]


def rect_to_px(rect: tuple[float, float, float, float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0 = to_px((rect[0], rect[1]), size)
    x1, y1 = to_px((rect[2], rect[3]), size)
    return x0, y0, x1, y1
