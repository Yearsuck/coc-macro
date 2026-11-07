# Development Guide for CoC Macro

This document describes how to set up the local development environment, run and test the application, regenerate OCR training assets, execute auxiliary utility scripts, build the standalone Windows binary, and follow the project's coding conventions.

---

## 1. Environment Setup

### Prerequisites
- Windows 10 or 11 (64-bit).
- Python 3.12 or newer (`pyproject.toml` requires `>=3.12`).
- Google Play Games for PC with Clash of Clans installed (default calibration assumes Spanish game language and 16:9 window aspect ratio).

### Virtual Environment Creation
Create and activate an isolated Python virtual environment from the repository root:

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1
```

### Dependency Installation
Install runtime dependencies from `requirements.txt` and packaging dependencies from `requirements-build.txt`:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-build.txt
```

#### Package Manifest
- `requirements.txt`:
  - `numpy`: Numerical operations, array slicing, and template feature math.
  - `opencv-python`: Image manipulation, template matching (`matchTemplate`), morphology, and color space transformations.
  - `Pillow`: listed in `requirements.txt` but not imported by the package, scripts or tests.
  - `pynput`: Global mouse and keyboard listeners for recording and hotkeys (`F8`/`F9`).
  - `pytest`: Automated test runner and assertion framework.
- `requirements-build.txt`:
  - `pyinstaller`: Packages the Python application into a standalone Windows `.exe`.

---

## 2. Running the Application

To run the application directly from source:

```powershell
python -m cocmacro
```


### Initial Launch Notice
On first startup, the application verifies the existence of `data/accepted.flag`. If missing, it presents the user with Supercell's Terms of Service automation warning dialog. Accepting the notice creates `data/accepted.flag` and initializes the main interface.

---

## 3. Test Suite Layout and Execution

The project uses `pytest` as its test runner. Pytest configuration is declared in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: needs the game window open (run with -m integration)"]
addopts = "-m 'not integration'"
```

### Running Unit Tests
Unit tests run entirely in-memory using mocked Windows APIs or masked fixture images without requiring Google Play Games to be open:

```powershell
python -m pytest
```

### Running Integration Tests
Integration tests verify live Win32 window discovery and background frame capture against a real running game instance:

```powershell
python -m pytest -m integration
```

### Test Suite Structure and Coverage Mapping

| Test File | Covered Module / Feature | Description |
|:---|:---|:---|
| `tests/conftest.py` | Shared test fixtures | Provides session-scoped `tk_root` fixture to prevent Tkinter multi-init crashes on Windows. |
| `tests/test_accounts.py` | `cocmacro/accounts.py` | Validates account filename validation, JSON registry loading/saving, and account copying. |
| `tests/test_bot.py` | `cocmacro/bot.py` | Core bot finite state machine tests using `FakeGame` (search, stable read, deploy, surrender, retries). |
| `tests/test_bot_modes.py` | `cocmacro/bot.py` | Tests for village upgrade modes (`walls`, `busy`), storage fullness checks, and builder spending. |
| `tests/test_calibrate.py` | `cocmacro/calibrate.py` | Tests `RectTracker`, button click capture, and dragged region rectangle validation. |
| `tests/test_config.py` | `cocmacro/config.py` | Tests `Config` dataclass loading/saving, region validation (`region_ok`), and `m:ss` time parsing. |
| `tests/test_decisions.py` | `cocmacro/decisions.py` | Tests pure predicates for `should_attack` (loot thresholds) and `should_surrender` (% and timer). |
| `tests/test_defaults.py` | `cocmacro/defaults.py` | Tests applying shipped 16:9 button coordinates, regions, and copying template assets. |
| `tests/test_game.py` | `cocmacro/game.py` | Tests `RealGame` screen matching, OCR number extraction from fixture frames, inactivity checks, storage-full and free-slot reading, upgrade dispatch, zoom-out, menu closing, reload, debug dumps and skip reasons. |
| `tests/test_geometry.py` | `cocmacro/geometry.py` | Tests coordinate transformations between normalized floats `(0..1)` and client pixel integers. |
| `tests/test_gui_smoke.py` | `cocmacro/gui.py` | End-to-end smoke tests for Tkinter `App` lifecycle, single-account panels, widgets, and bindings. |
| `tests/test_gui_tabs.py` | `cocmacro/gui.py` | Tests multi-account tabs, window selector combobox, duplicate-window guards, and tab removal. |
| `tests/test_hotkeys.py` | `cocmacro/hotkeys.py` | Tests global hotkey callback registration and event forwarding for F8 and F9. |
| `tests/test_ocr.py` | `cocmacro/ocr.py` | Digit segmentation, nearest-neighbor glyph classification, and string cleaning on fixture crops. |
| `tests/test_overlay.py` | `cocmacro/overlay.py` | Tests click-through overlay banner placement algorithms (`banner_box`) (`banner_box`). |
| `tests/test_paths.py` | `cocmacro/paths.py` | Tests data directory resolution in source mode vs frozen PyInstaller executable mode. |
| `tests/test_player.py` | `cocmacro/player.py` | Tests gesture-level deployment replay, lock acquisition, and safe mouse-up release on abort. |
| `tests/test_preflight.py` | `cocmacro/preflight.py` | Tests pre-flight sanity checks (missing calibrations, missing templates, missing recordings). |
| `tests/test_recording.py` | `cocmacro/recorder.py` | Tests `Event` and `Recording` serialization, list recordings, `Recorder` event feeding, and `player.play` replay (stop handling, button release, wheel events). |
| `tests/test_templates.py` | `cocmacro/templates.py` | Tests normalized cross-correlation template matching, strict thresholding, and label-only crops. |
| `tests/test_updater.py` | `cocmacro/updater.py` | Tests semantic version parsing, version comparison, release asset discovery, and SHA-256 checks. |
| `tests/test_upgrades.py` | `cocmacro/upgrades.py` | Tests wall upgrade sequences (zoom, add, remove, confirm) and busy builder upgrade tab routines. |
| `tests/test_viewmodel.py` | `cocmacro/viewmodel.py` | Pure viewmodel presentation logic tests (phase steps, number formatting, state titles, chips). |
| `tests/test_vision.py` | `cocmacro/vision.py` | Tests red cost color detection, storage bar fullness, builder counter zero recognition, and wall spots. |
| `tests/test_winctl.py` | `cocmacro/winctl.py` | Win32 interop unit tests using mock APIs (minimized window restoration without focus theft, mouse messages). |
| `tests/test_winctl_integration.py` | `cocmacro/winctl.py` | Live integration test (`@pytest.mark.integration`) validating game window detection and capture. |

---

## 4. Fixture and Privacy Policy

Test fixtures are stored under `tests/fixtures/`.
- **Masked Captures (`f*.png`)**: game frames (about 1297x729) where everything is blacked out except the regions the tests read (loot digits, damage percentage, battle clock).
- **UI Captures (`ui/*.png`)**: not fully masked, but the profile box (player name, clan, level) must be blacked out.
- **Strict Privacy Rule**: no fixture may contain a player name, clan tag, chat text or account identifier. See `tests/fixtures/README.md`.
- **Raw Captures (`tests/fixtures/raw/`)**: Full raw captures containing personal game data are strictly git-ignored (`.gitignore` entry `tests/fixtures/raw/`) and must never be committed.

---

## 5. Regenerating Glyphs

The digit recognition system in `cocmacro/ocr.py` relies on pre-trained glyph feature maps compiled in `cocmacro/glyphs.npz`. When adding new digit fixtures or refining digit extraction, regenerate the glyph archive using `scripts/build_glyphs.py`:

```powershell
$env:PYTHONPATH = "."
python scripts/build_glyphs.py
```

### How `build_glyphs.py` Works
1. Loads labelled digit bounding boxes from `tests/fixtures/labels.json` and standalone digit crops from `tests/fixtures/crops/*_<value>.png`.
2. Segments each component using `cocmacro.ocr.segment` and extracts normalized 12×18 feature matrices and aspect ratios using `cocmacro.ocr.features`.
3. Compiles the resulting dataset into `cocmacro/glyphs.npz` (`imgs`, `aspect`, `labels`).
4. Runs a **leave-one-source-out** cross-validation test across all fixture sources to ensure that unseen village digits generalize with 0 classification errors.

---

## 6. Helper Scripts

The `scripts/` directory contains diagnostic and maintenance utilities. Every script is documented below:

- **`scripts/build_exe.ps1`**: PowerShell build script that invokes PyInstaller with required data assets and flags to package `dist/CoCMacro.exe`.
- **`scripts/build_glyphs.py`**: Trains normalized digit glyph templates from fixture crops and saves `cocmacro/glyphs.npz` with leave-one-source-out cross validation.
- **`scripts/calibrate_from_session.py`**: Generates `data/config.json` and template crops in `data/templates/` from a recorded click session directory.
- **`scripts/capture_clicks.py`**: Records user left-clicks inside the game window, capturing before/after screenshots and relative coordinates into `clicks.json`.
- **`scripts/capture_session.py`**: Captures game window frames periodically at a fixed interval (default 1.5s) for dataset collection.
- **`scripts/spike_drag.py`**: Diagnostic spike script testing whether mouse drag events (`WM_MOUSEMOVE` while pressed) function on background windows.

---

## 7. Building the Executable

The standalone Windows executable is built using PyInstaller via `scripts/build_exe.ps1`.

### Build Command
Run the build script from the repository root:

```powershell
powershell -File scripts\build_exe.ps1
```

### PyInstaller Configuration
The script invokes PyInstaller with the following arguments:
- `--noconfirm --clean`: Cleans previous build artifacts and overwrites existing outputs.
- `--onefile`: Packages the entire application and its dependencies into a single binary.
- `--windowed`: Suppresses the Windows console window on launch.
- `--name CoCMacro`: Sets the executable name to `CoCMacro.exe`.
- `--add-data "cocmacro\glyphs.npz;cocmacro"`: Bundles the trained OCR glyph database.
- `--add-data "cocmacro\counter_zero.npz;cocmacro"`: Bundles the builder counter zero reference.
- `--add-data "cocmacro\defaults\templates;cocmacro\defaults\templates"`: Bundles factory button template images.
- `--hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32`: Ensures Windows platform backends for `pynput` are included.
- `cocmacro\__main__.py`: Entry point script.

The resulting binary is output to `dist/CoCMacro.exe`.

---

## 8. Branching and Release Flow

The repository follows a Git Flow branching model:
- **`develop`**: Main integration branch for active feature development.
- **`main`**: Production release branch representing published versions.
- **Feature / Fix Branches**: Branch off `develop` (e.g. `feature/...` or `fix/...`) and merge back into `develop` via pull requests.
- **Task Worktrees**: Isolated worktrees created from `develop` for specific tasks.
- **Release Process**:
  1. A release branch or commit on `develop` bumps the version string synchronously in `pyproject.toml` and `cocmacro/__init__.py`.
  2. `develop` is merged into `main` with a release commit: `chore(release): X.Y.Z`.
  3. A Git tag `vX.Y.Z` is pushed to GitHub. Publish `CoCMacro.exe` as a release asset; the in-app updater verifies it against the SHA-256 published by GitHub or in the release notes.
  4. `main` is merged back into `develop` to keep integration branches aligned.

---

## 9. Coding Conventions and Architecture Patterns

- **Modern Python Typing**:
  - Code uses Python 3.12+ type union syntax (`int | None`, `str | None`) rather than `typing.Optional` or `typing.Union`.
  - Type annotations are consistently applied across public module functions and class signatures.
- **Structured Data via Dataclasses**:
  - Configuration (`Config`), window references (`GameWindow`, `WindowInfo`), input events (`Event`, `Recording`), and update metadata (`UpdateInfo`) use `@dataclass` (with `frozen=True` where immutability is desired).
- **Decoupled Protocols for Testability**:
  - Core business logic communicates via `typing.Protocol` interfaces (`bot.Game` in `bot.py` and `upgrades.Screen` in `upgrades.py`). This allows bot loops and upgrade routines to be tested deterministically with in-memory test doubles (`FakeGame`, `ModeGame`).
- **Separation of Presentation and UI Toolkit**:
  - Display string formatting, progress calculation, and state translation are kept in `cocmacro/viewmodel.py`, independent of Tkinter, so they can be unit tested without a GUI.
- **Custom Domain Exceptions**:
  - Distinct exceptions handle operational states: `WindowNotFound`, `WindowMinimized`, `AmbiguousWindow`, `UpdateError`, `_Abort`, and `_Unreadable`.
- **Fail-Safe Resource Handling**:
  - Win32 handles and GDI contexts are managed with strict `try...finally` blocks (`user32.ReleaseDC`, `gdi32.DeleteDC`, `gdi32.DeleteObject`).
  - Thread locks (`_input_lock`, `_owned_lock`) and mouse button states (`down` tracking in `player.py`) guarantee release even when operations abort or raise exceptions.
