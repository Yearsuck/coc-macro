# Storage / wall / busy-builders modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "stop when storages full", "wall upgrade mode" and "busy builders mode" to the attack bot without changing behaviour when no mode is selected.

**Architecture:** Pure vision helpers (`vision.py`) read frames; `upgrades.py` holds the two routines over a small `Screen` protocol (grab / click / find template); `bot.py` calls one optional hook after each attack and one check before each search. New `Game` methods are optional (`getattr`), exactly like `dismiss_popup`, so existing fakes and tests keep working.

**Tech Stack:** Python 3.12, OpenCV, numpy, tkinter, pytest. Game: Clash of Clans (Spanish) in Google Play Games PC, window client 1296x729.

**Spec:** `docs/superpowers/specs/2026-11-05-storage-wall-builder-modes-design.md`

## Global Constraints

- No mode selected => `Bot._cycle` identical to today; all 65+ existing tests pass untouched.
- Never spend gems: if a confirm/upgrade shows a gem cost, abort the routine and log.
- F8 (`stop` event) must be honoured between every click of every routine (`Bot._check`).
- Coordinates are relative 0-1 of the client area; frames are normalised to 1296 px wide (`frames.grab`).
- Routine failure after 1 retry => log, abort routine, keep attacking. Unknown screen => stop (existing `_Abort`).
- UI text is Spanish; code and commits English, Conventional Commits, no `Co-Authored-By`/`Claude-Session` trailers.
- Delegated agents (`agy`) are edit-only: they cannot run tests or git. I run pytest and commit.

## Review Focus

- Counter reads `0/7` mis-parsed as `07`/`7` => bot thinks a builder is free and clicks menus forever. Test: free=0 never triggers a routine; unreadable counter => treated as "none free".
- Wall at max level 19 or no wall panel after click => routine ends, no infinite "add" loop. Test: loop bounded by `MAX_ADDS`.
- Cost red never appears (very rich account) => `+10` spam. Test: `MAX_ADDS` cap then upgrade.
- Filter popup left open / filter not applied (Héroe+Coste máx. remembered) => wrong item upgraded. Test: routine verifies `Permanente` and `Coste mín.` templates are selected before clicking first row; else abort.
- Storages full and mode `none` + `stop_when_full` => bot idles without clicking, still stoppable by F8. Test with fake game.

---

### Task 1: Config fields and defaults

**Files:** Modify `cocmacro/config.py`, `cocmacro/defaults.py`; Test `tests/test_config.py`, `tests/test_defaults.py`

**Interfaces:**
- Produces: `Config.mode: str = "none"` (`"none"|"walls"|"busy"`), `Config.stop_when_full: bool = False`; `DEFAULT_REGIONS` gains `storage_gold`, `storage_elixir`, `free_builders`, `free_researchers`, `wall_title`, `wall_cost_gold`, `wall_cost_elixir`; `defaults.BUTTONS` gains `build`, `build_close`, `filter`, `wall_more`, `wall_remove`, `wall_add10`, `wall_add1`, `wall_up_gold`, `wall_up_elixir`, `wall_spot`.

- [ ] **Step 1: Test** `test_old_config_loads_with_new_defaults` (a json without the new keys loads with `mode == "none"`, `stop_when_full is False`, and every new region present and `region_ok`); `test_defaults_apply_adds_new_buttons` (all names above present in `cfg.buttons` after `apply`).
- [ ] **Step 2:** Run `python -m pytest tests/test_config.py tests/test_defaults.py -v`; expect FAIL.
- [ ] **Step 3: Implement** fields and defaults. Starting values (1296x729 captures of 2026-11-05, to be corrected in Task 6): `build (0.945,0.905)`, `build_close (0.984,0.032)`, `filter (0.7595,0.032)`, `wall_spot (0.585,0.335)`, `wall_more (0.500,0.800)`, `wall_remove (0.339,0.800)`, `wall_add10 (0.420,0.800)`, `wall_add1 (0.500,0.800)`, `wall_up_gold (0.580,0.809)`, `wall_up_elixir (0.661,0.809)`; regions: `free_builders (0.905,0.790,0.945,0.820)`, `free_researchers (0.955,0.790,0.990,0.820)`, `wall_title (0.40,0.690,0.60,0.730)`, `wall_cost_gold (0.545,0.745,0.620,0.775)`, `wall_cost_elixir (0.625,0.745,0.700,0.775)`, `storage_gold (0.815,0.030,0.990,0.060)`, `storage_elixir (0.815,0.085,0.990,0.115)`.
- [ ] **Step 4:** Run the same tests; expect PASS. Run full `python -m pytest`.
- [ ] **Step 5:** Commit `feat(config): add mode, stop_when_full and upgrade coordinates`.

### Task 2: Vision helpers (agy: `gemini-3.8-flash-high`)

**Files:** Create `cocmacro/vision.py`; Test `tests/test_vision.py`; fixtures `tests/fixtures/ui/*.png` (cut from real captures by me in Task 6; the task uses synthetic frames for the unit tests).

**Interfaces:**
- Produces:
  - `storage_full(frame: np.ndarray, region: Region) -> bool | None` — fill of the bar behind the digits spans the region width (None if unreadable).
  - `free_count(frame: np.ndarray, region: Region) -> int | None` — first number of an `a/b` counter; `None` if unreadable. Uses `ocr` glyph machinery on the left of the slash only.
  - `cost_is_red(frame: np.ndarray, region: Region) -> bool` — share of red text pixels (R>180, G<90, B<90) above `RED_SHARE = 0.08`.
  - `Region = tuple[float, float, float, float]`.

- [ ] **Step 1: Tests** with synthetic frames: `test_cost_is_red_true_on_red_text_false_on_white`, `test_storage_full_true_when_bar_spans_region_false_when_half`, `test_free_count_none_on_blank_region`.
- [ ] **Step 2:** Run `python -m pytest tests/test_vision.py -v`; expect FAIL (module missing).
- [ ] **Step 3: Implement** the three functions. `free_count` real-data accuracy is proven in Task 6 against live captures; the unit test only pins the `None` path.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit `feat(vision): read storage fill, free counters and red costs`.

### Task 3: Upgrade routines (agy: `claude-opus-4-6-thinking`)

**Files:** Create `cocmacro/upgrades.py`; Test `tests/test_upgrades.py`

**Interfaces:**
- Consumes: `vision.*`, `Config`.
- Produces:
  ```python
  class Screen(Protocol):
      def grab(self) -> np.ndarray: ...
      def click(self, x: float, y: float) -> None: ...
      def has(self, template: str) -> bool: ...
      def find(self, template: str) -> tuple[float, float] | None: ...
  MAX_ADDS = 60
  def upgrade_walls(scr: Screen, cfg: Config, log, check, sleep) -> bool   # True if >=1 upgrade started
  def upgrade_cheapest_permanent(scr: Screen, cfg: Config, log, check, sleep) -> bool
  def free_slots(scr: Screen, cfg: Config) -> dict[str, int | None]       # keys builders, researchers
  ```
  `check()` raises on stop (pass `Bot._check`).

- [ ] **Step 1: Tests** with a scripted `FakeScreen` (records clicks, returns canned frames/`has`/`find`): `test_walls_adds_until_red_then_removes_one_then_upgrades_gold_then_elixir` (clicks order: spot, more, add10 x k, add1 x m, remove, up_gold, spot, more, …, remove, up_elixir); `test_walls_stops_when_no_wall_panel` (title unreadable => no add clicks, returns False); `test_walls_add_loop_capped_at_max_adds`; `test_busy_aborts_if_permanent_filter_not_selected` (no click on a list row); `test_busy_skips_when_first_row_cost_red`; `test_gem_confirm_aborts` (template `gem_cost` present => no confirm click).
- [ ] **Step 2:** Run `python -m pytest tests/test_upgrades.py -v`; expect FAIL.
- [ ] **Step 3: Implement.** Walls per spec "Rutina de muros". Busy: click `build`, click `filter`, click templates `filter_permanent` and `filter_cost_min` (found with `find`), verify both `has("filter_permanent_on")` / `has("filter_cost_min_on")`, close filter, find template `filtered_header` and click ~0.075 (relative y) below it for the first row, confirm button via template `confirm_upgrade`, close menu with `build_close`. One retry per step, then abort and return False.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit `feat(upgrades): wall and cheapest-permanent upgrade routines`.

### Task 4: Real-game plumbing

**Files:** Modify `cocmacro/game.py`; Test `tests/test_game.py`

**Interfaces:**
- Produces on `RealGame`: `storages_full() -> bool | None` (both gold and elixir full), `free_slots() -> dict`, and a `screen` property returning a `Screen` implementation (`grab` = `frames.grab(win)`, `click` = `winctl.click`, `has`/`find` via `templates`).
- Consumes: Task 2, Task 3 protocol.

- [ ] **Step 1: Test** `test_storages_full_requires_both` with monkeypatched `vision.storage_full` (True/False/None combinations; any None => None).
- [ ] **Step 2-4:** fail, implement, pass.
- [ ] **Step 5:** Commit `feat(game): expose storage and slot readings`.

### Task 5: Bot hooks

**Files:** Modify `cocmacro/bot.py`; Test `tests/test_bot.py`

**Interfaces:**
- Consumes: optional `game.storages_full()`, `game.free_slots()`, `game.upgrades` object with `walls()` / `busy()` returning bool (RealGame binds them to Task 3 functions).
- Behaviour: in `run()`, before each `_cycle` and when `cfg.stop_when_full` and `storages_full() is True`: if `cfg.mode == "none"` log once and wait (poll 5 s, `_check` each poll); else run the mode hook then continue. After a completed attack, mode `walls`: if `free_slots()["builders"] >= 1` run `walls()`; mode `busy`: if storages full or any slot free run `busy()`. A hook returning False or raising `_Abort`-free errors logs and continues attacking.

- [ ] **Step 1: Tests** (FakeGame subclass with the optional methods): `test_no_mode_never_calls_hooks`; `test_walls_hook_runs_only_when_builder_free`; `test_busy_hook_runs_when_storages_full`; `test_full_storages_idle_without_clicks_in_mode_none` (stop after 2 polls, `clicks == []`); `test_unreadable_counter_counts_as_none_free`; `test_hook_failure_does_not_stop_bot`.
- [ ] **Step 2-4:** fail, implement, pass; run full `python -m pytest`.
- [ ] **Step 5:** Commit `feat(bot): run storage check and upgrade hooks between attacks`.

### Task 6: GUI

**Files:** Modify `cocmacro/gui.py`, `cocmacro/viewmodel.py`; Test `tests/test_gui_smoke.py`, `tests/test_viewmodel.py`

- [ ] **Step 1: Tests:** `test_mode_label_roundtrip` (`viewmodel.MODES` maps "Ninguno/Muros/Constructores ocupados" <-> `none/walls/busy`); smoke test that the window builds and `_read_cfg` stores `mode` and `stop_when_full`.
- [ ] **Step 2-4:** fail, add a mode combobox and a "Parar con depositos llenos" checkbox to the rules card (`gui.py:193`), persist through `_read_cfg`/save, pass; full pytest.
- [ ] **Step 5:** Commit `feat(gui): mode selector and stop-when-full checkbox`.

### Task 7: Calibration and live validation (done here, not delegated)

Needs the secondary account open. Scratch scripts only; nothing stored from the account except masked template crops.

- [ ] **Step 1:** Cut templates from live captures into `cocmacro/defaults/templates/`: `filter_permanent`, `filter_permanent_on`, `filter_cost_min`, `filter_cost_min_on`, `filtered_header`, `confirm_upgrade`, `gem_cost`. Correct the default coordinates of Task 1 from real captures.
- [ ] **Step 2:** `vision.free_count` and `storage_full` on live frames: assert `0/7` => 0, full/not-full storages classified as seen.
- [ ] **Step 3:** Dry run of each routine stopping right before the final upgrade click (patch `Screen.click` to skip it); check screenshots after every step.
- [ ] **Step 4:** One real supervised wall upgrade (gold), one real `busy` upgrade; then 3 attack cycles in each mode with F8 mid-routine.
- [ ] **Step 5:** Commit fixture/template/coordinate corrections `fix(defaults): calibrate upgrade UI on real captures`.

### Task 8: Release prep (needs your explicit yes)

PR into `develop` with independent read-only review (3 reviewers on the merged result), CI green, merge `--no-ff`. Release/version bump only after you say so.

---

## Self-review

- Spec coverage: stop-when-full (T1,T2,T4,T5,T6), walls (T3,T5), busy (T3,T5), mode exclusivity + none unchanged (T1,T5,T6), live validation (T7), no gems (T3 test).
- Names consistent: `Screen`, `free_slots`, `storages_full`, `upgrade_walls`, `upgrade_cheapest_permanent`, `MAX_ADDS`, regions/buttons listed once in T1.
- Delegation: T2 -> `gemini-3.8-flash-high`; T3 -> `claude-opus-4-6-thinking` (tricky state machine); T1/T4/T5/T6 small, done here.
- Known risk: `free_count` accuracy and list-row position in the filtered menu are only proven in T7.
