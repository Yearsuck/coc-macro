import tkinter as tk

import pytest

from cocmacro import accounts, config, gui, recorder, theme, updater, winctl
from cocmacro.recorder import Event, Recording
from cocmacro.winctl import GameWindow, WindowInfo


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


def calibrate_panel(panel):
    cfg = config.Config(
        aspect=1296 / 729,
        buttons={n: (0.5, 0.5) for n in ["battle", "find", "attack", "next", "surrender", "ok", "back"]},
        deployment="d",
    )
    panel.cfg = cfg
    gui.TPL_DIR.mkdir(parents=True, exist_ok=True)
    for n in ("battle", "next", "ok", "back", "surrender"):
        (gui.TPL_DIR / f"{n}.png").write_bytes(b"x")
    recorder.save_recording(Recording("d", 1.78, [Event(0.0, "down", 0.5, 0.5)]), gui.REC_DIR)
    config.save(cfg, panel.cfg_path)
    panel.refresh_state()


def test_fresh_data_dir_has_one_tab(app):
    """Fresh install starts with one tab, tab text Cuenta 1, btn_add active, close disabled/unmapped."""
    assert len(app.panels) == 1
    assert app.panels == [app.panel]
    assert app.nb.tab(app.panel, "text") == "Cuenta 1"
    assert str(app.btn_add.cget("state")) == "normal"
    assert str(app.panel.btn_close.cget("state")) == "disabled" or not app.panel.btn_close.winfo_ismapped()


def test_registry_with_two_accounts_builds_panels_in_order(tk_root, tmp_path, monkeypatch):
    """Loading a registry with config.json and config_2.json builds both panels in order."""
    monkeypatch.setattr(gui, "CFG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(gui, "TPL_DIR", tmp_path / "templates")
    monkeypatch.setattr(gui, "REC_DIR", tmp_path / "recordings")
    monkeypatch.setattr(gui, "DATA", tmp_path)
    monkeypatch.setattr(gui.hotkeys, "start", lambda *a, **k: (lambda: None))
    monkeypatch.setattr(updater, "check", lambda current: None)
    monkeypatch.setattr(gui.winctl, "find_game_window", lambda title="": (_ for _ in ()).throw(winctl.WindowNotFound()))
    monkeypatch.setattr(gui.winctl, "list_game_windows", lambda: [])

    config.save(config.Config(account_name="Principal"), tmp_path / "config.json")
    config.save(config.Config(account_name="Secundaria"), tmp_path / "config_2.json")
    accounts.save_registry(tmp_path, ["config.json", "config_2.json"])

    a = gui.App(tk_root)
    try:
        assert len(a.panels) == 2
        p1, p2 = a.panels
        assert p1.index == 1 and p1.cfg_path == tmp_path / "config.json"
        assert p2.index == 2 and p2.cfg_path == tmp_path / "config_2.json"
        assert a.nb.tab(p1, "text") == "Principal"
        assert a.nb.tab(p2, "text") == "Secundaria"
    finally:
        a.dispose()
        for w in tk_root.winfo_children():
            w.destroy()


def test_add_account_copies_calibration_and_caps_at_max(app):
    """Adding an account copies calibration from tab 1; caps at MAX_ACCOUNTS and logs beyond that."""
    calibrate_panel(app.panel)
    config.save(app.panel.cfg, app.panel.cfg_path)          # the new account copies tab 1's config FILE
    app.add_account()

    assert len(app.panels) == 2
    p2 = app.panels[1]
    assert p2.index == 2
    assert (gui.DATA / "config_2.json").exists()
    # tab 1's calibration is copied; the panel then adds the shipped defaults that are missing
    assert all(p2.cfg.buttons[k] == v for k, v in app.panel.cfg.buttons.items())
    assert accounts.load_registry(gui.DATA) == ["config.json", "config_2.json"]
    assert app.nb.select() == str(p2)

    # Add up to MAX_ACCOUNTS (4)
    app.add_account()
    assert len(app.panels) == 3
    app.add_account()
    assert len(app.panels) == 4
    assert str(app.btn_add.cget("state")) == "disabled"

    # A 4th add is a no-op that logs
    app.add_account()
    assert len(app.panels) == 4
    assert not app.panel.q.empty()
    kind, msg = app.panel.q.get_nowait()
    assert kind == "log" and "max accounts" in msg


def test_close_account_behaviours(app, monkeypatch):
    """close_account requires confirmation, refuses busy panels and tab 1, and preserves config file."""
    app.add_account()
    assert len(app.panels) == 2
    p2 = app.panels[1]

    # askyesno -> False: nothing changes
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    app.close_account(p2)
    assert len(app.panels) == 2

    # busy panel: refuses with showwarning, nothing changes
    warning_called = []
    monkeypatch.setattr(gui.messagebox, "showwarning", lambda *a, **k: warning_called.append(a))
    p2.busy = True
    app.close_account(p2)
    assert len(app.panels) == 2
    assert len(warning_called) == 1
    p2.busy = False

    # running mode panel: refuses with showwarning
    warning_called.clear()
    p2.mode = "running"
    app.close_account(p2)
    assert len(app.panels) == 2
    assert len(warning_called) == 1
    p2.mode = "idle"

    # tab 1 cannot be closed
    app.close_account(app.panels[0])
    assert len(app.panels) == 2
    assert app.panels[0].index == 1

    # confirm close tab 2: removed from registry, kept on disk
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    app.close_account(p2)
    assert len(app.panels) == 1
    assert accounts.load_registry(gui.DATA) == ["config.json"]
    assert (gui.DATA / "config_2.json").exists()
    assert str(app.btn_add.cget("state")) == "normal"


def test_window_selector_populates_and_updates_tab_title(app, monkeypatch):
    """Selecting a window sets window_title, extracts account_name, saves config, and updates tab title."""
    windows = [
        WindowInfo(10, "Clash of Clans - PlayerOne", 1296, 729),
        WindowInfo(20, "Clash of Clans - PlayerTwoo", 1296, 729),
    ]
    monkeypatch.setattr(gui.winctl, "list_game_windows", lambda: windows)

    panel = app.panel
    panel.refresh_windows()
    assert list(panel.win_combo["values"]) == [w.title for w in windows]

    panel.win_combo.set("Clash of Clans - PlayerTwoo")
    panel._on_window_selected()

    assert panel.cfg.window_title == "Clash of Clans - PlayerTwoo"
    assert panel.cfg.account_name == "PlayerTwoo"
    assert config.load(panel.cfg_path).window_title == "Clash of Clans - PlayerTwoo"
    assert app.nb.tab(panel, "text") == "PlayerTwoo"


def test_window_in_use_shows_suffix_and_selection_is_refused(app, monkeypatch):
    """A window claimed by another panel shows ' (en uso)' and selecting it is rejected."""
    w1 = WindowInfo(10, "Clash of Clans - Cuenta1", 1296, 729)
    w2 = WindowInfo(20, "Clash of Clans - Cuenta2", 1296, 729)
    monkeypatch.setattr(gui.winctl, "list_game_windows", lambda: [w1, w2])

    app.add_account()
    p1, p2 = app.panels
    app.claim_window(p1, 10)

    p2.refresh_windows()
    assert "Clash of Clans - Cuenta1 (en uso)" in p2.win_combo["values"]
    assert "Clash of Clans - Cuenta2" in p2.win_combo["values"]

    p2.cfg.window_title = "Clash of Clans - Original"
    p2.win_combo.set("Clash of Clans - Cuenta1 (en uso)")
    p2._on_window_selected()

    # Rejection leaves cfg.window_title unchanged and logs
    assert p2.cfg.window_title == "Clash of Clans - Original"
    assert not p2.q.empty()
    kind, msg = p2.q.get_nowait()
    assert kind == "log" and msg == "La ventana ya la usa otra cuenta"


def test_find_window_passes_title_and_handles_ambiguous(app, monkeypatch):
    """_find_window passes cfg.window_title; AmbiguousWindow in refresh_state sets 'Juego no encontrado'."""
    calls = []

    def spy_find(title=""):
        calls.append(title)
        if not title:
            raise winctl.AmbiguousWindow("Hay varias ventanas de Clash of Clans: elige una")
        return GameWindow(10, 1296, 729)

    monkeypatch.setattr(gui.winctl, "find_game_window", spy_find)
    panel = app.panel

    panel.cfg.window_title = "Clash of Clans - Específica"
    win = panel._find_window()
    assert calls[-1] == "Clash of Clans - Específica"
    assert win.hwnd == 10

    # With empty title, AmbiguousWindow is caught by refresh_state and shows chip
    panel.cfg.window_title = ""
    panel.refresh_state()
    assert calls[-1] == ""
    chip_texts = [txt.cget("text") for _, txt in panel.chip_frames]
    assert chip_texts[0] == "Juego no encontrado"


def test_claim_window_ownership(app):
    """claim_window enforces single panel ownership of an hwnd; release frees it."""
    app.add_account()
    pA, pB = app.panels

    assert app.claim_window(pA, 7) is True
    assert app.claim_window(pB, 7) is False
    assert app.claim_window(pA, 7) is True
    assert app.window_in_use_by_other(pB, 7) is True
    assert app.window_in_use_by_other(pA, 7) is False

    app.release_window(pA)
    assert app.window_in_use_by_other(pB, 7) is False
    assert app.claim_window(pB, 7) is True


def test_try_exclusive_and_release(app):
    """try_exclusive grants exclusive access only when no panel is busy or running."""
    app.add_account()
    pA, pB = app.panels

    assert app.try_exclusive(pA) is True
    assert app.exclusive is pA
    assert app.try_exclusive(pB) is False

    app.release_exclusive(pA)
    assert app.exclusive is None
    assert app.try_exclusive(pB) is True
    app.release_exclusive(pB)

    # Busy panel prevents exclusivity
    pB.busy = True
    assert app.try_exclusive(pA) is False
    pB.busy = False

    # Running panel prevents exclusivity
    pB.mode = "running"
    assert app.try_exclusive(pA) is False
    pB.mode = "idle"


def test_exclusive_disables_empezar_and_calibrate_on_other_panel(app):
    """While panel A is exclusive, panel B's Empezar and Calibrar/Grabar buttons are disabled."""
    app.add_account()
    pA, pB = app.panels
    calibrate_panel(pA)
    calibrate_panel(pB)

    assert str(pB.btn_start.cget("state")) == "normal"
    assert str(pB.btn_cal.cget("state")) == "normal"
    assert str(pB.btn_rec.cget("state")) == "normal"

    assert app.try_exclusive(pA) is True
    pB.refresh_state()

    assert str(pB.btn_start.cget("state")) == "disabled"
    assert str(pB.btn_cal.cget("state")) == "disabled"
    assert str(pB.btn_rec.cget("state")) == "disabled"

    app.release_exclusive(pA)
    pB.refresh_state()

    assert str(pB.btn_start.cget("state")) == "normal"
    assert str(pB.btn_cal.cget("state")) == "normal"
    assert str(pB.btn_rec.cget("state")) == "normal"


def test_hotkey_stop_posts_to_every_panel(app):
    """F8 stop hotkey enqueues ('stop', None) on every panel."""
    app.add_account()
    assert len(app.panels) == 2
    app._hotkey_stop()

    assert app.panels[0].q.get_nowait() == ("stop", None)
    assert app.panels[1].q.get_nowait() == ("stop", None)


def test_must_not_start_bot_on_owned_window(app, monkeypatch):
    """A bot job refuses to start on a window owned by another panel."""
    app.add_account()
    pA, pB = app.panels
    app.claim_window(pA, 42)

    monkeypatch.setattr(pB, "_find_window", lambda: GameWindow(42, 1296, 729))
    monkeypatch.setattr(gui.preflight, "check", lambda *a, **k: None)

    class SyncThread:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(gui.threading, "Thread", SyncThread)

    pB.dry.set(True)
    pB.start()

    assert pB.bot is None
    found_log = False
    while not pB.q.empty():
        kind, val = pB.q.get_nowait()
        if kind == "log" and val == "La ventana ya la usa otra cuenta":
            found_log = True
    assert found_log is True


def test_must_not_calibrate_or_record_while_another_panel_bot_runs(app):
    """Calibrating or recording is rejected when another panel's bot is running."""
    app.add_account()
    pA, pB = app.panels
    pA.mode = "running"

    pB.calibrate()
    assert pB.q.get_nowait() == ("log", "Para los demas bots antes de calibrar o grabar")

    pB.calibrate_timer()
    assert pB.q.get_nowait() == ("log", "Para los demas bots antes de calibrar o grabar")

    pB.toggle_record()
    assert pB.q.get_nowait() == ("log", "Para los demas bots antes de calibrar o grabar")
    assert pB.recorder is None


def test_must_not_close_tab_1(app, monkeypatch):
    """Tab 1 can never be closed or removed from the registry."""
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    app.close_account(app.panels[0])

    assert len(app.panels) == 1
    assert app.panels[0].index == 1
    assert accounts.load_registry(gui.DATA) == ["config.json"]


def test_must_not_delete_closed_account_config_file(app, monkeypatch):
    """Closing an account removes it from the registry but preserves config file on disk."""
    app.add_account()
    cfg2_file = gui.DATA / "config_2.json"
    assert cfg2_file.exists()

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    app.close_account(app.panels[1])

    assert len(app.panels) == 1
    assert cfg2_file.exists()


def test_claim_window_runs_on_the_bot_thread_so_it_never_touches_widgets(app, monkeypatch):
    """claim_window is called from the bot thread: tkinter widgets must not be touched there."""
    real = app.panel.refresh_state
    monkeypatch.setattr(app.panel, "refresh_state", lambda: (_ for _ in ()).throw(AssertionError("widget access")))
    assert app.claim_window(app.panel, 99) is True          # would raise if it refreshed widgets
    monkeypatch.setattr(app.panel, "refresh_state", real)
    app.panel.q.put(("refresh_all", None))
    app.panel._poll()                                       # the Tk thread handles the refresh event
