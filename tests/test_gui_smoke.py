import tkinter as tk

import pytest

from cocmacro import config, gui, recorder, theme, updater, winctl
from cocmacro.recorder import Event, Recording


@pytest.fixture(scope="module")
def tk_root():
    """One Tk root for the module: creating several in a test process fails at random on Windows."""
    try:
        root = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(gui, "CFG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(gui, "TPL_DIR", tmp_path / "templates")
    monkeypatch.setattr(gui, "REC_DIR", tmp_path / "recordings")
    monkeypatch.setattr(gui, "DATA", tmp_path)
    monkeypatch.setattr(gui.hotkeys, "start", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(updater, "check", lambda current: None)

    def no_game():
        raise winctl.WindowNotFound("no game")
    monkeypatch.setattr(gui.winctl, "find_game_window", no_game)
    a = gui.App(tk_root)
    tk_root.update()
    yield a
    a.dispose()
    for w in tk_root.winfo_children():
        w.destroy()


def calibrated(app):
    cfg = config.Config(aspect=1296 / 729, buttons={n: (0.5, 0.5) for n in
                                                    ["battle", "find", "attack", "next", "surrender", "ok", "back"]},
                        deployment="d")
    app.cfg = cfg
    gui.TPL_DIR.mkdir(parents=True, exist_ok=True)
    for n in ("battle", "next", "ok", "back", "surrender"):
        (gui.TPL_DIR / f"{n}.png").write_bytes(b"x")
    recorder.save_recording(Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5)]), gui.REC_DIR)


def test_fresh_install_only_needs_a_deployment(app):
    """The shipped calibration is applied on first start: only the deployment is left to record."""
    assert app.mode == "setup"
    assert app.setup_title.cget("text") == "Falta preparar 1 paso"
    assert gui.CFG_PATH.exists() and (gui.TPL_DIR / "next.png").exists()


def test_nothing_calibrated_shows_the_setup_screen(app, monkeypatch):
    app.cfg = config.Config()
    monkeypatch.setattr(gui.defaults, "apply", lambda cfg, tpl: False)
    app.refresh_state()
    assert app.mode == "setup"
    assert app.setup_title.cget("text") == "Falta preparar 2 pasos"
    assert str(app.setup.winfo_manager()) == "pack" and not app.state.winfo_manager()
    assert [t.cget("text") for _, t in app.chip_frames] == ["Juego no encontrado", "Sin calibrar", "Sin despliegue"]


def test_calibrated_shows_ready_and_running_locks_the_rules(app):
    calibrated(app)
    app.refresh_state()
    assert app.mode == "idle" and app.title_lbl.cget("text") == "Listo para atacar"
    assert str(app.btn_start.cget("state")) == "normal" and str(app.btn_stop.cget("state")) == "disabled"
    app.mode, app.phase = "running", "watch"
    app._apply_mode(True)
    assert app.title_lbl.cget("text") == "Vigilando la batalla"
    assert str(app.btn_start.cget("state")) == "disabled" and str(app.btn_stop.cget("state")) == "normal"
    assert all(str(e.cget("state")) == "disabled" for e in app.rule_entries)
    assert [bar.cget("bg") for _, bar in app.step_cells][3] == theme.GOLD          # current phase
    assert [bar.cget("bg") for _, bar in app.step_cells][0] == theme.OK            # done


def test_readings_are_formatted_against_the_rules(app):
    app._show_reading({"gold": 1664232, "elixir": 383078, "damage": 36, "time_left": 156})
    assert app.tiles["gold"][0].cget("text") == "1.664.232" and app.tiles["gold"][1].cget("text") == "supera 500.000"
    assert app.tiles["elixir"][1].cget("text") == "no llega a 500.000"
    assert app.tiles["damage"][0].cget("text") == "36%" and app.tiles["time"][0].cget("text") == "2:36"
    app._show_reading({})
    assert app.tiles["gold"][0].cget("text") == "—"


def test_done_returns_to_idle(app):
    calibrated(app)
    app.mode, app.phase = "running", "deploy"
    app.q.put(("done", None))
    app.root.update()
    app._poll()
    assert app.mode == "idle" and app.phase is None


def test_mode_and_stop_when_full_are_saved_and_locked_while_running(app):
    calibrated(app)
    app.mode_combo.set("Mejorar muros")
    app.full_var.set(True)
    assert app._read_cfg() is True
    assert app.cfg.mode == "walls" and app.cfg.stop_when_full is True
    assert config.load(gui.CFG_PATH).mode == "walls"
    app.mode, app.phase = "running", "watch"
    app._apply_mode(True)
    assert str(app.mode_combo.cget("state")) == "disabled" and str(app.full_chk.cget("state")) == "disabled"
