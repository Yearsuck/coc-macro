# Multi-account tabs: one app, one bot per Clash window (2026-11-07)

## Intent and why

The user plays two accounts on one PC with Google Play Games on PC multi-instancing (verified 2026-11-07: two
windows, `Clash of Clans - PlayerOne` and `Clash of Clans - PlayerTwo`, both 1297x729, different villages,
both captured correctly by `winctl.capture`, one in the foreground and one behind it). Today the app drives a
single window (`winctl.find_game_window()` returns the first one it finds) and has one config, one bot, one
log. The user wants **one executable, with a tab per account**, each tab picking which Clash window it drives, so
both accounts attack at the same time without running two copies of the program.

## Goals

- A tab per account (up to 4: Play Games' own window limit). Each tab is today's whole screen: state, setup
  steps, live reading, rules, deployment, log, `Empezar` (Start) / `Parar` (Stop).
- Each tab has its own **window selector** (dropdown of the open `Clash of Clans - <account name>` windows, with a
  refresh button) and its own settings: mode (none / walls / busy), "heroes first", stop when full, loot minimums,
  surrender rules, deployment. Two accounts can run different modes and different deployments.
- Both bots run at the same time (one thread each). No real mouse or foreground needed: capture is
  `PrintWindow`, clicks and deployments are posted window messages.
- **F8 stops every account.** Each tab also has its own `Parar`.
- An existing install keeps working untouched: tab 1 is the current `data/config.json`.
- A new tab starts with the calibration (buttons, regions) copied from tab 1: same window size, so no
  recalibration.

## Non-goals and anti-goals

- No changing mode over time inside one account (e.g. walls every N attacks, then busy). Not asked for yet; each
  tab keeps one mode, as today. Separate request if wanted.
- No two bots on the same window. Starting a tab on a window another running tab owns is refused with a message.
- No running calibration or recording in two tabs at once (they read the real mouse): while one runs the other
  tabs' `Calibrar` (Calibrate) / `Grabar` (Record) are disabled.
- No new automation features, no second update checker, no per-tab update prompts.
- Anti-goal: a regression in the single-account experience (same screens, same text, same defaults) or a tab
  whose bot can click in the other tab's window.

## Constraints

- tkinter UI, Windows only, packaged with PyInstaller as the single `CoCMacro.exe`.
- The whole program is small and tested (379 tests, `tests/test_gui_smoke.py` runs the real `App`). Keep that
  true: logic that can live outside tkinter (window listing, account registry, duplicate-window guard) goes in
  testable modules.
- Shared and global by nature: the F8 / F9 `pynput` hotkeys, the update check and the Supercell warning (once,
  at app level), `data/templates` and `data/recordings` (shared by all tabs). The lazy module caches
  `ocr._templates` and `vision._zero` are idempotent loads, safe from two threads.
- Windows are matched by title text, which carries the Play Games gamer name. The `hwnd` is resolved at `Empezar`,
  not stored.

## Design (decided)

- **`winctl`**: `list_game_windows()` returns every visible `crosvm` window titled `Clash of Clans...` as
  (hwnd, title, client size). `find_game_window(title="")` keeps today's behaviour when `title` is empty (first
  window) and otherwise picks the one whose title equals / contains it; `WindowNotFound` as now. `overlay` takes
  the finder as it already does.
- **Config**: new `Config.window_title: str = ""` and `Config.account_name: str = ""`. Accounts registry in
  `data/accounts.json`: an ordered list of config file names. Tab 1 is `config.json` (no migration); tab n is
  `config_n.json`. A missing or corrupt registry means a single tab.
- **GUI**: `App` becomes the shell (root, notebook, header, hotkeys, updater, warning, footer). Today's per-account
  code moves into `AccountPanel(tk.Frame)` with its own `cfg`, queue, stop event, bot, recorder, busy / mode /
  phase, overlay and poll timer, built from its config path. Behaviour of a single panel is unchanged; this
  refactor lands first, on its own, with all tests green. Then tabs, add (+) and close tabs, the window selector
  and the guards.
- **Guards**: a start-time registry of owned `hwnd`s refuses a second bot on the same window; one global
  "calibrating or recording" owner; closing a running tab asks to stop it first.
- **F8** posts stop to every panel. **F9** ends the recording of whichever panel is recording.
- **Window chip** (the game chip in the header) shows the selected window of the visible tab; a missing window
  is shown on that tab only.

## Verified premise (spike, 2026-11-07)

With both Clash windows in the background (focus on another app): captures of a window 4 s apart differ
(live frames, mean abs diff 2.0), and a wheel turn posted with `winctl.post_wheel` to a background window
changed it (diff 27.6). So posted input and `PrintWindow` work on unfocused `crosvm` windows: two independent
threads are viable, no focus switching or input serialisation is needed.

## Decisions (supervisor's calls, from the builder check; the user may change them)

- **Window matching**: exact title first, then "contains". An empty `window_title` is allowed only when exactly one
  game window is open (today's behaviour); with several open, `Empezar` is refused with "elige una ventana" ("choose a window"). The
  title is persisted per tab and re-resolved at `Empezar` and on refresh; if the window is gone the tab shows it
  missing and `Empezar` is refused. The duplicate-window guard works on the resolved `hwnd`, empty titles included.
- **Calibrate / record**: allowed only when no tab has a bot running; while one tab calibrates or records, the
  other tabs' `Empezar` / `Calibrar` / `Grabar` are disabled. (Conservative and the same as today's single app.)
- **New tab calibration**: one-time copy at creation of `buttons`, `regions`, `tpl_size` and `aspect` from tab 1
  plus the deployment NAME (recordings are shared, so the new account starts on the same attack; never mode or
  thresholds). Independent afterwards; recalibrating tab 1 does not change the others.
- **Closing tabs**: the registry stores explicit file names. Tab 1 cannot be closed. Closing a tab removes it
  from the registry and keeps its config file on disk; a new tab never reuses a file name (next unused number).
  Closing a running tab is refused with a message (stop it first); it never stops a bot by itself.
- **Debug captures**: per account, `data/debug/<n>` (n = file number, 1 for `config.json`), pruned per folder.
- **Account name**: filled automatically from the selected window title (the text after `Clash of Clans - `);
  not typed. Before a window is chosen the tab is called `Cuenta N` (Account N).
- **Listing**: minimized windows count (they are visible to Windows); the dropdown marks windows already used by
  another tab as "(en uso)" ("(in use)"). The `+` button is disabled at 4 tabs.

## Left to the builder

Tab labels and layout details (keep the existing look), exact wording of messages (Spanish, as now), how to
share one calibrated config between panels internally, the internal API between `App` and `AccountPanel`,
test structure.

## Plan shape (for writing-plans)

1. `winctl` window listing and title selection, with tests.
2. `Config` fields and the accounts registry, with tests.
3. Extract `AccountPanel` from `App`, one tab, no behaviour change.
4. Tabs, add / close, window selector, duplicate-window guard, F8 to all, exclusive calibrate / record.
5. Live validation on the two real windows: read-only first (both read their own villages), then a supervised
   short run on each.
6. PR into `develop`, three read-only reviewers, release only on an explicit yes.

## Inactivity reload (added during implementation)

After long idle time the game shows a modal "Estás ahí? Se te ha desconectado por inactividad" ("Are you there? You have been disconnected due to inactivity") dialog that
swallows every click. Measured live: a click posted to a background window is ignored by this dialog unless the
window is the active one, and the button needed a slightly different point in each window. So the reload takes
the focus for a moment (one window at a time, `winctl.focused`), taps a few nearby points while keeping it, waits
for the dialog to go (the village is visible behind it, so "home" alone proves nothing), retries up to 3 times and
waits up to 5 minutes for the village (a reload can land in a live replay of an attack). The dialog is recognised
by its title AND body text; the "Conexión perdida / otro dispositivo" ("Connection lost / another device") dialog is deliberately never pressed
(reloading it would kick the account's other session). Known cost: the Alt tap used to unlock
`SetForegroundWindow` also reaches the user's active app, once when the focus is taken and once when it is given
back. Not measured: the score of the "otro dispositivo" ("another device") dialog against these templates (no capture of it was kept).
