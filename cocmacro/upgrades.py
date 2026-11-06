"""Wall and building upgrades driven by vision helpers and a Screen protocol."""
from __future__ import annotations

from typing import Protocol

import numpy as np

from cocmacro import vision
from cocmacro.config import Config

CLICK_DELAY = 0.4
MAX_ADDS = 250            # walls added one by one: the price turns red long before this
SPOT_OFFSETS = ((0.0, 0.0), (-0.015, -0.03), (-0.03, -0.06))   # retries inside the wall block


class Screen(Protocol):
    def grab(self) -> np.ndarray: ...
    def click(self, x: float, y: float) -> None: ...
    def has(self, template: str) -> bool: ...
    def find(self, template: str) -> tuple[float, float] | None: ...
    # optional: zoom_out() -> None (camera to the widest view) and wall_spot() -> (x, y) | None (where a wall is)


def free_slots(scr: Screen, cfg: Config) -> dict[str, int | None]:
    """Return the number of free builders and researchers (None = unreadable)."""
    return {
        "builders": vision.free_count(scr.grab(), cfg.regions["free_builders"]),
        "researchers": vision.free_count(scr.grab(), cfg.regions["free_researchers"]),
    }


def _reset_view(scr: Screen, cfg: Config, check, sleep) -> None:
    """Open and close the Construir menu: drops the wall selection and leaves the village as the bot expects."""
    for name in ("build", "build_close"):
        check()
        scr.click(*cfg.buttons[name])
        sleep(CLICK_DELAY)


def upgrade_walls(scr: Screen, cfg: Config, log, check, sleep) -> bool:
    """Upgrade as many walls as affordable for each resource. Returns True if at least one upgrade started."""
    started = False
    zoom_out = getattr(scr, "zoom_out", None)
    if zoom_out:
        check()
        zoom_out()      # the camera is wherever the player left it; the wall block is only fixed when zoomed out
        sleep(0.6)
    for resource in ("gold", "elixir"):
        # Select a wall; the block moves a few pixels with the zoom, so retry a little further inside it
        selected = False
        finder = getattr(scr, "wall_spot", None)
        found = finder() if finder else None      # located on screen: the camera is not always where we left it
        for dx, dy in SPOT_OFFSETS:
            check()
            x, y = found or cfg.buttons["wall_spot"]
            scr.click(x + dx, y + dy)
            sleep(CLICK_DELAY)
            if scr.has("wall_panel"):
                selected = True
                break
        if not selected:
            log("Panel de muro no encontrado, no hay muros para mejorar")
            break

        # Open the multi-wall panel
        check()
        scr.click(*cfg.buttons["wall_more"])
        sleep(CLICK_DELAY)

        cost_region = cfg.regions[f"wall_cost_{resource}"]
        add_clicks = 0

        # Phase 1: add one wall at a time until the cost turns red
        while add_clicks < MAX_ADDS:
            check()
            scr.click(*cfg.buttons["wall_add1"])
            sleep(CLICK_DELAY)
            add_clicks += 1
            if vision.cost_is_red(scr.grab(), cost_region):
                break
        else:
            # Exhausted MAX_ADDS without turning red — give up this resource
            if not vision.cost_is_red(scr.grab(), cost_region):
                log(f"Coste de {resource} nunca se puso rojo tras {MAX_ADDS} clics")
                _reset_view(scr, cfg, check, sleep)       # drop the open panel before the next resource
                continue

        # Phase 2: the last wall made it unaffordable: remove that one
        check()
        scr.click(*cfg.buttons["wall_remove"])
        sleep(CLICK_DELAY)

        if vision.cost_is_red(scr.grab(), cost_region):
            # Still red after one remove — try one more
            check()
            scr.click(*cfg.buttons["wall_remove"])
            sleep(CLICK_DELAY)
            if vision.cost_is_red(scr.grab(), cost_region):
                # Still cannot afford — give up this resource
                log(f"Coste de {resource} sigue rojo tras dos eliminaciones")
                _reset_view(scr, cfg, check, sleep)
                continue

        # Gems are never spent: Mejorar is only pressed with a payable price (checked just above) and only
        # the exact "Mejorar muros" dialog is confirmed below
        check()
        scr.click(*cfg.buttons[f"wall_up_{resource}"])
        sleep(CLICK_DELAY)

        # Confirm the 'Mejorar muros' dialog (only that exact dialog has this Vale)
        sleep(0.8)
        pos = scr.find("confirm_upgrade") if scr.has("confirm_upgrade") else None
        if pos is None:
            log(f"No aparece el dialogo de mejora de muros ({resource})")
            _reset_view(scr, cfg, check, sleep)
            continue
        check()
        scr.click(*pos)
        sleep(CLICK_DELAY)
        started = True

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


# Construir menu tabs the bot may use: (slot, tab button, counter region, filter buttons to have selected,
# header above the first row). The forge / hero-equipment tab is deliberately absent: never upgraded.
BUSY_TABS = (
    ("builders", "tab_builders", "tab_count_builders",
     (("filter_permanent", "filter_permanent_on"), ("filter_cost_min", "filter_cost_min_on")), "filtered_header"),
    ("researchers", "tab_researchers", "tab_count_researchers",
     (("filter_cost_min", "filter_cost_min_on"),), "filtered_header"),
    ("pets", "tab_pets", "tab_count_pets", (), "assigned_header"),
)
FIRST_ROW_DY = 0.075


def _first_row_upgrade(scr: Screen, cfg: Config, tab, log, check, sleep) -> bool:
    """On the open Construir menu: open the tab, apply its filters, press the first row and confirm the
    green button of the 'Mejorar tu ...' window. Never presses the grey hammer button, never a red price."""
    slot, tab_button, _count, filters, header = tab
    check()
    scr.click(*cfg.buttons[tab_button])
    sleep(CLICK_DELAY + 0.4)
    if filters:
        popup_open = False
        try:
            check()
            scr.click(*cfg.buttons["filter"])
            sleep(CLICK_DELAY)
            popup_open = True
            if not all(_select_filter(scr, off, on, check, sleep) for off, on in filters):
                log(f"Filtros no activados ({slot})")
                return False
        finally:
            if popup_open:
                check()
                scr.click(*cfg.buttons["filter"])
                sleep(CLICK_DELAY)
    h = scr.find(header)
    if h is None:
        sleep(0.8)
        h = scr.find(header)
    if h is None:
        log(f"No encuentro la lista de mejoras ({slot})")
        return False
    # Cost of the first row, read BEFORE clicking: the click changes the screen
    if vision.cost_is_red(scr.grab(), (h[0] - 0.10, h[1] + 0.04, h[0] + 0.14, h[1] + 0.11)):
        log(f"Primera mejora demasiado cara ({slot})")
        return False
    check()
    scr.click(h[0], h[1] + FIRST_ROW_DY)
    sleep(CLICK_DELAY + 0.4)
    if not scr.has("upgrade_window"):
        log(f"No aparece la ventana de mejora ({slot})")
        return False
    try:
        if vision.cost_is_red(scr.grab(), cfg.regions["upgrade_cost"]):
            log(f"No hay recursos para la primera mejora ({slot})")
            return False
        check()
        scr.click(*cfg.buttons["upgrade_confirm"])      # the green button; the grey one is the hammer item
        sleep(CLICK_DELAY + 0.4)
        return True
    finally:
        if scr.has("upgrade_window"):                   # still open: refused or not confirmed
            check()
            scr.click(*cfg.buttons["upgrade_window_close"])
            sleep(CLICK_DELAY)


def upgrade_busy(scr: Screen, cfg: Config, log, check, sleep) -> bool:
    """Open Construir, and for every tab (builders, researchers, pets) with a free slot upgrade its first
    filtered row. True if at least one upgrade was confirmed. Always leaves the menu closed."""
    check()
    scr.click(*cfg.buttons["build"])
    sleep(CLICK_DELAY + 0.6)
    started = False
    try:
        frame = scr.grab()
        free = {t[0]: vision.free_count(frame, cfg.regions[t[2]]) for t in BUSY_TABS}
        todo = [t for t in BUSY_TABS if (free[t[0]] or 0) >= 1]
        if not todo:
            log("Nada libre en el menu Construir")
        for tab in todo:
            if _first_row_upgrade(scr, cfg, tab, log, check, sleep):
                started = True
                log(f"Mejora lanzada ({tab[0]})")
            if not scr.has("menu_close_x"):             # the game closed the menu: nothing more to do
                break
        return started
    finally:
        if scr.has("menu_close_x"):
            check()
            scr.click(*cfg.buttons["build_close"])
            sleep(CLICK_DELAY)
