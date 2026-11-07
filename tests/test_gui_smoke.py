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

    def no_game(title=""):
        raise winctl.WindowNotFound("no game")
    monkeypatch.setattr(gui.winctl, "find_game_window", no_game)
    monkeypatch.setattr(gui.winctl, "list_game_windows", lambda: [])
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
    app.panel.cfg = cfg
    gui.TPL_DIR.mkdir(parents=True, exist_ok=True)
    for n in ("battle", "next", "ok", "back", "surrender"):
        (gui.TPL_DIR / f"{n}.png").write_bytes(b"x")
    recorder.save_recording(Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5)]), gui.REC_DIR)


def test_fresh_install_only_needs_a_deployment(app):
    """The shipped calibration is applied on first start: only the deployment is left to record."""
    panel = app.panel
    assert panel.mode == "setup"
    assert panel.setup_title.cget("text") == "Falta preparar 1 paso"
    assert gui.CFG_PATH.exists() and (gui.TPL_DIR / "next.png").exists()


def test_nothing_calibrated_shows_the_setup_screen(app, monkeypatch):
    panel = app.panel
    panel.cfg = config.Config()
    monkeypatch.setattr(gui.defaults, "apply", lambda cfg, tpl: False)
    panel.refresh_state()
    assert panel.mode == "setup"
    assert panel.setup_title.cget("text") == "Falta preparar 2 pasos"
    assert str(panel.setup.winfo_manager()) == "pack" and not panel.state.winfo_manager()
    assert [t.cget("text") for _, t in panel.chip_frames] == ["Juego no encontrado", "Sin calibrar", "Sin despliegue"]


def test_calibrated_shows_ready_and_running_locks_the_rules(app):
    panel = app.panel
    calibrated(app)
    panel.refresh_state()
    assert panel.mode == "idle" and panel.title_lbl.cget("text") == "Listo para atacar"
    assert str(panel.btn_start.cget("state")) == "normal" and str(panel.btn_stop.cget("state")) == "disabled"
    panel.mode, panel.phase = "running", "watch"
    panel._apply_mode(True)
    assert panel.title_lbl.cget("text") == "Vigilando la batalla"
    assert str(panel.btn_start.cget("state")) == "disabled" and str(panel.btn_stop.cget("state")) == "normal"
    assert all(str(e.cget("state")) == "disabled" for e in panel.rule_entries)
    assert [bar.cget("bg") for _, bar in panel.step_cells][3] == theme.GOLD          # current phase
    assert [bar.cget("bg") for _, bar in panel.step_cells][0] == theme.OK            # done


def test_readings_are_formatted_against_the_rules(app):
    panel = app.panel
    panel._show_reading({"gold": 1664232, "elixir": 383078, "damage": 36, "time_left": 156})
    assert panel.tiles["gold"][0].cget("text") == "1.664.232" and panel.tiles["gold"][1].cget("text") == "supera 500.000"
    assert panel.tiles["elixir"][1].cget("text") == "no llega a 500.000"
    assert panel.tiles["damage"][0].cget("text") == "36%" and panel.tiles["time"][0].cget("text") == "2:36"
    panel._show_reading({})
    assert panel.tiles["gold"][0].cget("text") == "—"


def test_done_returns_to_idle(app):
    panel = app.panel
    calibrated(app)
    panel.mode, panel.phase = "running", "deploy"
    panel.q.put(("done", None))
    panel.root.update()
    panel._poll()
    assert panel.mode == "idle" and panel.phase is None


def test_mode_and_stop_when_full_are_saved_and_locked_while_running(app):
    panel = app.panel
    calibrated(app)
    panel.mode_combo.set("Mejorar muros")
    panel.full_var.set(True)
    assert panel._read_cfg() is True
    assert panel.cfg.mode == "walls" and panel.cfg.stop_when_full is True
    assert config.load(gui.CFG_PATH).mode == "walls"
    panel.mode, panel.phase = "running", "watch"
    panel._apply_mode(True)
    assert str(panel.mode_combo.cget("state")) == "disabled" and str(panel.full_chk.cget("state")) == "disabled"


def test_app_has_one_panel_and_forwards_stop(app):
    panel = app.panel
    assert app.panels == [panel]
    panel.q.put(("stop", None))
    panel._poll()
    assert panel.stop_ev.is_set()


def test_dispose_stops_every_panel(app):
    panel = app.panel
    assert not panel.stop_ev.is_set()
    app.dispose()
    assert panel.stop_ev.is_set()


def test_hotkeys_only_post_to_the_panel_queues(app):
    """F8 / F9 run on the pynput thread: they must queue events for the Tk thread, never touch widgets."""
    panel = app.panel
    app._hotkey_end_record()                      # nobody is recording: nothing queued
    assert panel.q.empty()
    app._hotkey_stop()
    assert panel.q.get_nowait() == ("stop", None)
    panel.recorder = object()
    app._hotkey_end_record()
    assert panel.q.get_nowait() == ("end_record", None)
    panel.recorder = None
