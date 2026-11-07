# Modes: stop when storages full, wall upgrades, busy builders

Date: 2026-11-05. Status: draft for approval. **[my decision]** = decided by me, not the user.

## Intent

Currently the bot only loops attacks. The user wants farming time to also spend what was farmed:
stop when no more loot fits and make use of free builders between attacks (walls, or the cheapest
permanent upgrade).

## Goals

1. **Stop when storages full** (checkbox, toggleable): before each search, if storages at the top
   right are full, do not attack.
2. **Walls mode**: attack; upon returning to the village, if a builder is free, upgrade walls and resume attacking.
3. **Busy builders mode**: attack until storages are full or something is free (builder, researcher,
   or pet); then upgrade and resume attacking.
4. Modes are mutually exclusive and selectable from the window (none = current behaviour).
5. **Nothing currently working is broken**: without an active mode, the attack cycle is identical.

## Non-goals / anti-goals

- Do not train troops, donate, or choose what to build except as described.
- Never spend gems. If a button prompts for gems, stop and alert.
- Do not click blindly: on an unrecognized screen, stop and alert (same as current bot).
- Stopping with F8 continues to work at any point in the new routines.

## Facts measured in the real game (secondary account, window 1296x729, 2026-11-05)

- Storages top right: gold (y~31), elixir (y~73), dark elixir (y~115), bar behind digits.
- Counters above `Construir` (Build): builders `0/7` (x~1198, y~587) and researchers `0/2` (x~1250, y~587).
  Assumed format free/total.
- `Construir` menu (button x~0.945, y~0.905; close X x~0.984, y~0.032): four counters at the bottom
  (builders, researchers, forge (anvil), pets `0/1`). Filter: button top-left (x~0.7595, y~0.032) with
  `Recurso` (Resource) (gold/elixir/dark), `Tipo` (Type) (`Ejército` (Army), `Defensa` (Defense),
  `Héroe` (Hero), `Recurso` (Resource), `Nuevo` (New), `Permanente` (Permanent)), and `Orden` (Sort)
  (`Coste máx.` (Max cost), `Coste mín.` (Min cost)). **The game remembers the last filter**: the
  bot must set `Permanente` + `Coste mín.` each time.
- After closing a menu, the camera remains zoomed out showing the entire village; the wall block is top
  center. Clicking the bottom edge of the block (~0.585, 0.335 relative) selects a wall.
- Selected wall panel (once): `Infor.` (Info), `Marcar fila` (Row select), `Mejorar más` (Upgrade more),
  `Mejorar` (Upgrade) gold, `Mejorar` elixir.
  After `Mejorar más`: `Eliminar muro (-1)` (Remove wall (-1)), `Añadir muro (+10)` (Add wall (+10)),
  `Añadir muro (+1)` (Add wall (+1)), `Mejorar` gold, `Mejorar` elixir.
  Title "Muro (Nivel N)" ("Wall (Level N)"). Costs appear in red when they cannot be paid.
- Maximum wall level: 19. When nothing remains to upgrade the button disappears (but that does not prove
  it is at max level, see Walls mode).
- Walls in the block have mixed levels (observed 16 and 17). Higher level walls are at the bottom; the user
  always starts from the bottom and works upward.

## Stop when storages full

- Read gold and elixir bars (complete fill = full). **[my decision]**: stops when **both** are full
  (attacking requires both minimums, so one full storage alone does not prevent farming the other).
- Checked on the home screen, before `Batalla` (Battle). If full: do not attack, wait (polling every
  few seconds) while the bot remains active, or stop with an alert. **[my decision]**: wait and alert in
  the log; in walls / busy modes, full storages mean "time to spend".
- Calibration: region of each bar in `config.regions`, with measured default values.

## Walls mode

After each attack, in the village:
1. Read the builders counter. If free == 0, keep attacking. If storages full and free == 0, wait until
   one frees up (polling every few seconds).
2. If free >= 1: **wall routine** (below), then open `Construir` (closes selection and resets camera),
   close it, and resume attacking.

**Wall routine** (for each resource, gold then elixir):
1. Click a wall at the bottom edge of the block (fixed point, calibratable).
2. Read title (level). If 19 or no wall panel: finish this resource.
3. Click `Mejorar más`; click `+10` repeatedly and then `+1` while the resource cost is not red.
4. When it turns red: click `Eliminar muro` once; verify cost is no longer red.
5. Click the resource `Mejorar` button; confirm if the game prompts (never if gems are requested).
6. Repeat for the other resource (reselect a wall; after upgrading, selection is usually lost).
7. Stop if no builder is free (re-read counter) or failing to select a wall.

**[my decision]** Only one retry is kept per step; if it fails twice, abort routine, log, and continue
attacking (do not stop the entire bot for this).

## Busy builders mode

After each attack, if storages full **or** anything is free (builder, researcher, or pet):
1. Open `Construir`, set `Tipo` = `Permanente`, `Orden` = `Coste mín.`, close filter selector.
2. Click the first entry in the list. Confirm if prompted (never gems).
3. Close menu and resume attacking.
If the first entry cannot be paid (cost in red), do not click; log and resume attacking.
**[my decision]**: "anything free" is read from the counters inside the `Construir` menu (builders,
researchers, pets), not just from the village screen.

## Structure (proposed)

- `cocmacro/storage.py`: reading storage bars (pure on a frame).
- `cocmacro/builders.py`: reading free/total counters and detecting "red cost" (pure on frames).
- `cocmacro/upgrades.py`: wall and builder routines, over the `Game` protocol.
- `bot.py`: after each attack, one hook per mode. Without an active mode, it is not even called.
- `config.py`: `mode` (`none`/`walls`/`busy`), `stop_when_full`, new positions with defaults.
- `gui.py`: mode selector and checkbox; no changes to existing code.
- New templates (wall panel buttons, `Construir` menu, filter) cut from real captures.

## Verification

- Unit tests with masked fixture captures for reading bars, counters, and "red".
- Bot tested with fake `Game` (covers branches: free/busy, full/not full, selection failure).
- **Validation on the secondary account**: I run each routine myself on the real game, inspecting captures
  step by step (first without spending: up to just before `Mejorar`; then one supervised real upgrade).

## Out of scope for this document / to calibrate during testing

- Exact coordinates of each button and bars (measured in real game).
- What the bot does if the wall block moves (standard camera after closing a menu is assumed).
