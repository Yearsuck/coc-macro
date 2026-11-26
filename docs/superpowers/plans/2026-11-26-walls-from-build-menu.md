# Walls from the Construir menu: any level, anywhere

**Goal.** Walls mode upgrades walls on its own whatever their level and wherever they are in the village. Today it
works only when walls are piled in one block of a known colour.

## Why the current routine fails (seen live 2026-11-26, one account, TH with walls 17-20)

`upgrade_walls` zooms out, finds "the biggest blob of blue (or gold) pixels" with `vision.find_wall_spot` and clicks
just above its lowest point. On the live village:

- The blob is the gold/cream level-17 walls; its lowest point touches grey level-19/20 walls. The click lands on the
  border, so it selects whichever level is there (level 19 = 6.4M, more than the 6.0M of gold) and then "+1" cannot
  add anything: `No se pudo anadir ningun muro con gold`.
- Walls of another colour (each level has its own look), walls spread around the base instead of piled, or a
  block under the HUD: no spot at all, or a click on a building.

Captures: `tests/fixtures/raw/live-2026-11-26/` (git-ignored): `old_wall_spot_zoomed.png` (red circle = old click).

## What the game offers (verified live by hand)

1. Construir menu, builders tab, filters `Permanente` + `Coste min.` (what the busy routine already sets): the list
   holds one row per wall level, `Muro x N` (N walls of that level), sorted by price with everything else
   (`build_list_wall_rows.png`: `Muro x 285` lvl 18 4.8M, `Muro x 37` lvl 19 6.4M, `Muro x 3` lvl 20 8M).
   The first `Muro` row going down is the cheapest wall level.
2. Tapping a `Muro` row (unlike other rows, which open the "Mejorar tu ..." window) **selects one wall of that level
   and moves the camera to it** (`wall_selected_menu_open.png`). Level and position do not matter.
3. With the menu open the wall bar is drawn in two rows; closing the menu with its X keeps the wall selected and the
   bar goes back to the usual single row of 5/6 buttons (`wall_selected_menu_closed.png`). From there the existing
   code works unchanged: `_wall_bar_shift`, `Mejorar mas`, `+1` until the cap, item-button guard, confirm dialog.
4. Type filters are exclusive (Defensa replaces Permanente). **Resource filter `elixir` + `Coste min.` (Permanente
   off) puts the walls near the top** (user's tip, verified: `build_list_elixir_costmin.png`, `Muro x 25` lvl 13 at
   1.2M is the 2nd row). That row is the cheapest level, which the Permanente list had hidden among the first rows;
   tapping it selected a lone level-12 wall under the block (`wall_lvl12_selected.png`) that the old finder could
   never reach. Walls below level 9 cannot be paid with elixir and would not be listed: gold filter as fallback.
5. Pressing the filter button while the menu is NOT open hits the gold bar and opens the gem shop
   (`shop_opened_by_mistake.png`, nothing bought). Every filter press must follow a `_menu_opened` check.

## Design

New selection step, everything after it stays:

```
_select_cheapest_wall(scr, cfg, log, check, sleep) -> bool
  open Construir (build); _menu_opened or give up
  builders tab; filters elixir + Coste min, Permanente and Heroe cleared (reuse _select_filter/_clear_filter)
  look at the first rows; if no Muro row, scroll: for up to MAX_WALL_SCROLLS drags
  still none -> same with the gold filter instead of elixir (walls below level 9)
      look for the 'Muro' name template inside LIST_X x LIST_Y; take the topmost hit
      none -> drag the list up by ~4 rows; if the list did not move (end) -> stop
  no Muro row -> log "No hay muros en la lista", close menu, False
  tap the row on its name (never on the price) ; close the menu with its X
  True only if 'wall_panel' (Marcar fila) is seen on the bar row
```

`upgrade_walls`:
- Selection: `_select_cheapest_wall` first. Fallback to the old `wall_spot` path only if the menu path fails
  before tapping (template missing on an old config). The zoom-out is no longer needed for the new path.
- Per resource (gold, then elixir) select again (the previous batch upgraded the cheapest walls; the cheapest
  row may now be another level).
- Within one call, when a resource's batch hit the cap because **no more walls of that level** were left while the
  price was still payable, select again and repeat (next level), up to `MAX_LEVEL_PASSES = 3`. The bot's outer
  `MAX_SPEND_ROUNDS` loop already re-calls walls while a storage is full.
- Filters are remembered by the game, so both sides clean up: the wall routine puts back Permanente and clears the
  resource filter before closing the menu, and `_first_row_upgrade` also clears the gold/elixir/dark resource
  filters (today it only clears Heroe), so a run stopped half way cannot leave the busy/surplus list filtered.
  New templates `filter_gold(_on)`, `filter_elixir(_on)`, `filter_dark(_on)`.

New pieces:
- Template `wall_row_name.png`: the word "Muro" in the list's white row font, cut from the live capture
  (same scale handling as the other templates). Bundled defaults + calibration entry like `filter_*`.
- `vision.wall_rows(frame)` is NOT needed: the template match over the list column is enough; a test proves it
  ignores `Muralla`-like or other names (`Monolito`, `Mortero`).
- Drag helper on `_Screen`: `drag(x0, y0, x1, y1)` built on `winctl.post_mouse` (down, moves, up), as
  `scripts/spike_drag.py` already does.

Surplus builders (user requirement: with 2+ free builders, start upgrades until 1 is left). Already in
`spend_free_slots` (`_spend("surplus")` = `upgrade_busy(only=builders, keep=1)`), but `_first_row_upgrade` presses the
first allowed row, and with Permanente + Coste min. a `Muro x N` row can be the cheapest (lvl-13 walls at 1.2M):
tapping it selects a wall instead of opening "Mejorar tu ...", the routine logs `No aparece la ventana de mejora` and
the builders stay idle. Fix: `_allowed_row` skips rows whose name matches `wall_row_name` (walls are instant and are
the wall routine's job), same double-look rule as `NEVER_UPGRADE`. Test with a list frame whose first row is a wall.

Not changed: storage checks, builder wait, surplus, `_recover`, the bar handling, gem guards.

## Tasks (TDD, one commit each, branch `fix/walls-from-build-menu` off `develop`)

1. `test(walls)`: template finds the `Muro` rows in `build_list_wall_rows.png` / `build_list_walls_scrolled.png`
   (y of each row) and none in a list without walls; fixture crops committed under `tests/fixtures/` (no player
   names in them). Then add the template + matcher.
2. `feat(game)`: `_Screen.drag`; unit test with a fake winctl. Resource filter templates (cut from
   `filter_popup.png`) and `_first_row_upgrade` clearing them, with tests.
3. `feat(walls)`: `_select_cheapest_wall` with a fake Screen (list frames sequence: no wall -> scroll -> wall row;
   end of list; menu never opens; panel not seen after tap).
4. `feat(walls)`: `upgrade_walls` uses it, re-selects per resource and per level pass, fallback kept. Existing
   `test_upgrades.py` wall tests adapted, new ones for the level pass.
5. `docs`: user guide + architecture paragraph.

## Verification

- `pytest` full suite, each new test with a timeout.
- Live, read-only first: script that runs `_select_cheapest_wall` and stops (shows the wall selected), on this
  account at two camera positions (zoomed in elsewhere, zoomed out).
- Live, spending: one `upgrade_walls` call with 6.0M gold / 6.0M elixir (cheapest level 4.8M): expect one wall per
  resource, gold and elixir each drop ~4.8M. Then a full walls-mode run until a storage fills, if the user wants.

## Not verified / open

- Accounts with the list in another language (template is the Spanish word, as all other templates).
- Accounts with only one wall level left or none (list without `Muro`): handled by "no Muro row", untested live.
- Whether `Mejorar mas` "+1" stops at the last wall of the level the same way it stops at what you can pay
  (assumed: the price stops changing, which the cap logic already treats as the end).
