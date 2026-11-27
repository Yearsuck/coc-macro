"""Wall and building upgrades driven by vision helpers and a Screen protocol."""
from __future__ import annotations

from typing import Protocol

import numpy as np

from cocmacro import vision
from cocmacro.config import Config

CLICK_DELAY = 0.4
# The price of the 'Mejorar tu ...' window is only its first line: with a discount (gold pass) the full price is
# printed again below it, struck through by a RED line that read as 'cannot pay' (live: 'No hay recursos para la
# primera mejora' with 31 500 of 29 500 000 gold). Configs saved before keep the taller region, so it is cut here.
UPGRADE_COST_MAX_Y = 0.885


def _price_region(cfg: Config) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = cfg.regions["upgrade_cost"]
    return (x0, y0, x1, min(y1, UPGRADE_COST_MAX_Y))
MAX_ADDS = 250            # walls added one by one: the price turns red long before this
SPOT_OFFSETS = ((0.0, 0.0), (-0.015, -0.03), (-0.03, -0.06))   # retries inside the wall block
# The buttons of the wall bar are centred on the screen and a pitch apart. The bar has five buttons, or six when the
# account has the blue 'upgrade with an item' one, and then every button sits half a pitch further left than where it
# was calibrated (live 2026-11-16: the clicks fell in the gaps, so 'Mejorar mas' and the gold button were never pressed).
WALL_BAR_PITCH = 0.0805
CAP_UNCHANGED = 2         # looks at the price with no change after a '+1' that mean the game stopped adding walls


COIN_DX = 0.028           # the coin of the gold price sits at the top right of its button: this much right of the centre
WALL_BAR_Y_TOL = 0.06     # 'Marcar fila' must be found on the bar's row, or it is another icon
DROP_X_TOL = 0.015        # the elixir drop sits one button right of the gold coin
WALL_BAR_LOOKS = 3        # looks at the screen to measure the bar before giving up and trusting the calibration
# 'Eliminar muro' is red while there is no wall to take off and white once two or more are marked
WALL_TAKE_ONE = ("wall_take_one", "wall_take_one_on")
ITEM_MARGIN = 0.012       # a click this close to the blue item button counts as on it (the gap between buttons is 0.007)


def _wall_bar_shift(scr, cfg: Config, sleep=lambda _s: None) -> float:
    """How far the bar is from where it was calibrated, in x. 'Marcar fila' is the button one pitch left of
    'Mejorar mas'; where it is found tells the layout. The centred bar can only move in half pitches, so the
    measurement is snapped to one (a few pixels of noise do not matter) and anything beyond a pitch is a false
    match, not a layout."""
    row = cfg.buttons["wall_more"][1]
    for look in range(WALL_BAR_LOOKS):
        found = scr.find("wall_panel")            # a redraw can hide it for a moment: look again before giving up
        if found is not None and abs(found[1] - row) <= WALL_BAR_Y_TOL:
            shift = found[0] - (cfg.buttons["wall_more"][0] - WALL_BAR_PITCH)
            half = WALL_BAR_PITCH / 2
            if abs(shift) > WALL_BAR_PITCH + half / 2:
                return 0.0
            return round(shift / half) * half
        if look + 1 < WALL_BAR_LOOKS:
            sleep(0.3)
    return 0.0


class Screen(Protocol):
    def grab(self) -> np.ndarray: ...
    def click(self, x: float, y: float) -> None: ...
    def has(self, template: str) -> bool: ...
    def find(self, template: str) -> tuple[float, float] | None: ...
    # optional: zoom_out() -> None (camera to the widest view) and wall_spot() -> (x, y) | None (where a wall is)


def free_slots(scr: Screen, cfg: Config) -> dict[str, int | None]:
    """Return the number of free builders and researchers (None = unreadable)."""
    return {
        "builders": _free(scr.grab(), cfg, "free_builders"),
        "researchers": _free(scr.grab(), cfg, "free_researchers"),
    }


# Counters drawn under the face of whoever is free. A goblin works for gems, so its slot is not a free one; the pets
# counter has a coin above it and no goblin.
GOBLIN_COUNTERS = {"free_builders", "free_researchers", "tab_count_builders", "tab_count_researchers"}


def _free(frame: np.ndarray, cfg: Config, name: str) -> int | None:
    count = vision.free_count(frame, cfg.regions[name])
    if count and name in GOBLIN_COUNTERS and vision.goblin_above(frame, cfg.regions[name]):
        return 0
    return count


def _close_menu(scr: Screen, cfg: Config, check, sleep) -> None:
    """Close the Construir menu, but only when it is really open: its X sits where the gold bar is in the
    village, and pressing the bar opens the gem shop."""
    for _ in range(3):
        if scr.has("menu_close_x"):
            check()
            scr.click(*cfg.buttons["build_close"])
            sleep(CLICK_DELAY)
            return
        sleep(0.4)


def _dismiss_no_builder(scr: Screen, cfg: Config, log, check, sleep) -> bool:
    """The game answers an upgrade with no free builder by offering to finish another task, or to hire the goblin
    builder, for gems. Close that notice with its X (never the green gem button) and report that it was there."""
    for notice, close in (("no_builder_dialog", "dialog_close"), ("goblin_dialog", "goblin_close")):
        if scr.has(notice):
            log("No hay constructores libres: cierro el aviso sin gastar gemas")
            check()
            scr.click(*cfg.buttons[close])
            sleep(CLICK_DELAY)
            return True
    return False


def _menu_opened(scr: Screen, sleep, tries: int = 6) -> bool:
    """The Construir menu can take a second or two to open (slower while another account's window is being
    switched to), so look for its X a few times before saying it did not open."""
    for i in range(tries):
        if scr.has("menu_close_x"):
            return True
        if i + 1 < tries:
            sleep(0.5)
    return False


def _reset_view(scr: Screen, cfg: Config, check, sleep) -> None:
    """Open and close the Construir menu: drops the wall selection and leaves the village as the bot expects."""
    check()
    scr.click(*cfg.buttons["build"])
    sleep(CLICK_DELAY + 0.4)
    _close_menu(scr, cfg, check, sleep)


def _select_wall_on_screen(scr: Screen, cfg: Config, log, check, sleep, view: dict) -> str:
    """The old selection, used when the Construir list cannot be used (template missing on an old config, filters
    that will not set): zoom out, find the wall block by its colour and click it. 'selected', 'none' (no wall
    panel: nothing to upgrade) or 'abort' (the block is not on screen, or another screen opened: touch nothing).
    `view` remembers that the camera was already zoomed out during this routine."""
    zoom_out = getattr(scr, "zoom_out", None)
    if zoom_out and not view.get("zoomed"):
        check()
        zoom_out()      # the camera is wherever the player left it; the wall block is only fixed when zoomed out
        sleep(0.6)
        view["zoomed"] = True
    # Select a wall; the block moves a few pixels with the zoom, so retry a little further inside it
    finder = getattr(scr, "wall_spot", None)
    found = finder() if finder else None      # located on screen: the camera is not always where we left it
    if finder and found is None:
        log("No veo el bloque de muros: no pulso nada")
        return "abort"
    for dx, dy in SPOT_OFFSETS:
        check()
        x, y = found or cfg.buttons["wall_spot"]
        scr.click(x + dx, y + dy)
        sleep(CLICK_DELAY)
        if scr.has("wall_panel"):
            return "selected"
        if not scr.has("battle"):             # some other screen opened (shop, window...): touch nothing more
            log("Se abrio una pantalla inesperada: paro las mejoras de muros")
            return "abort"
    log("Panel de muro no encontrado, no hay muros para mejorar")
    return "none"


def _bar_button(scr: Screen, names: tuple[str, ...], row: float, sleep) -> tuple[float, float] | None:
    """Where a mark of the multi-wall bar is drawn right now, looked for around height `row`. `names` are the ways
    the game draws that mark."""
    for look in range(WALL_BAR_LOOKS):
        for name in names:
            found = scr.find(name)
            if found is not None and abs(found[1] - row) <= WALL_BAR_Y_TOL:
                return found
        if look + 1 < WALL_BAR_LOOKS:
            sleep(0.3)
    return None


def _upgrade_selected_walls(scr: Screen, cfg: Config, resource: str, log, check, sleep) -> str:
    """With a wall selected: open the multi-wall panel, add walls while the price is payable and confirm the
    upgrade with `resource`. 'started' (a batch was confirmed), 'nothing' (could not start one; the view is
    reset) or 'abort' (no free builder: stop the whole routine)."""
    shift = _wall_bar_shift(scr, cfg, sleep)

    def at(name: str) -> tuple[float, float]:
        x, y = cfg.buttons[name]
        return x + shift, y

    # Open the multi-wall panel
    check()
    scr.click(*at("wall_more"))
    sleep(CLICK_DELAY)

    # The multi-wall bar changes shape: '+10' is only there with ten or more walls left to add, so its buttons are
    # not where the bar of a single wall said they would be (live 2026-11-27: with two walls of a level the clicks
    # fell between buttons and on the village for hours, selecting buildings that offer gems). Press only what is
    # seen. Both marks look the same at every wall level: the coin on the gold price ('+1' is the button left of the
    # gold one and elixir the one to its right) and the red 'Eliminar muro' label.
    # Adding walls can reshape it again ('+10' goes away), so it is measured anew after every change.
    price = cfg.regions["wall_cost_gold"]
    shift, take, cost_region = 0.0, (0.0, 0.0), price

    def measure() -> bool:
        nonlocal shift, take, cost_region
        coin = _bar_button(scr, ("wall_coin",), (price[1] + price[3]) / 2, sleep)
        found = _bar_button(scr, WALL_TAKE_ONE, cfg.buttons["wall_remove"][1], sleep)
        # walls below level 9 only take gold: the elixir price is pressed only with its drop seen beside the coin
        drop = coin and resource == "elixir" and _bar_button(scr, ("wall_drop",), coin[1], sleep)
        if resource == "elixir" and coin and not (drop and abs(drop[0] - coin[0] - WALL_BAR_PITCH) <= DROP_X_TOL):
            log("Este muro no se mejora con elixir: no pulso nada")
            _reset_view(scr, cfg, check, sleep)
            return False
        if coin is None or found is None:
            log("No reconozco los botones de la barra de muros: no pulso nada")
            _reset_view(scr, cfg, check, sleep)
            return False
        shift, take = coin[0] - COIN_DX - cfg.buttons["wall_up_gold"][0], found
        x0, y0, x1, y1 = cfg.regions[f"wall_cost_{resource}"]
        cost_region = (x0 + shift, y0, x1 + shift, y1)
        return True

    if not measure():
        return "nothing"
    add_clicks = 0

    # Phase 1: add one wall at a time until the cost turns red, or the game stops adding. Current versions
    # refuse to add more walls than you can pay: the counter stops, the price stays white and only the
    # 'Anadir' buttons turn red (live 2026-11-16: 250 useless clicks, nothing upgraded). A price that does
    # not change over CAP_UNCHANGED looks in a row is the cap, and then nothing has to be taken off. A price that
    # never moved and is not red is the one wall that can be added: it is upgraded too (a level with one wall left
    # would otherwise be picked from the list for ever).
    previous, unchanged, capped = vision.region_crop(scr.grab(), cost_region), 0, False
    while add_clicks < MAX_ADDS:
        check()
        scr.click(*at("wall_add1"))
        sleep(CLICK_DELAY)
        add_clicks += 1
        if not measure():
            return "nothing"
        frame = scr.grab()
        if vision.cost_is_red(frame, cost_region):
            break
        now = vision.region_crop(frame, cost_region)
        still = now is not None and previous is not None and not vision.region_changed(previous, now)
        unchanged = unchanged + 1 if still else 0
        previous = now
        if unchanged >= CAP_UNCHANGED:
            capped = True
            break
    else:
        # Exhausted MAX_ADDS without turning red — give up this resource
        if not vision.cost_is_red(scr.grab(), cost_region):
            log(f"Coste de {resource} nunca se puso rojo tras {MAX_ADDS} clics")
            _reset_view(scr, cfg, check, sleep)       # drop the open panel before the next resource
            return "nothing"

    if capped and vision.cost_is_red(scr.grab(), cost_region):
        log(f"No se pudo anadir ningun muro con {resource}")
        _reset_view(scr, cfg, check, sleep)
        return "nothing"

    # Phase 2: the last wall made it unaffordable: remove that one (nothing to remove at the cap)
    if not capped:
        check()
        scr.click(take[0], cfg.buttons["wall_remove"][1])
        sleep(CLICK_DELAY)
        if not measure():
            return "nothing"

    if not capped and vision.cost_is_red(scr.grab(), cost_region):
        # Still red after one remove — try one more
        check()
        scr.click(take[0], cfg.buttons["wall_remove"][1])
        sleep(CLICK_DELAY)
        if not measure():
            return "nothing"
        if vision.cost_is_red(scr.grab(), cost_region):
            # Still cannot afford — give up this resource
            log(f"Coste de {resource} sigue rojo tras dos eliminaciones")
            _reset_view(scr, cfg, check, sleep)
            return "nothing"

    # Gems are never spent: Mejorar is only pressed with a payable price (checked just above) and only
    # the exact "Mejorar muros" dialog is confirmed below
    target = at(f"wall_up_{resource}")
    item = vision.item_button_span(scr.grab())
    if item is not None and item[0] - ITEM_MARGIN <= target[0] <= item[1] + ITEM_MARGIN:
        # Whatever the layout measurement said, never press the item button: it spends a wall ring.
        log(f"El clic de {resource} caeria sobre el boton de mejorar con objeto: no pulso nada")
        _reset_view(scr, cfg, check, sleep)
        return "nothing"
    check()
    scr.click(*target)
    sleep(CLICK_DELAY)

    # Only the exact "Mejorar muros" dialog is confirmed (its title must be on screen)
    sleep(0.8)
    if _dismiss_no_builder(scr, cfg, log, check, sleep):
        return "abort"
    pos = scr.find("confirm_upgrade") if scr.has("walls_dialog") else None
    if pos is None:
        log(f"No aparece el dialogo de mejora de muros ({resource})")
        _reset_view(scr, cfg, check, sleep)
        return "nothing"
    check()
    scr.click(*pos)
    sleep(CLICK_DELAY + 0.6)
    if _dismiss_no_builder(scr, cfg, log, check, sleep):
        return "abort"
    # The game is still animating the batch that just started (live: the next pass found no wall panel at
    # the very spot that worked a minute later), and the next resource needs no selection left over.
    _reset_view(scr, cfg, check, sleep)
    return "started"


def upgrade_walls(scr: Screen, cfg: Config, log, check, sleep) -> bool:
    """Upgrade as many walls as affordable for each resource. Returns True if at least one upgrade started.

    The wall is chosen from the Construir list (cheapest level, wherever it is in the village); when the list
    cannot be used the colour-based selection of the wall block is the fallback. With the list, a resource
    selects again after each batch (the cheapest level may be used up), up to MAX_LEVEL_PASSES times."""
    started = False
    if scr.has("menu_close_x"):               # a menu left open would swallow the wheel and the clicks
        _close_menu(scr, cfg, check, sleep)
    view: dict = {}
    for resource in ("gold", "elixir"):
        no_panel = False
        for _pass in range(MAX_LEVEL_PASSES):
            chosen = _select_cheapest_wall(scr, cfg, log, check, sleep)
            if chosen == "none":
                return started                # no wall in the list at all: nothing to do for any resource
            if chosen == "lost":
                _reset_view(scr, cfg, check, sleep)
                break                         # the next resource selects again from a clean village
            from_list = chosen == "selected"
            if not from_list:
                chosen = _select_wall_on_screen(scr, cfg, log, check, sleep, view)
                if chosen == "abort":
                    return started
                if chosen == "none":
                    no_panel = True
                    break
            outcome = _upgrade_selected_walls(scr, cfg, resource, log, check, sleep)
            if outcome == "abort":
                return started
            if outcome != "started":
                break
            started = True
            if not from_list:
                break                         # the next pass would click the same block again
        if no_panel:
            break                             # no wall panel on the old path: the other resource finds none either
    _reset_view(scr, cfg, check, sleep)
    return started


def _select_filter(scr: Screen, off: str, on: str, check, sleep) -> bool:
    """Make one filter button selected. The game remembers the last filter, so it may already be on:
    pressing a selected button could switch it off again."""
    pos = None
    for _ in range(4):               # the popup takes a moment to draw
        check()
        if scr.has(on):
            return True
        pos = scr.find(off)
        if pos is not None:
            break
        sleep(0.5)
    if pos is None:
        return False
    check()
    scr.click(*pos)
    sleep(CLICK_DELAY)
    for _ in range(3):
        check()
        if scr.has(on):
            return True
        sleep(0.4)
    return False


# Construir menu tabs the bot may use: (slot, tab button, counter region, filter buttons to have selected). The forge / hero-equipment tab is deliberately absent: never upgraded.
BUSY_TABS = (
    ("builders", "tab_builders", "tab_count_builders",
     (("filter_permanent", "filter_permanent_on"), ("filter_cost_min", "filter_cost_min_on"))),
    ("researchers", "tab_researchers", "tab_count_researchers",
     (("filter_cost_min", "filter_cost_min_on"),)),
    ("pets", "tab_pets", "tab_count_pets", ()),
)
HERO_FILTER = (("filter_hero", "filter_hero_on"),)
PLAIN_FILTERS = (("filter_permanent", "filter_permanent_on"), ("filter_cost_min", "filter_cost_min_on"))
# The game remembers the resource filter between openings. The wall routine sets one, and a list still filtered by
# it would hide the cheapest upgrades of the busy / surplus modes, so those modes switch all of them off.
RESOURCE_FILTERS = (("filter_gold", "filter_gold_on"), ("filter_elixir", "filter_elixir_on"),
                    ("filter_dark", "filter_dark_on"))
# 'Muro' in the white font of a list row. Only wall rows select a wall when tapped instead of opening the
# 'Mejorar tu ...' window, and they are the wall routine's job.
WALL_ROW = "wall_row_name"
LIST_SCROLL = (0.87, 0.80, 0.87, 0.30)    # a drag inside the list from low to high: scrolls the list down
MAX_WALL_SCROLLS = 8      # drags to look for a wall row in one list (the walls sit near the top: a few are enough)
MAX_LEVEL_PASSES = 3      # batches of one resource in one call: a batch may use up the cheapest wall level
LIST_NAME_X_MIN = vision.LIST_X[0] - 0.08     # the name column starts at ~0.78, left of the list's price column
# Rows the user never wants upgraded (siege machines that the 'Heroe' filter also lists): matched by their name text.
NEVER_UPGRADE = ("skip_arrojatroncos", "skip_destructor", "skip_tiradora")
ROW_PITCH = 0.0796        # distance between two rows of the list (58 px at 729 high)
NAME_DY = -0.0137         # the name text sits this far above the row centre found by first_upgrade_row
MAX_ROWS_SKIPPED = 6
MAX_PER_TAB = 8      # upgrades pressed in one tab before looking again (a builder count is at most a few)


def _clear_filter(scr: Screen, off: str, on: str, check, sleep) -> str:
    """Make sure a filter button is NOT selected (the game remembers the last filters): press it only if it
    is seen selected. 'off' = it is off (or was switched off and seen off), 'stuck' = it was seen selected,
    was pressed and is still selected, 'unknown' = neither look was ever seen (popup not drawn, template
    missing)."""
    for _ in range(4):               # the popup takes a moment to draw
        check()
        if scr.has(off):
            return "off"
        pos = scr.find(on)
        if pos is not None:
            scr.click(*pos)
            sleep(CLICK_DELAY)
            for _ in range(3):
                check()
                if scr.has(off):
                    return "off"
                sleep(0.4)
            return "stuck"
        sleep(0.5)
    return "unknown"


def _rows_of(scr: Screen, template: str) -> list[tuple[float, float]]:
    """Every place of the list where `template` (a row's name) is seen, top to bottom. Screens that cannot give
    every hit (old ones, test doubles) give their best one."""
    finder = getattr(scr, "find_all", None)
    hits = finder(template) if finder else [h for h in [scr.find(template)] if h is not None]
    return [(x, y) for x, y in hits if vision.LIST_Y[0] <= y <= vision.ROW_Y_MAX and x >= LIST_NAME_X_MIN]


def _name_is_blocked(scr: Screen, name_y: float) -> bool:
    if any((pos := scr.find(n)) is not None and abs(pos[1] - name_y) < 0.03 for n in NEVER_UPGRADE):
        return True
    # Walls are instant and belong to the wall routine: tapping their row selects a wall and opens no window
    return any(abs(y - name_y) < 0.03 for _x, y in _rows_of(scr, WALL_ROW))


def _allowed_row(scr: Screen, first: tuple[float, float], sleep=lambda _s: None) -> tuple[float, float] | None:
    """The first row from `first` down whose name is not on the never-upgrade list. None if every visible row
    is one of them or the list ends. A row counts as allowed only if two looks, a moment apart, both fail to
    see a forbidden name: the guard is a template match, so a single miss while the list is still drawing
    must not let a forbidden row through."""
    for k in range(MAX_ROWS_SKIPPED):
        y = first[1] + k * ROW_PITCH
        if y > vision.ROW_Y_MAX:
            return None
        name_y = y + NAME_DY
        if _name_is_blocked(scr, name_y):
            continue
        sleep(0.3)
        if _name_is_blocked(scr, name_y):
            continue
        return (first[0], y)
    return None


def _find_wall_row(scr: Screen, check, sleep) -> tuple[float, float] | None:
    """The topmost wall row of the open list, scrolling down until one shows or the list stops moving."""
    scroll = getattr(scr, "drag", None)
    area = (vision.LIST_X[0], vision.LIST_Y[0], vision.LIST_X[1], vision.LIST_Y[1])
    for scrolls in range(MAX_WALL_SCROLLS + 1):
        check()
        rows = _rows_of(scr, WALL_ROW)
        if rows:
            return rows[0]
        if scroll is None or scrolls == MAX_WALL_SCROLLS:
            return None
        before = vision.region_crop(scr.grab(), area)
        scroll(*LIST_SCROLL)
        sleep(0.3)
        after = vision.region_crop(scr.grab(), area)
        if before is not None and after is not None and not vision.region_changed(before, after):
            return None                 # the list did not move: that was its end
    return None


def _set_list_filters(scr: Screen, cfg: Config, resource: tuple[str, str], log, check, sleep) -> bool:
    """On the open Construir menu, builders tab: show only what `resource` pays, cheapest first and with no type
    filter, which puts the wall levels near the top. False if a filter would not set. The popup is closed again."""
    others = tuple(f for f in RESOURCE_FILTERS if f != resource)
    clear = HERO_FILTER + PLAIN_FILTERS[:1] + others
    popup_open = False
    try:
        check()
        scr.click(*cfg.buttons["filter"])
        sleep(CLICK_DELAY)
        popup_open = True
        for off, on in clear:
            result = _clear_filter(scr, off, on, check, sleep)
            if result == "stuck":
                log(f"No pude apagar el filtro {off} (muros)")
                return False
            if result == "unknown":
                log(f"No pude comprobar el filtro {off} (muros)")
        if not all(_select_filter(scr, off, on, check, sleep) for off, on in (resource, PLAIN_FILTERS[1])):
            log("Filtros no activados (muros)")
            return False
        return True
    finally:
        if popup_open:
            check()
            scr.click(*cfg.buttons["filter"])
            sleep(CLICK_DELAY)


def _select_cheapest_wall(scr: Screen, cfg: Config, log, check, sleep) -> str:
    """Select one wall of the cheapest level from the Construir list, wherever it is in the village: tapping a
    'Muro x N' row selects a wall of that level and moves the camera to it. Walls below level 9 cannot be paid
    with elixir and are not in that list, so the gold list is the second look. 'selected' (the wall bar is on the
    screen, menu closed), 'none' (the menu opened and no list has a wall row) or 'failed' (the menu or the filters
    would not work, nothing tapped: the caller may fall back) or 'lost' (a row was tapped but no wall bar showed:
    no fallback). The menu is left closed."""
    check()
    scr.click(*cfg.buttons["build"])
    sleep(CLICK_DELAY + 0.6)
    opened = False
    try:
        if not _menu_opened(scr, sleep):
            log("El menu Construir no se abrio: no pulso nada")
            return "failed"
        opened = True
        check()
        scr.click(*cfg.buttons["tab_builders"])
        sleep(CLICK_DELAY + 0.4)
        for resource in (RESOURCE_FILTERS[1], RESOURCE_FILTERS[0]):          # elixir first, then gold
            if not _set_list_filters(scr, cfg, resource, log, check, sleep):
                return "failed"
            row = _find_wall_row(scr, check, sleep)
            if row is None:
                continue
            check()
            scr.click(*row)                                       # on the name: the price column is a button
            sleep(CLICK_DELAY + 0.4)
            _close_menu(scr, cfg, check, sleep)
            opened = False
            bar_row = cfg.buttons["wall_more"][1]
            for look in range(WALL_BAR_LOOKS):
                bar = scr.find("wall_panel")
                if bar is not None and abs(bar[1] - bar_row) <= WALL_BAR_Y_TOL:
                    return "selected"
                if look + 1 < WALL_BAR_LOOKS:
                    sleep(0.3)
            log("No aparece la barra del muro tras elegirlo en la lista")
            return "lost"           # a row was tapped: the colour search would click blind over whatever it opened
        log("No hay muros en la lista de Construir")
        return "none"
    finally:
        if opened:
            _close_menu(scr, cfg, check, sleep)


def _first_row_upgrade(scr: Screen, cfg: Config, tab, log, check, sleep, filters=None, clear=None,
                       state=None) -> bool:
    """On the open Construir menu: open the tab, apply its filters, press the first row and confirm the
    green button of the 'Mejorar tu ...' window. Never presses the grey hammer button, never a red price.

    `filters` / `clear` override the tab's filters to select and name filters that must be OFF. On the
    builders tab the hero and resource filters are cleared by default (the game remembers them). `state`, if given, gets
    `no_builder=True` when the game said there is no free builder (trying again is pointless)."""
    slot, tab_button, _count, tab_filters = tab
    filters = tab_filters if filters is None else filters
    if clear is None:
        clear = HERO_FILTER + RESOURCE_FILTERS if slot == "builders" else ()
    check()
    scr.click(*cfg.buttons[tab_button])
    sleep(CLICK_DELAY + 0.4)
    if filters or clear:
        popup_open = False
        try:
            check()
            scr.click(*cfg.buttons["filter"])
            sleep(CLICK_DELAY)
            popup_open = True
            for off, on in clear:
                result = _clear_filter(scr, off, on, check, sleep)
                if result == "stuck":
                    log(f"No pude apagar el filtro {off} ({slot})")
                    return False
                if result == "unknown":
                    log(f"No pude comprobar el filtro {off} ({slot})")
            if not all(_select_filter(scr, off, on, check, sleep) for off, on in filters):
                log(f"Filtros no activados ({slot})")
                return False
        finally:
            if popup_open:
                check()
                scr.click(*cfg.buttons["filter"])
                sleep(CLICK_DELAY)
    row = vision.first_upgrade_row(scr.grab())
    if row is None:
        sleep(0.8)
        row = vision.first_upgrade_row(scr.grab())
    if row is None:
        log(f"No encuentro la lista de mejoras ({slot})")
        return False
    if slot == "builders":
        row = _allowed_row(scr, row, sleep)
        if row is None:
            log(f"Solo hay mejoras que no quiero hacer ({slot})")
            return False
    # Price of the first row, read BEFORE clicking: the click changes the screen
    if vision.cost_is_red(scr.grab(), (0.86, row[1] + 0.005, 0.995, row[1] + 0.055)):
        log(f"Primera mejora demasiado cara ({slot})")
        return False
    check()
    scr.click(*row)
    sleep(CLICK_DELAY + 0.4)
    if not scr.has("upgrade_window"):
        log(f"No aparece la ventana de mejora ({slot})")
        return False
    try:
        if vision.cost_is_red(scr.grab(), _price_region(cfg)):
            log(f"No hay recursos para la primera mejora ({slot})")
            return False
        check()
        scr.click(*cfg.buttons["upgrade_confirm"])      # the green button; the grey one is the hammer item
        sleep(CLICK_DELAY + 0.6)
        if _dismiss_no_builder(scr, cfg, log, check, sleep):
            if state is not None:
                state["no_builder"] = True
            return False
        return True
    finally:
        if scr.has("upgrade_window"):                   # still open: refused or not confirmed
            check()
            scr.click(*cfg.buttons["upgrade_window_close"])
            sleep(CLICK_DELAY)


def upgrade_busy(scr: Screen, cfg: Config, log, check, sleep, only=None, keep=None, heroes=False) -> bool:
    """Open Construir, and for every tab (builders, researchers, pets) with a free slot keep upgrading its
    cheapest filtered row until the tab's counter reaches 0 or the price cannot be paid. True if at least one
    upgrade was confirmed. Always leaves the menu closed.

    `only` restricts it to some tabs (slot names) and `keep` maps a slot to how many free slots to LEAVE: the
    walls mode keeps exactly one builder free for the walls, so it asks for only=("builders",), keep={"builders": 1}.

    `heroes`: on the builders tab try the Heroe filter first (its first allowed row); when there is none or it
    cannot be paid, fall back to the cheapest permanent upgrade as usual."""
    keep = keep or {}
    check()
    scr.click(*cfg.buttons["build"])
    sleep(CLICK_DELAY + 0.6)
    started = False
    try:
        if not _menu_opened(scr, sleep):
            log("El menu Construir no se abrio: no pulso nada")
            return False
        frame = scr.grab()
        free = {t[0]: _free(frame, cfg, t[2]) for t in BUSY_TABS}
        todo = [t for t in BUSY_TABS if (only is None or t[0] in only) and (free[t[0]] or 0) > keep.get(t[0], 0)]
        if not todo:
            log("Nada libre en el menu Construir")
        hero_try = heroes            # one failed hero attempt (none to upgrade, too dear) ends the tries
        for tab in todo:
            slot, _btn, count_region = tab[0], tab[1], tab[2]
            left, reserve = free[slot] or 0, keep.get(slot, 0)
            for _ in range(MAX_PER_TAB):
                # drain the tab: the cheapest item again and again until its counter is 0 or it cannot be paid
                hero_done, state = False, {}
                if hero_try and slot == "builders":
                    hero_done = _first_row_upgrade(scr, cfg, tab, log, check, sleep, filters=HERO_FILTER,
                                                   clear=PLAIN_FILTERS + RESOURCE_FILTERS, state=state)
                    if not hero_done:
                        hero_try = False
                        if state.get("no_builder"):
                            break                   # no free builder: the plain attempt would meet the same notice
                if not hero_done and not _first_row_upgrade(scr, cfg, tab, log, check, sleep):
                    break
                started = True
                log(f"Mejora lanzada ({slot}{', heroe' if hero_done else ''})")
                now = _free(scr.grab(), cfg, count_region)
                if now is None:                       # blurry for a moment right after the confirm: look again
                    sleep(0.6)
                    now = _free(scr.grab(), cfg, count_region)
                stuck = bool(now) and (now > left or now == left < vision.MANY_FREE)     # at 'two or more' it need not drop
                if not now or stuck or now <= reserve:   # done / unreadable / did not start / reserve reached
                    break
                left = now
            if not scr.has("menu_close_x"):             # the game closed the menu: nothing more to do
                break
        return started
    finally:
        _close_menu(scr, cfg, check, sleep)
