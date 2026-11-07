# Test Fixtures

This directory contains test fixture images used mainly by `tests/test_ocr.py`, `tests/test_templates.py`, `tests/test_vision.py` and `tests/test_game.py`.

## Fixture Overview

- **Full-Frame Captures (`f*.png`)**:
  About 1297x729 game screen captures where **everything is completely blacked out except** the precise bounding boxes read by the tests:
  - **Gold Loot**: Digit region `(0.040, 0.106, 0.135, 0.133)` in the scout screen HUD.
  - **Elixir Loot**: Digit region `(0.040, 0.145, 0.135, 0.178)` in the scout screen HUD.
  - **Damage Percentage**: Digit region `(0.922, 0.774, 0.971, 0.809)` showing attack destruction.
  - **Battle Clock**: Timer region `(0.451, 0.045, 0.552, 0.082)` showing remaining match time.
  Expected values and coordinate mappings are defined in [labels.json](labels.json).

- **UI State Captures (`ui/*.png`)**:
  Captures of game user interface components (full frames or crops). The profile box (player name, clan, level) is blacked out; the rest of the village UI is visible:
  - **Storage Bars** (`storage_bars_full.png`, `storage_bars_half_full.png`, `storage_bars_not_full.png`): Top-right village resource bars for detecting full storage capacity.
  - **Builder and Researcher Counters** (`counters_0_of_7_and_0_of_2.png`, `counters_1_of_7_and_0_of_2.png`, `menu_text_over_counters.png`): Hud indicators for available builders and laboratory researchers.
  - **Wall Panels** (`wall_block_centered_top.png`, `wall_block_panned_top.png`, `wall_panel_cost_red.png`): Wall cluster positions and multi-wall upgrade dialog with red unaffordable cost detection.
  - **Upgrade Menu Tabs** (`menu_builders_tab_filtered.png`, `menu_pets_tab.png`, `menu_researchers_tab.png`, `village_no_menu.png`): Construir menu navigation tabs and filter buttons.

- **Isolated Number Crops (`crops/*.png`)**:
  Cropped digit patches from real villages with diverse scenery themes used to verify glyph segmentation edge cases (e.g. touching digits or light background skins). Expected values are encoded in the filenames (e.g., `c1_gold_2660193.png`).

## Privacy Rules

- `f*.png`: everything outside the regions listed above is pure black `RGB(0, 0, 0)`.
- `ui/*.png`: not fully masked (village layout and resource bars are visible), but the profile box with the player name, clan tag and level must be blacked out, as must any other text that names a player or clan.
- `crops/*.png`: tiny digit patches only.
- No fixture may contain a player name, clan tag, chat text or account identifier. Check every new image by eye.

## Raw Captures are Git-Ignored

Real, unmasked captures contain sensitive personal account data. The directory `tests/fixtures/raw/` is explicitly listed in `.gitignore`:
- Unmasked screenshots must **only** reside temporarily in `tests/fixtures/raw/`.
- Never bypass `.gitignore` or force-commit raw game captures.

## How to Add a New Fixture Safely

When adding a test capture for a new resolution, OCR edge case, or UI template:

1. **Capture to Raw**: Save your original game screenshot to `tests/fixtures/raw/<name>.png`.
2. **Apply Solid Black Mask**: Use an image editor or script to mask out the entire image with solid black `(0, 0, 0)`, leaving only the target digits or button visible.
3. **Inspect the Mask**: Verify that no player names, chat boxes, clan banners, gems, or base designs remain visible anywhere in the image.
4. **Place in Fixtures**: Save the masked file to `tests/fixtures/<name>.png` (or under `tests/fixtures/ui/`).
5. **Add Test Labels**: Register the expected parsed values in `tests/fixtures/labels.json` or write a dedicated test case.
6. **Verify Git Status**: Run `git status` to confirm that `tests/fixtures/raw/` remains untracked and only your masked fixture is staged.
