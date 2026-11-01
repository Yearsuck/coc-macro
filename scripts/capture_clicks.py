"""Log the user's left clicks inside the game window, with a screenshot per click.
For each click: NNN_before.png (taken at press, before the game reacts) and
NNN_after.png (1.2 s later), plus clicks.json (relative position, time, type).
Usage: capture_clicks.py OUT_DIR [MAX_SECONDS=600]   (press F9 to finish)"""
import json
import sys
import threading
import time
from pathlib import Path

import cv2
from pynput import keyboard, mouse

from cocmacro import winctl

out = Path(sys.argv[1])
max_s = float(sys.argv[2]) if len(sys.argv) > 2 else 600
out.mkdir(parents=True, exist_ok=True)
win = winctl.find_game_window()
log, n, t0 = [], 0, time.time()
done, lock = threading.Event(), threading.Lock()


def save(path, img):
    cv2.imwrite(str(path), img)


def after(idx):
    try:
        save(out / f"{idx:03d}_after.png", winctl.capture(win))
    except Exception as e:  # window lost
        print("after-capture failed:", e)


def on_click(x, y, button, pressed):
    global n
    if button != mouse.Button.left:
        return
    pos = winctl.screen_to_rel(win, int(x), int(y))
    with lock:
        if pressed and pos is not None:
            n += 1
            idx = n
            save(out / f"{idx:03d}_before.png", winctl.capture(win))
            log.append({"i": idx, "t": round(time.time() - t0, 2), "x": round(pos[0], 4),
                        "y": round(pos[1], 4), "event": "down"})
            threading.Timer(1.2, after, args=(idx,)).start()
        elif not pressed and n and pos is not None:
            log.append({"i": n, "t": round(time.time() - t0, 2), "x": round(pos[0], 4),
                        "y": round(pos[1], 4), "event": "up"})


ml = mouse.Listener(on_click=on_click)
kl = keyboard.GlobalHotKeys({"<f9>": done.set})
ml.start(); kl.start()
print(f"Grabando clics en {out}. F9 para terminar (max {max_s:.0f}s).", flush=True)
done.wait(max_s)
time.sleep(1.5)
ml.stop(); kl.stop()
(out / "clicks.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
print(f"{n} clics guardados", flush=True)
