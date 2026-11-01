# Spike: drag in background (2026-11-01)

- Village camera pan via `WM_MOUSEMOVE` + `MK_LBUTTON` with the game NOT in foreground (Orca focused): **PASS**
  (~45% of pixels changed, village visibly shifted). Script: `scripts/spike_drag.py`.
- Troop deployment drag / long press during a real attack: **PENDING** (needs user supervising a throwaway attack).
- Capture of a minimised window: not tested (would minimise the user's game); `capture()` raises `WindowMinimized` via `IsIconic`.
- Provisional decision: `player_mode = background`. Revisit after the attack test.
