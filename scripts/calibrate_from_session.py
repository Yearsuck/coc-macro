"""Build data/config.json + data/templates from a capture_clicks session.
Usage: calibrate_from_session.py SESSION_DIR   (needs PYTHONPATH=.)
Maps clicks by index (from the 2026-11-01 session): see CLICKS below."""
import json
import sys
from pathlib import Path

import cv2

from cocmacro import config, game, geometry, templates, winctl

sess = Path(sys.argv[1])
data = Path("data")
tpl_dir = data / "templates"
clicks = {c["i"]: c for c in json.loads((sess / "clicks.json").read_text()) if c["event"] == "down"}
# name -> (click index, frame to cut the template from)
CLICKS = {"battle": 1, "find": 2, "attack": 3, "next": 4, "end": 52, "ok": 53, "back": 54}
size = (1296, 729)
cfg = config.Config(aspect=geometry.aspect(size))
labels = json.loads(Path("tests/fixtures/labels.json").read_text())
cfg.regions = {k: tuple(v) for k, v in labels["regions"].items()}
for name, i in CLICKS.items():
    c = clicks[i]
    cfg.buttons[name] = (c["x"], c["y"])
    frame = cv2.imread(str(sess / f"{i:03d}_before.png"))
    templates.save_template(name, frame, (c["x"], c["y"]), cfg.tpl_size, tpl_dir)
# 'Rendirse' (red, <50%) sits where 'Terminar batalla' does: same click, template from frame 51
cfg.buttons["surrender"] = cfg.buttons["end"]
templates.save_template("surrender", cv2.imread(str(sess / "051_before.png")), cfg.buttons["end"], cfg.tpl_size, tpl_dir)
data.mkdir(exist_ok=True)
config.save(cfg, data / "config.json")

# self-check on the session's own frames
def has(frame_idx, name):
    return templates.match(cv2.imread(str(sess / f"{frame_idx:03d}_before.png")), name, tpl_dir)
checks = {
    "home on 001": has(1, "battle"), "no home on 004": not has(4, "battle"),
    "scout on 004": has(4, "next"), "no scout on 019": not has(19, "next"),
    "surrender on 051": has(51, "surrender"), "end on 052": has(52, "end"),
    "confirm on 053": has(53, "ok"), "no confirm on 052": not has(52, "ok"),
    "results on 054": has(54, "back"), "no results on 053": not has(53, "back"),
}
for k, v in checks.items():
    print(("OK  " if v else "FAIL"), k)
print("all ok" if all(checks.values()) else "SOME FAILED")
