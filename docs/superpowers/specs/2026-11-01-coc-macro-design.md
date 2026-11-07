# CoC Macro: design

Date: 2026-11-01. Status: draft for approval. Decisions marked **[my decision]** were made by me, not the user.

## Intent

The user frequently attacks in Clash of Clans and wants to move fast. They want a small desktop app that repeats the cycle "search for a good village → deploy troops → surrender upon reaching 50% → start over" unattended and without keeping the game in the foreground. This allows quick resource farming.

## Verified environment (spike, 2026-11-01)

- Game running on **Google Play Games on PC**, process `crosvm`, window titled `Clash of Clans - <account name>`. Window 1315×776, client area 1296×729 (offset 9,38).
- **Background capture: works.** `PrintWindow` with flag 2 returns the image even when the window is behind others.
- **Background click: works.** `PostMessage` with `WM_LBUTTONDOWN`/`WM_LBUTTONUP` to the top-level window, using client coordinates, selected a building with Orca in the foreground.
- **Unverified:** dragging (`WM_MOUSEMOVE` with button down), long press, capture with the window minimized, and OCR reliability on numbers.

## Goals

1. Desktop window with buttons `Empezar` (Start), `Parar` (Stop), `Grabar despliegue` (Record deployment), and a selector for named saved deployments.
2. Automated loop:
   1. Fixed clicks: `Batalla` (Battle) → `Buscar batalla` (Find battle) → `Atacar` (Attack).
   2. Wait for the enemy village to load.
   3. Read gold and elixir (the first two numbers, top left). If **both** are greater than the threshold (default 500,000), attack. Otherwise, press `Siguiente` (Next) and read again, until finding a valid village.
   4. Replay the chosen troop deployment, respecting recorded pauses.
   5. With troops deployed, monitor damage %. Upon exceeding the threshold (default 50%), press `Rendirse` (Surrender) → `Vale` (OK) → `Volver` (Back).
   6. Return to step 1.
3. Everything must work with the game in the background (visible behind other windows).
4. Multiple recorded deployments selectable from the UI.

## Non-goals

- Recognizing troops, deciding where to attack, or adapting the attack to each village. The deployment is always the same recorded click sequence.
- Upgrading buildings, training troops, donating, or anything outside the attack and surrender loop (see open question).
- Supporting other emulators or mobile. Google Play Games PC only.
- Reading game memory, injecting code, or modifying the game.

## Anti-goals (would be a failure even if it "works")

- Running out of control without a way to stop it. There must be a global emergency stop key **[my decision: F8]** that works even when the game is unfocused, and a `Parar` button.
- Clicking blindly on an unexpected screen (for example, an error or connection dialog). When faced with something unrecognized, it must stop and alert, not keep clicking.
- Losing the user's recording due to a crash or failure. It is saved to disk upon completion.

## Constraints

- Python on Windows 11. UI in **tkinter [my decision]**.
- Warning accepted by the user: Supercell forbids automating attacks; there is a risk of account ban. The app must display this warning the first time it opens.
- Coordinates are stored **relative to the client area size (0–1)**, not in absolute pixels, so they survive window resizing. **[my decision]** If the window aspect ratio changes, warn and ask to recalibrate.
- Identify the window by process `crosvm` and title starting with `Clash of Clans`.

## How each component works

- **Record deployment:** global mouse hook (e.g., `pynput`), filtered to clicks inside the game window. Saves each event (down, up, move if dragging) with its relative position and the elapsed time since the previous event. Ends with a key **[my decision: F9]**. Saved as JSON, one per name.
- **Replay:** sends the same events with `PostMessage` and respects pauses. If drags do not replay properly via messages, that is a risk to resolve (see below).
- **Button calibration [my decision]:** fixed buttons (`Batalla`, `Buscar batalla`, `Atacar`, `Siguiente`, `Rendirse`, `Vale`, `Volver`) are registered once by clicking each one, rather than using hand-coded coordinates. Likewise for the crops where gold, elixir, and % are read: they are marked by dragging a rectangle over a capture.
- **Number reading:** small crop of each zone and digit recognition. Method to be chosen by whoever builds it (see "To be decided by the implementer").
- **State detection [my decision]:** before each step, verify that the screen matches expectations (for example, that the button to click is still there). Each wait has a timeout. If it expires, stop and alert.
- **Configuration** in a JSON file: resource threshold, % threshold, chosen deployment, calibrated regions and buttons.

## Minimal interface

Buttons `Empezar` / `Parar` / `Grabar despliegue`, deployment dropdown, threshold fields for resources and %, counter of completed attacks, and a text log showing current actions. A single window, nothing more.

## Risks to resolve upfront (before building the rest)

1. **Background drags:** test whether `WM_MOUSEMOVE` with button down deploys troops with the game in the background. If not, plan B: bring the window to the foreground only during deployment.
2. **OCR:** measure the accuracy rate of gold, elixir, and % numbers with real captures from the scout screen and battle.
3. **Minimized capture:** confirm that it fails and show a clear warning if it occurs.

## How it is verified

- Unit tests for logic (deciding whether to attack, deciding whether to surrender, state machine) with captures stored as fixtures. Real captures of the village scout screen, battle, and `Rendirse` button are needed; they can be captured using the same method as the spike while the user is on those screens.
- Staged manual tests: first resource reading only without clicking, then a supervised full attack, then several consecutive attacks.
- Display test output before considering anything complete.

## To be decided by the implementer

- OCR library or digit reading method (e.g., matching digit templates, or Tesseract/RapidOCR), depending on what performs best in risk 2.
- Module structure and file names.
- How to retry and log errors.

## User decisions on open questions

1. **Troop replenishment:** the game refills troops, spells, and heroes automatically. The app does not train anything or wait for them to replenish (confirmed non-goal).
2. **Battle ending on its own** (100% destruction or time expires): the app detects the results screen and only clicks `Volver`.
