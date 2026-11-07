# CoC Macro

Windows desktop automation app for Clash of Clans running in **Google Play Games for PC**. The tool operates quietly in the background using Win32 window capture and input message posting, allowing you to use your computer normally while the bot manages attacks, troop deployments, and village upgrades.

> **Warning:** Supercell forbids automating gameplay with macros or bots. Using this tool violates their Terms of Service and can result in your account being banned. Use entirely at your own risk.

## Features

- **Multi-Account Tabs**: Run up to 4 accounts concurrently in separate tabs, each driving its own game window with independent settings.
- **Automated Farming Loop**: Clicks `Batalla` (Battle) → `Buscar batalla` (Find a Match) → `Atacar` (Attack), reads enemy gold and elixir, and skips with `Siguiente` (Next) until targets meet your minimums.
- **Recorded Deployments**: Record and replay troop and spell deployment sequences, including clicks, drags, mouse-wheel turns, and pauses.
- **Smart Surrender**: Surrenders when battle destruction reaches a target damage percentage or when the countdown clock drops below a set cutoff.
- **Between-Attack Upgrade Modes**:
  - `Solo atacar` (Attack only): Pure farming loop without village maintenance.
  - `Mejorar muros` (Upgrade walls): Automatically upgrades walls between attacks while reserving a builder.
  - `Mejorar lo mas barato` (Upgrade cheapest): Automatically starts the cheapest building, research, or pet upgrade whenever slots are free, with an optional `Heroes primero` (Heroes first) priority filter.
- **Storage Protection**: Optionally pauses attacks when gold and elixir storages are completely full (`Parar si los depositos estan llenos`).
- **Resilience**: Recovers from inactivity timeouts (`VOLVER A CARGAR` / Reload) and dismisses star bonus or gem dialog popups.
- **Background Execution**: Works with the game window behind other applications without requiring window focus.
- **In-App Updater**: Checks the project's GitHub Releases page for new versions, verifies SHA-256 hashes, and safely updates the executable.
- **Global Hotkeys**: `F8` stops all running accounts immediately; `F9` ends an active deployment recording.

## Requirements

- Windows 10 or 11 (64-bit)
- Python >= 3.12 (if running from source)
- Google Play Games for PC running Clash of Clans

## Quick Start

1. Download `CoCMacro.exe` from the project's GitHub Releases page (or run from source with `python -m cocmacro`).
2. Open Clash of Clans in Google Play Games for PC. Keep the window restored (not minimized).
3. Select your game window from the `Ventana` (Window) dropdown.
4. **Calibration**: Shipped templates support standard 16:9 Spanish game windows out of the box. For other languages or window shapes, click `Calibrar` (Calibrate) and follow the on-screen prompts.
5. **Record Deployment**: Click `Grabar despliegue` (Record deployment), deploy your army in-game, and press `F9` to finish.
6. Set loot minimums and surrender conditions, then click `Empezar` (Start). Test your settings first with `Solo simular` (Simulate only).

Settings, calibration templates, and recordings are stored in a `data/` folder next to the program. They contain screen crops from your personal game session: **never share this folder**.

## How It Works

- **Capture**: Captures the game window in the background via Win32 `PrintWindow` without bringing it to the front.
- **OCR**: Segments near-white pixel clusters and matches digits against pre-learned glyph templates (`glyphs.npz`) to read loot, damage %, and the battle timer.
- **Decisions**: Evaluates loot readings to decide attack versus skip, and monitors combat damage and clock time against surrender thresholds.
- **Input**: Dispatches clicks, drags, and mouse-wheel events via Win32 `PostMessage` directly to the window client area.

## Development

Set up a virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Run unit tests:

```bash
python -m pytest
```

Run integration tests (requires an open game window):

```bash
python -m pytest -m integration
```

Build the standalone executable:

```powershell
python -m pip install -r requirements.txt -r requirements-build.txt
powershell -File scripts\build_exe.ps1
```

Test fixtures are masked screen captures; see [tests/fixtures/README.md](tests/fixtures/README.md).

## Documentation

- [User Guide](docs/user-guide.md): Comprehensive setup, multi-account tabs, modes, calibration, and troubleshooting.
- [Architecture](docs/architecture.md): System architecture, vision pipeline, and background input model.
- [Development](docs/development.md): Development setup, testing guidelines, and release builds.
- [Superpowers Specs](docs/superpowers/): Feature specifications and implementation notes.
