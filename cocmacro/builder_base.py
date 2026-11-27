"""Builder Base farming: sail there by boat, attack in a loop, collect the elixir cart and sail back.

Everything is recognised by its image before anything is pressed (live 2026-11-27, frames 1296x729). Nothing here
presses a gem or item button: 'Potenciar ejercito' / 'Potenciar heroes' (bottom left during the countdown) and 'Usar'
(next to 'Editar ejercito') are never aimed at, and no drop point lies on them."""
import cv2
import numpy as np

from cocmacro.config import Config

VISIT_ATTACKS = 5        # attacks before sailing back to look at the main village builders
POLL_S = 1.0
SAIL_WAIT_S = 20         # the trip takes 5-8 s
PANEL_WAIT_S = 8         # 'Empezar ataque' after Batalla
SEARCH_WAIT_S = 40       # an opponent after Buscar
BATTLE_WAIT_S = 480      # two stages, each with a 60 s countdown and 3 min of fight
ABILITY_S = 20           # how often the hero card is pressed again (its ability)
DROP_TRIES = 4           # drop points tried for one card before moving on to the next
SAIL_TRIES = 4

SEARCH_X = (0.850, 0.182)      # X of 'Empezar ataque'
STAR_OK = (0.500, 0.763)       # 'Vale' of 'Bonus estelar'
CART_COLLECT = (0.735, 0.844)  # 'Recoger'
CART_X = (0.838, 0.100)
CARD_Y = 0.898
# hero first, then troop slots 1-8 (stage 2 adds 7 and 8)
CARD_X = (0.167, 0.241, 0.308, 0.374, 0.440, 0.506, 0.572, 0.638, 0.704)
# Drop points around the village, out by the edge of the field: a drop inside the red zone around the buildings is
# ignored, and the card is then tried on the next point.
DROPS = ((0.154, 0.549), (0.139, 0.453), (0.208, 0.370), (0.231, 0.288), (0.324, 0.219), (0.679, 0.206),
         (0.772, 0.274), (0.810, 0.357), (0.887, 0.453), (0.864, 0.521), (0.810, 0.631), (0.733, 0.670),
         (0.255, 0.658))
# A troop card still to be dropped has a blue body; dropped ones turn green and dead ones grey (shares of blue measured
# on live frames: waiting >= 0.66, anything else 0.00). The strip is left of the face, above the level badge.
WAITING_HSV_LOW, WAITING_HSV_HIGH = (95, 120, 120), (125, 255, 255)
WAITING_MIN_SHARE = 0.4
CARD_STRIP = (-0.024, -0.018, 0.889, 0.916)    # x offsets from the card centre, y from / to
# The boat is only tapped here: above it lie the resource bars and the gem '+', around it the game's own buttons.
BOAT_AREA = (0.13, 0.28, 0.90, 0.80)
BOATS = ("boat", "boat_far")
# Where a pan starts (scenery: a drag that starts on a building can open it) and ends, to uncover the boat / the cart.
PAN_MAIN = ((0.88, 0.68), (0.95, 0.35))
PAN_BB = ((0.15, 0.35), (0.15, 0.55))


def in_builder_base(scr) -> bool:
    """Any screen of the Builder Base the bot knows."""
    return any(scr.has(n) for n in ("bb_home", "bb_search", "bb_attacker", "bb_cart_window"))


def _result_button(scr):
    """'Volver' of a Builder Base result. The main village's looks the same, so the 'Atacante' banner, which only
    the Builder Base draws, must be there too."""
    return scr.find("bb_back") if scr.has("bb_attacker") else None


def _wait(scr, names, seconds: float, check, sleep) -> bool:
    """True once any of `names` (one template or several) is on screen."""
    names = (names,) if isinstance(names, str) else names
    for _ in range(max(1, int(seconds / POLL_S))):
        check()
        if any(scr.has(n) for n in names):
            return True
        sleep(POLL_S)
    return False


def _boat(scr):
    """Where the boat can be tapped, if it can. It is drawn smaller in the main village (the camera goes farther out)."""
    for name in BOATS:
        at = scr.find(name)
        if at is not None and BOAT_AREA[0] <= at[0] <= BOAT_AREA[2] and BOAT_AREA[1] <= at[1] <= BOAT_AREA[3]:
            return at
    return None


def _sail(scr, arrive: str, pan, log, check, sleep) -> bool:
    """Tap the boat and wait for the other village (`arrive` is the template that proves it)."""
    for _ in range(SAIL_TRIES):
        check()
        if scr.has(arrive):
            return True
        scr.zoom_out()
        boat = _boat(scr)
        if boat is None:
            check()
            scr.drag(*pan[0], *pan[1])
            sleep(POLL_S)
            boat = _boat(scr)
        if boat is not None:
            check()
            scr.click(*boat)
            if _wait(scr, arrive, SAIL_WAIT_S, check, sleep):
                return True
    log("No consigo usar el barco")
    return False


def _close_popups(scr, check, sleep) -> None:
    for name, at in (("bb_star_ok", STAR_OK), ("bb_cart_window", CART_X), ("bb_search", SEARCH_X)):
        if scr.has(name):
            check()
            scr.click(*at)
            sleep(2 * POLL_S)


def leave(scr, log, check, sleep) -> bool | None:
    """If the game is in the Builder Base (the main village routines must never run there), get out of whatever
    screen it is on and sail home. None if it was not there, True once home, False if it is still there."""
    if not in_builder_base(scr):
        return None
    log("Estoy en la aldea pequena: vuelvo a la principal")
    if scr.has("bb_attacker") and not scr.has("bb_back"):
        _wait(scr, "bb_back", BATTLE_WAIT_S, check, sleep)       # let the battle end by itself
    back = _result_button(scr)
    if back is not None:
        check()
        scr.click(*back)
        sleep(5 * POLL_S)
    _close_popups(scr, check, sleep)
    return _sail(scr, "battle", PAN_BB, log, check, sleep)


def waiting_cards(frame: np.ndarray) -> list[int]:
    """Troop slots (1-8) whose card says its troop has not been dropped yet."""
    h, w = frame.shape[:2]
    x0, x1, y0, y1 = CARD_STRIP
    waiting = []
    for slot, x in enumerate(CARD_X[1:], start=1):
        strip = frame[int(y0 * h):int(y1 * h), int((x + x0) * w):int((x + x1) * w)]
        blue = cv2.inRange(cv2.cvtColor(strip, cv2.COLOR_BGR2HSV), WAITING_HSV_LOW, WAITING_HSV_HIGH)
        if blue.mean() / 255 >= WAITING_MIN_SHARE:
            waiting.append(slot)
    return waiting


def _fighting(scr) -> bool:
    return scr.has("bb_attacker") and not scr.has("bb_back")


def _deploy(scr, slots: list[int], turn: int, check, sleep) -> int:
    """Drop the hero and every waiting troop, spread around the village, each one tried on further points until its
    card stops waiting. `turn` is where the ring of points goes on from; returns the new one."""
    if not _fighting(scr):
        return turn
    check()
    scr.click(CARD_X[0], CARD_Y)                 # the hero: dropped, or its ability if it is already out
    sleep(0.2)
    check()
    scr.click(*DROPS[turn % len(DROPS)])
    sleep(0.2)
    for slot in slots:
        for _ in range(DROP_TRIES):
            check()
            if not _fighting(scr):
                return turn
            scr.click(CARD_X[slot], CARD_Y)
            sleep(0.2)
            turn += 5                            # five points on: neighbours in the list are neighbours on the field
            check()
            scr.click(*DROPS[turn % len(DROPS)])
            sleep(0.4)
            if slot not in waiting_cards(scr.grab()):
                break
    return turn


def attack(scr, cfg: Config, log, check, sleep) -> bool:
    """One attack from the Builder Base village and back to it."""
    check()
    scr.click(*cfg.buttons["battle"])
    if not _wait(scr, "bb_search", PANEL_WAIT_S, check, sleep):
        log("No se abre el menu de ataque de la aldea pequena")
        return False
    search = scr.find("bb_search")
    if search is None:
        return False
    check()
    scr.click(*search)
    if not _wait(scr, "bb_attacker", SEARCH_WAIT_S, check, sleep):
        log("No aparece rival en la aldea pequena")
        return False
    sleep(2 * POLL_S)
    turn, since_ability = 0, 0.0
    for _ in range(int(BATTLE_WAIT_S / POLL_S)):
        check()
        back = _result_button(scr)
        if back is not None:
            check()
            scr.click(*back)
            if not _wait(scr, ("bb_home", "bb_star_ok"), SAIL_WAIT_S, check, sleep):
                return False
            sleep(3 * POLL_S)            # the star bonus window comes up a moment after the village
            _close_popups(scr, check, sleep)
            return True
        slots = waiting_cards(scr.grab()) if _fighting(scr) else []
        if slots:                        # at the start, in stage 2, and for drops that did not take
            turn = _deploy(scr, slots, turn, check, sleep)
            since_ability = 0.0
        elif since_ability >= ABILITY_S and _fighting(scr):
            check()
            scr.click(CARD_X[0], CARD_Y)
            since_ability = 0.0
        sleep(POLL_S)
        since_ability += POLL_S
    log("La batalla de la aldea pequena no termina")
    return False


def _collect_cart(scr, log, check, sleep) -> None:
    cart = scr.find("bb_cart")
    if cart is None:
        check()
        scr.drag(*PAN_BB[0], *PAN_BB[1])
        sleep(POLL_S)
        cart = scr.find("bb_cart")
    if cart is None or cart[0] > 0.80:              # not seen, or under the resource bars
        return
    check()
    scr.click(*cart)
    if not _wait(scr, "bb_cart_window", PANEL_WAIT_S, check, sleep):
        return
    check()
    scr.click(*CART_COLLECT)
    sleep(2 * POLL_S)
    _close_popups(scr, check, sleep)     # only a window still there: its X sits by the elixir bar and the gem '+'
    log("Carro de elixir revisado")


def farm(scr, cfg: Config, gold_full, log, check, sleep) -> str:
    """One visit: from the main village to the Builder Base, up to VISIT_ATTACKS attacks, the cart, and back.
    'full' (the Builder Base gold storage is full: no reason to come again), 'ok' (more to farm later) or 'failed'.
    `gold_full()` reads the storage bar of whatever village is on screen."""
    if not _sail(scr, "bb_home", PAN_MAIN, log, check, sleep):
        return "failed"
    log("En la aldea pequena")
    result = "ok"
    _close_popups(scr, check, sleep)
    for done in range(VISIT_ATTACKS):
        if sum(gold_full() is True for _ in range(3)) >= 2:
            log("Oro de la aldea pequena lleno")
            result = "full"
            break
        if not attack(scr, cfg, log, check, sleep):
            result = "failed"
            break
        log(f"Ataque {done + 1} en la aldea pequena completado")
    if scr.has("bb_home"):
        _collect_cart(scr, log, check, sleep)
        if not _sail(scr, "battle", PAN_BB, log, check, sleep):
            return "failed"
    else:
        leave(scr, log, check, sleep)
    return result
