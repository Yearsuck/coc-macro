from cocmacro import geometry


def test_roundtrip_px_rel():
    size = (1296, 729)
    px = geometry.to_px((0.5, 0.25), size)
    rel = geometry.to_rel(px, size)
    assert abs(rel[0] - 0.5) <= 1 / 1296
    assert abs(rel[1] - 0.25) <= 1 / 729


def test_aspect():
    assert geometry.aspect((1296, 729)) == 1296 / 729
