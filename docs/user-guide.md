# CoC Macro User Guide

Comprehensive guide to setting up, configuring, and operating **CoC Macro** for Clash of Clans in **Google Play Games for PC**.

---

## Table of Contents

1. [First Run & Setup](#first-run--setup)
2. [Window Selection & Multi-Account Tabs](#window-selection--multi-account-tabs)
3. [Calibration](#calibration)
4. [Recording Deployments](#recording-deployments)
5. [Settings & Modes](#settings--modes)
6. [Monitoring & Activity Log](#monitoring--activity-log)
7. [Global Hotkeys & Controls](#global-hotkeys--controls)
8. [Troubleshooting](#troubleshooting)

---

## First Run & Setup

### Requirements

- **Operating System**: Windows 10 or 11 (64-bit).
- **Game Platform**: Google Play Games for PC running Clash of Clans.
- **Python**: Version 3.12 or newer (only if running from source).

### Launching the Application

1. Start **Google Play Games for PC** and launch Clash of Clans.
2. Launch `CoCMacro.exe` (or run `python -m cocmacro` from your Python virtual environment).
3. **Terms of Service Dialog**: On the very first run, an initial warning dialog appears:
   A dialog titled `Aviso` (Notice) warns that Supercell forbids macros, that the account can be banned, and that you use the app at your own risk. It also reminds you of the hotkeys: F8 stops everything, F9 ends a deployment recording.
   - Clicking **OK** accepts the notice and creates `data/accepted.flag`.
   - Clicking **Cancel** exits the application immediately.

### Game Window Placement

- The Clash of Clans window **must not be minimized** to the Windows taskbar. Minimized windows have a 0×0 client area and cannot be captured.
- The window **can** sit completely obscured behind other application windows or off to the side. Win32 `PrintWindow` capture and message posting operate seamlessly in the background.

---

## Window Selection & Multi-Account Tabs

CoC Macro supports up to 4 concurrent game instances.

```
+-------------------------------------------------------------------------------+
| [ PlayerOne ] [ PlayerTwo ]                                   + Añadir cuenta |
| Ventana: [ Clash of Clans - PlayerOne                  v ]  [ Actualizar ]     |
| ...                                                                           |
+-------------------------------------------------------------------------------+
```

### Selecting a Window

- At the top of each tab, click `Ventana` (Window) to view all detected game windows.
- The app scans for running `crosvm` processes whose window title starts with `Clash of Clans`.
- Click `Actualizar` (Refresh) if you started a game instance after launching the macro.
- When you select a window (e.g. `Clash of Clans - PlayerOne`), the player name is automatically parsed and displayed on the tab header.

### Multi-Account Concurrency & Tab Management

- **Add an Account**: Click `+ Añadir cuenta` (+ Add account) at the bottom left to create a new tab (up to 4 total).
  - New accounts store their configuration in `data/config_<n>.json` (registered in `data/accounts.json`).
  - New tabs automatically inherit calibration settings (button coordinates, detection regions, window aspect ratio) and deployment name from `config.json`.
- **Independent Configuration**: Each account tab maintains its own loot minimums, surrender rules, attack modes, and troop deployment selection.
- **Concurrent Attacks**: Multiple accounts can run simultaneously. Each active tab runs its own background worker thread.
- **Window Ownership Guard**: A game window currently controlled by one tab cannot be controlled by another. In other tabs' dropdowns, that window appears marked as `(en uso)` (in use). Attempting to attach to an owned window is blocked with the message: `La ventana ya la usa otra cuenta` (The window is already in use by another account).
- **Exclusive Tasks**: Calibration and deployment recording require real mouse input and must be performed one account at a time. Other running bots must be paused before starting calibration or recording.
- **Close an Account**: Secondary tabs include a `Cerrar esta cuenta` (Close this account) button in the footer. The primary tab (`Cuenta 1` / `config.json`) cannot be deleted.

---

## Calibration

Calibration defines the precise on-screen coordinates for action buttons and bounding boxes where numbers are read via OCR.

### Shipped Defaults

CoC Macro includes pre-packaged calibration data (`cocmacro/defaults/templates/`) captured on a 16:9 Google Play Games window (1296×729) with the Spanish game interface (see `cocmacro/defaults.py`). A fresh installation works immediately without manual calibration.

### When to Recalibrate

Recalibration is only necessary if:
- You play Clash of Clans in a language other than Spanish.
- Your game window uses an aspect ratio different from 16:9.
- A game update relocates UI buttons or font metrics.

### Full Interactive Calibration

Click `Calibrar` (Calibrate) in the setup card or `Calibrar botones y zonas` (Calibrate buttons and regions) in the preparation card. An interactive, click-through overlay appears over the game window. Follow the 11 prompts during a normal practice attack:

1. `battle` (button): `Haz clic en Batalla` (Click Battle).
2. `find` (button): `Haz clic en Buscar batalla` (Click Find a match).
3. `attack` (button): `Haz clic en Atacar` (Click Attack).
4. `gold` (region): `Arrastra un rectangulo SOLO sobre las cifras del ORO (guiate por el recuadro punteado)` (Drag a rectangle ONLY over the gold digits; dashed guide provided).
5. `elixir` (region): `Arrastra un rectangulo SOLO sobre las cifras del ELIXIR (recuadro punteado)` (Drag a rectangle ONLY over the elixir digits; dashed guide provided).
6. `next` (button): `Haz clic en Siguiente` (Click Next).
7. `damage` (region): `Despliega una tropa y arrastra un rectangulo sobre el % de dano (recuadro punteado)` (Deploy a troop and drag a rectangle over the damage percentage).
8. `timer` (region): `Arrastra un rectangulo sobre el reloj de la batalla, ej. 2m 51s (recuadro punteado)` (Drag a rectangle over the battle clock).
9. `surrender` (button): `Haz clic en Rendirse` (Click Surrender).
10. `ok` (button): `Haz clic en Vale` (Click OK / Confirm).
11. `back` (button): `Haz clic en Volver` (Click Return).

During calibration, the overlay displays dashed guide boxes indicating suggested positions and highlights completed areas in green.

### Calibrating the Battle Clock

If the bot reads loot accurately but struggles with the battle clock, click `Calibrar reloj` (Calibrate clock) in the preparation card. Enter an attack manually and drag a rectangle over the clock digits (`La batalla acaba en: 2m 51s`).

---

## Recording Deployments

Deployments capture your custom troop, spell, and hero placements.

1. Click `Grabar despliegue` (Record deployment) or `Grabar despliegue nuevo` (Record new deployment).
2. Enter a name for the deployment when prompted (e.g. `Barch` or `GoblinFarm`).
3. Switch to your Clash of Clans window and deploy your troops manually.
   - The recorder captures mouse down, mouse up, dragging motions, mouse-wheel scrolls (used to scroll the army selection ribbon), and pauses between actions.
4. Press `F9` (or click `Terminar grabación (F9)` in the macro interface) to stop and save the recording.
5. The recording is saved as JSON in `data/recordings/<name>.json`.
6. Select the active deployment from the `Despliegue` (Deployment) dropdown menu in any account tab.

---

## Settings & Modes

Settings are configured individually per tab under the `Reglas` (Rules) card. When an account is actively attacking, rule entries are locked to prevent configuration conflicts.

### Minimum Loot Thresholds

- **`Oro` (Gold)**: Minimum gold required to attack (`gold_min`, default `500000`).
- **`Elixir` (Elixir)**: Minimum elixir required to attack (`elixir_min`, default `500000`).

Both resources must meet or exceed their respective thresholds. If either resource is below the minimum, the bot clicks `Siguiente` (Next) to scout another village.

### Surrender Rules

The bot monitors the battle and clicks `Rendirse` (Surrender) followed by `Vale` (OK) when either condition is met:

- **`el daño supera ... %` (Damage %)**: Surrenders when total base destruction exceeds this percentage (`surrender_pct`, default `50%`). Set to `100` to let attacks run to completion.
- **`o quedan menos de ...` (Time Remaining)**: Surrenders when the battle clock drops below this time limit (`surrender_time_s`, default `2:20` / 140 seconds). Enter in `m:ss` format (e.g. `2:20` or `1:30`). Set to `0:00` to disable the timer rule.
- **Grace Period**: The timer rule is ignored during the first 20 battle polling cycles (~10 seconds) after deployment completes. This ensures background window processing cannot trigger an immediate surrender before troops engage.

### Between-Attack Modes (`Entre ataques`)

Select what the bot does in the village between attacks:

| Mode Label | Setting | Description |
| :--- | :--- | :--- |
| `Solo atacar` | `none` | Continuous attack loop. Attacks, returns to village, and immediately searches for the next target. |
| `Mejorar muros` | `walls` | Wall upgrade mode. Checks for free builders before each attack. If more than 1 builder is free, it allocates surplus builders to the cheapest permanent upgrades, keeping exactly 1 builder reserved for walls. It then selects the wall block, opens the multi-wall panel, clicks `Añadir muro (+1)` until costs turn red, backs off 1 or 2 walls, and confirms the upgrade (`Mejorar muros`) for gold and elixir. |
| `Mejorar lo mas barato` | `busy` | Upgrades cheapest items. Checks free builders, laboratory researchers, and pet house slots. Opens the `Construir` (Build) menu, applies filters (`Permanente` + `Coste mín.`), and continuously starts the lowest-cost available upgrades until slots reach 0 or resources are depleted. Excludes siege machines listed under heroes (`skip_arrojatroncos`, `skip_destructor`, `skip_tiradora`). Never spends gems. |

### Additional Rule Options

- **`Parar si los depositos estan llenos` (`stop_when_full`)**:
  Monitors the visual fill level of your gold and elixir storage bars at the top right of the village screen. If both storages are full, attacks pause until resources are spent. In `walls` or `busy` mode, the bot uses free builders to spend resources before resuming attacks.
- **`Heroes primero (modo Mejorar lo mas barato)` (`prioritize_heroes`)**:
  In `busy` mode, the bot checks the `Heroe` (Hero) filter on the builders tab first. If a hero upgrade is affordable, it upgrades the hero before falling back to general buildings.
- **`Solo simular (no pulsa nada)` (session only, not saved)**:
  Simulate-only mode. The bot captures the active screen, executes OCR on loot, damage, and clock readings, and logs whether it would attack or skip without sending any mouse clicks or keystrokes to the game.

---

## Monitoring & Activity Log

### Status Card & Phase Stepper

The `Estado` (State) card displays real-time progress:

- **State Title**: Current high-level status (e.g. `Listo para atacar` / Ready to attack, `Buscando aldea` / Searching village, `Parando…` / Stopping).
- **Session Attack Counter**: Total successful attacks completed during the current application session.
- **Phase Stepper**: Visual indicator showing the active phase of the attack loop:
  `Buscar` (Search) → `Evaluar` (Evaluate) → `Desplegar` (Deploy) → `Vigilar` (Watch) → `Rendirse` (Surrender) → `Volver` (Return).

### Perception Tiles (`Lo que ve el bot`)

Shows what the bot's vision system reads in real time:

- **`Oro` (Gold)**: Parsed gold reading with status text (`supera ...` or `no llega a ...`).
- **`Elixir` (Elixir)**: Parsed elixir reading with threshold status.
- **`Daño` (Damage)**: Parsed destruction percentage with a visual fill bar progressing toward your surrender target.
- **`Reloj` (Clock)**: Parsed countdown timer with active rule status.
- **`Leer ahora` (Read now)**: Captures the screen immediately and displays current OCR values in the tiles and log.

### Activity Log (`Registro`)

The scrollable log box records timestamped actions and status updates with color tags:

- **Green (`ok`)**: Attack initiated (`Atacando`), hash verification passed (`Hash correcto`).
- **Yellow (`warn`)**: Skipping village (`Siguiente`), waiting for screens (`Sigo esperando`), initiating surrender (`Rindiendose`).
- **Red (`bad`)**: Errors, timeouts, or aborted tasks (`Error`, `No se pudo`, `Atencion`, `Tiempo agotado`).

---

## Global Hotkeys & Controls

Global hotkeys operate system-wide even when CoC Macro or Google Play Games is in the background:

- **`F8` (Emergency Stop)**: Immediately signals all running bots across all tabs to halt. Any active cycle cleanly finishes its current safety step and returns to idle.
- **`F9` (End Recording)**: Finishes and saves the active troop deployment recording.
- **Per-Tab Controls**:
  - `Empezar` (Start): Starts the automated attack loop for the current tab.
  - `Parar (F8)` (Stop): Stops the automated loop for the current tab.

---

## Troubleshooting

### Resolution and Window Proportions

- **Symptoms**: Buttons are clicked off-target; templates fail to match.
- **Solution**: The default calibration assumes a standard 16:9 aspect ratio at 1296×729. If your window has different proportions or a customized DPI scale, click `Calibrar` and complete the guided attack to calibrate button coordinates and detection regions for your screen.

### Window Minimized Errors

- **Symptoms**: Log displays `WindowMinimized` or reports that the game client size is 0×0.
- **Solution**: Restore the Google Play Games window so it is visible on your desktop. It can be completely covered by other windows (e.g. your browser or text editor), but it must not be minimized to the Windows taskbar.

### OCR Misreading Loot Digits

- **Symptoms**: The bot skips desirable villages or misreads digits; log shows `No se pudo leer oro y elixir de forma fiable`.
- **Safety Limit**: If the bot encounters 5 consecutive unreadable villages (`unreadable_limit = 5`), it automatically stops to prevent wasting gold on skips.
- **Debug Captures**: When an OCR error occurs, debug screenshots are saved to `data/debug/<account_index>/`. Inspect these images to verify if a village scenery skin or graphic effect obstructed the numbers.
- **Solution**: Recalibrate the `gold` and `elixir` regions using `Calibrar botones y zonas`. Ensure your rectangle covers only the white number text without including the coin/droplet icons.

### Inactivity Disconnections & Popups

- **Automatic Recovery**: If Clash of Clans disconnects due to inactivity, the bot detects the dialog, clicks `VOLVER A CARGAR` (Reload), and waits up to 5 minutes for the village to reload.
- **Popup Handling**: Post-battle star bonus notices (`Vale`) or unexpected notices are automatically closed before starting search clicks.
- **No-Gem Guarantee**: If a builder is unavailable during an upgrade, the game prompts to finish existing tasks with gems. The bot automatically clicks the close button (`X`) and logs: `No hay constructores libres: cierro el aviso sin gastar gemas`. The bot never spends gems.

### Application Updates

- **Automatic Check**: Enable `Buscar actualizaciones al abrir` (Check for updates on startup) in the footer to check for new releases automatically upon launch.
- **Manual Check**: Click `Buscar actualizaciones` (Check for updates) in the footer at any time.
- **Update Workflow**: The updater queries the project's GitHub Releases page over HTTPS, downloads `CoCMacro.exe`, verifies its SHA-256 hash against the release digest, renames the running binary, and restarts the application seamlessly.
- **Running From Source**: In-app updating is only available for the packaged executable. If running from source, update using standard git commands:
  ```bash
  git pull
  ```

### Data Privacy Reminder

All account settings, calibration templates, and troop deployment recordings reside in the `data/` folder next to the program executable:
- `data/config.json` (and `data/config_<n>.json`): Account configuration files.
- `data/templates/`: Template crops from your game client.
- `data/recordings/`: Recorded deployment sequences.
- `data/debug/`: Diagnostic screen captures.

Because these files contain screen captures and configuration details from your personal Clash of Clans account, **never commit, share, or upload the `data/` directory**.
