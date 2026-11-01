# CoC Macro

Small Windows app that automates the *search → attack → surrender* loop of Clash of Clans
running in **Google Play Games for PC**, with the game window in the background.

- Clicks the fixed buttons (Batalla → Buscar batalla → Atacar) and reads the loot of each village
  (gold and elixir). It presses **Siguiente** until both are above your minimum.
- Replays a **deployment you recorded** (your own clicks, drags, mouse-wheel turns and pauses).
- Surrenders when the damage passes a % **or** the battle clock drops below a set time.
- Stops on **F8** at any time; **F9** ends a deployment recording.

> **Warning:** Supercell forbids automating attacks with macros. Using this tool can get your
> account banned. You use it at your own risk.

## Use

1. Download `CoCMacro.exe` from the Releases page (or run `python -m cocmacro`).
2. Open Clash of Clans in Google Play Games, keep the window not minimised.
3. **Calibrar**: do one normal attack by hand while following the prompts (buttons and the
   rectangles where gold, elixir, damage % and the clock are read).
4. **Grabar despliegue**: deploy your troops once; press F9 to finish.
5. Set minimums and surrender rules, then **Empezar**. Tick *Solo simular* first to check the reading.

Settings, calibration and recordings are saved in a `data/` folder next to the program. They contain
screen crops from your own game: do not share that folder.

## Develop

```
python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
python -m pytest            # unit tests
python -m pytest -m integration   # needs the game open
```

Test fixtures are masked captures (only numbers and one button are visible); see `tests/fixtures/README.md`.
Design and plan: `docs/superpowers/`.
