"""Builder Base farming: recognition on real captures and the visit's flow on a fake screen."""
from pathlib import Path

import cv2
import numpy as np
import pytest

from cocmacro import builder_base as bb, defaults, templates
from cocmacro.config import Config

FIX = Path(__file__).parent / "fixtures" / "ui"


@pytest.mark.parametrize("fixture, name", [("bb_village", "bb_home"), ("bb_battle", "bb_attacker"),
                                           ("bb_result", "bb_back"), ("bb_boat_home", "boat"),
                                           ("bb_boat_main", "boat"), ("bb_boat_far", "boat_far")])
def test_builder_base_screens_are_recognised(fixture, name):
    """Real captures (2026-11-27), other than the ones the templates were cut from."""
    assert templates.match(cv2.imread(str(FIX / f"{fixture}.png")), name, defaults.DIR)


def test_the_main_village_is_not_taken_for_the_builder_base():
    frame = cv2.imread(str(FIX / "village_no_menu.png"))
    assert not any(templates.match(frame, n, defaults.DIR)
                   for n in ("bb_home", "bb_search", "bb_attacker", "bb_back", "bb_cart_window", "boat"))


class World:
    """The two villages and the screens of an attack, as the bot sees and presses them."""

    def __init__(self, boat=(0.32, 0.63), star=False, battle_polls=3):
        self.at, self.clicks, self.drags, self.boat = "main", [], 0, boat
        self.star, self.battle_polls, self.left, self.attacks = star, battle_polls, 0, 0
        self.pending, self.card, self.red = set(), None, set()
        self.collect_closes, self.stuck_boat = False, False

    def grab(self):
        frame = np.zeros((729, 1296, 3), dtype=np.uint8)
        if self.at == "battle":
            for slot in self.pending:                      # a waiting card has a blue body
                cx = int(bb.CARD_X[slot] * 1296)
                frame[640:680, cx - 37:cx + 37] = (230, 140, 50)
        return frame

    def zoom_out(self):
        pass

    def drag(self, *_):
        self.drags += 1
        self.boat = (0.5, 0.5)

    def has(self, name):
        if name == "bb_attacker":
            if self.at == "battle":
                self.left -= 1
                if self.left <= 0:
                    self.at = "result"
            return self.at in ("battle", "result")
        return name == {"main": "battle", "bb": "bb_home", "panel": "bb_search", "result": "bb_back",
                        "star": "bb_star_ok", "cart": "bb_cart_window"}.get(self.at)

    def find(self, name):
        if name == "boat":
            return self.boat if self.at in ("main", "bb") and name == "boat" else None
        if name == "bb_cart":
            return (0.67, 0.13) if self.at == "bb" else None
        if not self.has(name):
            return None
        return {"bb_search": (0.744, 0.654), "bb_back": (0.5, 0.84)}[name]

    def click(self, x, y):
        self.clicks.append((x, y))
        here = self.at
        if here in ("main", "bb") and (x, y) == self.boat and not self.stuck_boat:
            self.at = "bb" if here == "main" else "main"
        elif here == "bb" and x < 0.12:
            self.at = "panel"
        elif here == "bb" and (x, y) == (0.67, 0.13):
            self.at = "cart"
        elif here == "panel" and (x, y) == (0.744, 0.654):
            self.at, self.left, self.pending, self.card = "battle", self.battle_polls, set(range(1, 7)), None
        elif here == "battle" and y == bb.CARD_Y:
            self.card = bb.CARD_X.index(x)
        elif here == "battle" and (x, y) not in self.red:
            self.pending.discard(self.card)
        elif here == "result" and (x, y) == (0.5, 0.84):
            self.attacks += 1
            self.at = "star" if self.star else "bb"
        elif here == "star" and (x, y) == bb.STAR_OK:
            self.star, self.at = False, "bb"
        elif here == "cart" and (x, y) == bb.CART_X:
            self.at = "bb"
        elif here == "cart" and (x, y) == bb.CART_COLLECT and self.collect_closes:
            self.at = "bb"


def _farm(world, full=lambda: False):
    cfg = Config()
    cfg.buttons.update(defaults.BUTTONS)
    return bb.farm(world, cfg, full, lambda m: None, lambda: None, lambda s: None)


def test_a_visit_attacks_collects_and_sails_back():
    world = World(star=True)
    assert _farm(world) == "ok"
    assert world.attacks == bb.VISIT_ATTACKS and world.at == "main"
    assert bb.CART_COLLECT in world.clicks and bb.STAR_OK in world.clicks


def test_a_visit_ends_without_attacking_when_the_gold_is_full():
    world = World()
    assert _farm(world, full=lambda: True) == "full" and world.attacks == 0 and world.at == "main"


def test_a_boat_under_the_resource_bars_is_not_pressed():
    """Live: in the Builder Base the boat can sit under the gem '+'; the camera is moved first."""
    world = World(boat=(0.86, 0.18))
    assert _farm(world, full=lambda: True) == "full" and (0.86, 0.18) not in world.clicks and world.drags >= 1


def test_drop_points_never_reach_the_potion_buttons_or_the_battle_hud():
    for x, y in bb.DROPS:
        assert y <= 0.69 and not (x < 0.12 and y > 0.70) and not (x > 0.85 and 0.58 < y < 0.69)


def test_waiting_cards_are_read_from_a_real_troop_bar():
    """Stage 2 (2026-11-27): cards 4 and 5 (survivors) and 8 (new) wait; the others are out or dead."""
    assert bb.waiting_cards(cv2.imread(str(FIX / "bb_cards.png"))) == [4, 5, 8]


def test_every_troop_is_dropped_even_when_points_fall_in_the_red_zone():
    world = World(battle_polls=60)
    world.red = set(bb.DROPS[::2])                       # half of the points refuse the troop
    cfg = Config()
    cfg.buttons.update(defaults.BUTTONS)
    world.at = "bb"
    assert bb.attack(world, cfg, lambda m: None, lambda: None, lambda s: None) is True and not world.pending


def test_leave_only_acts_in_the_builder_base():
    world = World()
    assert bb.leave(world, lambda m: None, lambda: None, lambda s: None) is None and world.clicks == []
    world.at = "bb"
    assert bb.leave(world, lambda m: None, lambda: None, lambda s: None) is True and world.at == "main"
    world.at, world.stuck_boat = "bb", True
    assert bb.leave(world, lambda m: None, lambda: None, lambda s: None) is False


def test_the_cart_x_is_not_pressed_once_collecting_closed_the_window():
    """Where the X was, the village shows the elixir bar beside the gem '+'."""
    world = World()
    world.collect_closes = True
    assert _farm(world) == "ok" and bb.CART_COLLECT in world.clicks and bb.CART_X not in world.clicks
