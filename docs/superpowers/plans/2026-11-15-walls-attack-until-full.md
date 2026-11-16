# Plan (2026-11-15): walls mode = attack until a storage is full, and survive errors

Branch `feature/walls-attack-until-full`, worktree `../coc-macro-public.wt/walls-attack-until-full`.
Status: **implemented (PR #41); see Progress at the end.**

## What was asked

Walls mode does not hold up: a server error shows a "restart" message and the run dies, the loot is
sometimes not recognised and "Siguiente" sometimes does not take. Wanted: attack back to back until the
gold **or** the elixir storage is full, then upgrade as many walls as both resources pay for, then attack
again; restart after an error and carry on.

## What the recon found (evidence, 2026-11-15)

Sources: 72 failure captures in the `data\debug` folders of two installed copies of the app
(24 newest copied to `tests/fixtures/raw/loot-yellow/`, git-ignored), and two live runs on the open window.

1. **Loot OCR.** The gold number is now pale yellow (bright pixels B 194-208, G/R 241-255); elixir is
   slightly pink (min channel 220-236, still passes). `ocr.segment` cuts on `min(B,G,R) > 190`, which eats
   the yellow digits: at 190 they break up, at 170/150 a nibbled `5` reads as `9` (`565 511` -> `965511`
   at 170, `565511` at 150). The cuts disagree, so `read_crop` returns None. Reproduced offline on 22 of 24
   frames (gold None, elixir read); live 1 village in 10.
2. **Unreadable village costs ~10 s** (`MAX_READ_TRIES` 10 x 0.8 s) of the 30 s scout countdown.
3. **When the countdown ends the battle starts by itself**: "Terminar batalla" stays, "Siguiente" is gone,
   0 % damage. The bot waits for the scout screen for 60 s and stops ("Tiempo agotado esperando: aldea
   enemiga"). Seen live and in 3 saved frames. Live: pressing "Terminar batalla" with nothing deployed
   goes straight to the village (no confirmation, no results screen).
4. **"Siguiente".** 3 saved series show the same village 3 times, 10 s apart (press not taken). Live with
   one account: 10 of 10 presses taken, the button disappears 0.76-0.84 s after the press. Cause of the
   lost presses not reproduced (suspect: two accounts driven at once). Also: the bot sleeps 1.0 s after
   the press and then trusts the screen; a transition that starts later than that would be read as the
   **old** village (stale loot).
5. **Server "restart" message: no capture exists.** Only the inactivity dialog is known: an Android
   native dialog (flat dark box, white title and body, blue text button bottom-left, "VOLVER A CARGAR").
   Today only that exact title + body is pressed, on purpose (the "otro dispositivo" dialog looks alike
   and pressing it kicks the other session).
6. **Any timeout ends the run**: `Bot.run` breaks on every `_Abort`. Nothing is captured when it happens.
7. **Walls mode today** runs the wall routine before *every* attack while a builder is free, and
   `wait_if_full` only reacts when gold, elixir **and** dark are all full.

## Design

### A. Walls mode loop (`bot.py`, `game.py`)

- `RealGame.storage_levels() -> {"gold": bool|None, "elixir": bool|None, "dark": bool|None}`;
  `storages_full()` is rebuilt on it and keeps its meaning for the other modes.
- `Bot._any_storage_full()`: gold **or** elixir full, same 2-of-4 readings and HUD settle as today.
- Walls mode, before each attack:
  1. surplus builders (> 1 free) go to the cheapest permanent upgrade, as today;
  2. no storage full -> attack, the wall routine is **not** run;
  3. gold or elixir full -> `upgrade_walls` (already spends both resources, as many walls as each pays
     for); it runs again while it starts upgrades and a storage is still full (cap `MAX_SPEND_ROUNDS`);
  4. a storage full and **no free builder**: do not attack; look at the builder counter every
     `FULL_POLL_S` (reload dialogs are still handled meanwhile) until one is free, then upgrade the walls;
  5. then attack. A routine that had a builder and still upgraded nothing (no walls left, price not
     payable) does not block: log it and attack.
- `stop_when_full` keeps its meaning: with it on and everything full the bot still waits.
- `none` and `busy` modes: unchanged.

### B. Recover instead of stopping (`bot.py`, `game.py`, `vision.py`)

- `_Abort` stays for "stop for good" (F8, window gone). New `_Stuck` for timeouts, a search that did not
  start, loot unreadable N villages in a row, a reload that did not finish.
- `Bot.run` on `_Stuck`: save a capture (`dump_debug("stuck")`), then `_recover()`: press a reload dialog
  if there is one, close a notice / menu / upgrade window, results -> Volver, scout or battle -> Terminar
  batalla (+ confirmation if it shows), wait for the village (up to `RELOAD_WAIT_S`), go on with the loop.
  The bot never stops by itself for this: only F8 / Stop or a closed window end the run. Recoveries in a
  row with no finished attack pause longer each time (30 s, 60 s, ... capped at 5 min) so a broken
  screen is not hammered.
- Dialogs are looked for **while waiting** too (every ~5 s inside `_wait` and the battle loop), not only
  between attacks, so a dialog in the middle of a search is handled in seconds, not after the timeout.
- Server dialog: `vision.native_dialog(frame)` recognises the dialog family by shape (large flat dark box
  in the centre + a blue text button in its lower part) and returns where the button is.
  - inactivity dialog (title + body match): pressed at once, as today;
  - any other native dialog: capture saved to `data/debug` (first time of each run of presses), then its
    button is pressed, **every time, with no limit**, until the user stops the bot (user decision; it
    accepts that the "otro dispositivo" dialog is pressed too).
- Not possible to build from a real capture: none exists. The detector is checked against the old
  inactivity crop (positive) and every saved frame + fixture (negatives); the first real server dialog
  will be captured automatically and the detector adjusted then.

### C. Search (`ocr.py`, `bot.py`)

- OCR: binarise so that tinted text survives (candidates to measure: cut on `max(G,R)` / luminance, or
  per-crop adaptive cut; glyphs rebuilt with `scripts/build_glyphs.py` if the cut changes). Accepted when:
  all 25 raw frames read gold and elixir right (hand-labelled), every existing fixture test still passes,
  leave-one-source-out stays at 0 errors. New masked fixtures (digits only, privacy rule) + labels.
- Unreadable village: give up after ~3 s instead of ~10 s.
- "Siguiente": after the press wait for the button to disappear (up to 3 s); if it is still there, press
  again (3 times at most), then `_Stuck`. The loot is only read on a village that appeared after that.
- Battle started by itself (battle screen while waiting for the scout screen): "Terminar batalla",
  back to the village, new search. Logged, counted as a skipped village, not as an attack.

## Tasks (TDD: test first, watch it fail)

| # | Task | Files | Who |
|---|---|---|---|
| 1 | OCR for tinted loot + fixtures + glyphs | `ocr.py`, `glyphs.npz`, `tests/test_ocr.py`, `tests/fixtures/` | here (needs the raw frames and eyes on them) |
| 2 | `storage_levels`, walls loop | `game.py`, `bot.py`, `tests/test_game.py`, `tests/test_bot_modes.py` | agy |
| 3 | Next verification, short unreadable, self-started battle | `bot.py`, `tests/test_bot.py` | agy, after 2 (same file) |
| 4 | `_Stuck` + `_recover` + dialog checks while waiting + `native_dialog` | `bot.py`, `game.py`, `vision.py`, tests | agy, after 3 |
| 5 | Docs: `docs/user-guide.md`, `docs/architecture.md`, progress note | docs | agy (cheap model) |
| 6 | Live validation on the open account, PR into `develop`, 3 read-only reviewers | - | here |

Track 1 runs in parallel with 2-4 (no shared file). One atomic commit per task, `python -m pytest` green
on each.

## Verification

- Unit: full `python -m pytest` per commit.
- Offline on real data: the 25 raw frames (loot) and all 72 saved frames (no false dialog).
- Live, read-only first: storage readings, 20 villages of Next + loot with the new code.
- Live, supervised: one full walls cycle if a storage fills during the session (gold 6.0 M / elixir
  6.4 M now, 1 builder free); otherwise that path stays "not verified live" and is said so in the PR.
- Cannot be verified: the server dialog (no way to provoke it safely).

## Decisions (user, 2026-11-15)

1. Any dialog with a reload / retry button is always pressed, with no limit, until the user stops the bot.
2. Recovery (B) and the search fixes (C) apply to **every** mode, not only walls.
3. A storage full and no free builder: walls mode waits, checking periodically, until a builder is free;
   then it upgrades and goes back to the loop (attacks -> storage full -> walls).

My call, not asked: the bot never stops by itself on a timeout either, it pauses longer between
recoveries (see B).

## Not in scope

Release / version bump, the dark elixir bar, the pets counter, changes to busy mode.

## Progress (2026-11-15, night)

| Task | State |
|---|---|
| 1 OCR tinted loot | merged into `develop` (PR #40). 48 of 50 saved numbers read, 0 wrong. |
| 2-4 loop / search / recovery | implemented on this branch (agy: opus until quota, then gemini; two fix rounds, the last 7 red tests and the main loop fixed by the supervisor). Full suite green. |
| 5 docs | user guide, architecture, README updated. |
| 6 live validation | see below. PR open, reviewers pending. |

Verified live on the open account (2026-11-15):
- 3 full attacks in walls mode with the new loop (search, verified Siguiente, deploy, surrender, back).
- An inactivity dialog that was on screen at start: pressed by the bot, village back, run continued.
- A stuck start (game left on the scout screen, countdown ran out, battle started by itself): timeout ->
  capture saved -> `_recover` ended the battle -> village -> attack completed.
- `vision.native_dialog` on the real inactivity frame: point (0.354, 0.569) = button centre; 0 hits on 151 other frames.

- A real server dialog appeared in the last live run, in the middle of a battle: `Conexion perdida ... REINTENTAR`.
  The shape detector (written from the inactivity dialog alone) found it, saved it and pressed it. Kept as
  `tests/fixtures/ui/dialog_connection_lost.png` (masked) and used as a test. After it the game showed
  `No se ha podido atacar esta aldea. Intentalo mas tarde` (search screen with only Volver): no known screen, the
  recovery just waited. `RealGame.cancel_search` + template `search_back` now press that Volver.

NOT verified live:
- The wall upgrade after a storage fills (storages were at ~6-8 M, never full) and the wait for a builder.
- `cancel_search` and the review fixes that came after the last live run (two-look dialog confirmation, two-poll
  self-started-battle check, blind builder counter, unexpected errors recovered): unit tests only; the game was
  closed by then.
- The battle starting by itself in the middle of the evaluate loop (only reached through recovery).
- That the nudged repeat press cures the ignored `Siguiente` (seen once: 4 presses at one point ignored;
  not reproduced again in 40 + ~10 presses).

Review (3 read-only reviewers): logic APPROVE; game/vision and tests REQUEST_CHANGES, all addressed: dialog must be
seen twice before a press, rightmost button on two-button dialogs, guarded debug dump, self-start needs two polls,
blind builder counter stops the wait after 6 looks, unexpected exceptions are recovered, and tests for the 18
mutations that survived (detector guards, `_Stuck` at every timeout site, dialog in battle / while waiting).

Open / known:
- `glyphs.npz` not rebuilt; `scripts/build_glyphs.py` reports 1 leave-one-out error (`f052/damage`).
- A 60 s wait takes ~107 s of wall time: each poll also grabs frames for the notice and dialog checks.
- Raw captures (git-ignored): `tests/fixtures/raw/{loot-yellow,battle-started,dialogs}`.
