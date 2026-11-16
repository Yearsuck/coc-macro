import tkinter as tk

import pytest

from cocmacro import accounts, config, gui, recorder, theme, updater, winctl
from cocmacro.recorder import Event, Recording
from cocmacro.winctl import GameWindow, WindowInfo


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
    assert str(app.panel.btn_close.cget("state")) == "disabled"
    assert not app.panel.btn_close.winfo_ismapped()


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
    assert kind == "log" and "maximo" in msg


def test_close_account_behaviours(app, monkeypatch):
    """close_account requires confirmation, refuses busy panels and tab 1, and preserves config file."""
    app.add_account()
    assert len(app.panels) == 2
    p2 = app.panels[1]

    # askyesno -> False: nothing changes
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    app.close_account(p2)
    assert len(app.panels) == 2

    # busy panel: refuses with showwarning, nothing changes (a yes answer must not matter)
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
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


def test_start_checks_the_window_of_its_own_tab(app, monkeypatch):
    """preflight.check has its own untitled find_window default: with two windows open it said 'elige una'."""
    seen = {}

    def fake_check(cfg, tpl_dir, rec_dir, dry, find_window=None, capture=None):
        seen["find_window"] = find_window
        return "stop here"                                  # refuse to start: nothing else runs
    monkeypatch.setattr(gui.preflight, "check", fake_check)
    panel = app.panel
    panel.cfg.window_title = "Clash of Clans - Alguien"
    panel.start()
    assert seen["find_window"] == panel._find_window


def test_a_new_tab_is_called_cuenta_n_until_a_window_is_chosen(app):
    app.add_account()
    assert app.nb.tab(app.panels[1], "text") == "Cuenta 2"


def test_start_is_refused_when_several_windows_are_open_and_none_is_chosen(app, monkeypatch):
    def ambiguous(title=""):
        raise winctl.AmbiguousWindow("Hay varias ventanas de Clash of Clans: elige una")
    monkeypatch.setattr(gui.winctl, "find_game_window", ambiguous)
    calibrate_panel(app.panel)
    app.panel.start()
    logs = [v for k, v in list(app.panel.q.queue) if k == "log"]
    assert any("elige una" in v for v in logs)
    assert app.panel.bot is None and app.panel.mode != "running"


def test_start_is_refused_when_the_chosen_window_is_gone(app, monkeypatch):
    calibrate_panel(app.panel)
    app.panel.cfg.window_title = "Clash of Clans - Se fue"        # the fixture's finder raises WindowNotFound
    app.panel.start()
    logs = [v for k, v in list(app.panel.q.queue) if k == "log"]
    assert any("no game" in v for v in logs)
    assert app.panel.bot is None and app.panel.mode != "running"


def test_the_bot_of_a_tab_writes_its_debug_captures_in_its_own_folder(app, monkeypatch):
    app.add_account()
    p2 = app.panels[1]
    calibrate_panel(p2)
    seen = {}

    class FakeGame:
        def __init__(self, win, cfg, rec, stop, tpl_dir, debug_dir=None):
            seen["debug_dir"] = debug_dir

    class FakeBot:
        attacks_done = 0

        def __init__(self, *a, **k):
            pass

        def run_once(self):
            return True

        def run(self):
            return None

    class SyncThread:
        def __init__(self, target, daemon=True):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(gui.game, "RealGame", FakeGame)
    monkeypatch.setattr(gui.bot, "Bot", FakeBot)
    monkeypatch.setattr(gui.threading, "Thread", SyncThread)
    monkeypatch.setattr(gui.preflight, "check", lambda *a, **k: None)
    monkeypatch.setattr(p2, "_find_window", lambda: GameWindow(77, 1296, 729))
    p2.dry.set(True)
    p2.start()
    assert seen["debug_dir"] == gui.DATA / "debug" / "2"


def test_a_recording_keeps_its_exclusivity_when_another_job_of_the_tab_ends(app, monkeypatch):
    """'Leer ahora' finishing while a deployment is being recorded must not free the other tabs."""
    app.add_account()
    p1, p2 = app.panels
    assert app.try_exclusive(p1) is True
    p1.recorder = object()                                  # recording in progress
    p1.q.put(("done", None))
    p1._poll()
    assert app.exclusive is p1
    assert app.try_exclusive(p2) is False
    p1.recorder = None
    p1.q.put(("done", None))
    p1._poll()
    assert app.exclusive is None


def test_a_recorder_that_fails_to_start_does_not_leave_the_tabs_blocked(app, monkeypatch):
    calibrate_panel(app.panel)
    monkeypatch.setattr(app.panel, "_find_window", lambda: GameWindow(5, 1296, 729))
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: "nuevo")

    def boom(win, name):
        raise RuntimeError("no mouse hook")
    monkeypatch.setattr(gui.recorder.Recorder, "for_window", staticmethod(boom))
    app.panel.toggle_record()
    assert app.exclusive is None and app.panel.recorder is None
    logs = [v for k, v in list(app.panel.q.queue) if k == "log"]
    assert any("No pude empezar a grabar" in v for v in logs)


def test_claim_and_release_are_safe_from_several_threads(app):
    import threading
    app.add_account()
    p1, p2 = app.panels
    results = []

    def claim(panel):
        results.append(app.claim_window(panel, 99))
    threads = [threading.Thread(target=claim, args=(p,)) for p in (p1, p2) * 20]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == len(results) - results.count(False)
    owner = app._owned[99]
    winners = {p for p in (p1, p2) if app.window_in_use_by_other(p, 99) is False}
    assert winners == {owner}                              # exactly one tab owns it


def _size(app):
    return tuple(int(v) for v in app.root.geometry().split("+")[0].split("x"))


def _short_window(app):
    """A window too short for the cards: they scroll, the log and the bottom row stay."""
    app.root.geometry(f"{gui.MIN_SIZE[0]}x{gui.MIN_SIZE[1]}")
    app.root.update()
    app.root.update()                              # the layout pass runs when idle, after the <Configure>


def test_the_window_is_never_taller_than_the_screen_and_keeps_its_add_button(app, monkeypatch):
    """On a 816 px high screen the old window (about 1080 px) hid '+ Añadir cuenta' below the screen."""
    monkeypatch.setattr(app.root, "winfo_screenheight", lambda: 700)
    app._initial_size()
    app.root.update()
    assert _size(app)[1] <= 700 - gui.SCREEN_MARGIN
    root_bottom = app.root.winfo_rooty() + app.root.winfo_height()
    assert app.btn_add.winfo_ismapped()
    assert app.btn_add.winfo_rooty() + app.btn_add.winfo_height() <= root_bottom + 2      # inside the window


def test_the_window_can_be_resized_both_ways_down_to_a_minimum(app):
    assert app.root.resizable() == (True, True)
    assert app.root.minsize() == gui.MIN_SIZE


def test_a_state_change_does_not_undo_the_size_the_user_chose(app):
    """The old window forced its geometry on every state change, so it snapped back while the bot ran."""
    panel = app.panel
    calibrate_panel(panel)
    app.root.geometry("700x640")
    app.root.update()
    for mode, phase in (("running", "search"), ("running", "wait_builder"), ("stopping", None), ("idle", None)):
        panel.mode, panel.phase = mode, phase
        panel._apply_mode(True)
        app.root.update()
        assert _size(app) == (700, 640)
    panel.cfg.deployment = "ninguno"                # back to the setup screen
    panel.refresh_state()
    app.root.update()
    assert panel.mode == "setup" and _size(app) == (700, 640)


def test_content_taller_than_the_window_is_reachable_by_scrolling(app):
    panel = app.panel
    calibrate_panel(panel)
    _short_window(app)
    assert panel.content.winfo_reqheight() > panel.canvas.winfo_height()                  # it does not fit
    region = [float(v) for v in str(panel.canvas.cget("scrollregion")).split()]
    assert region[3] >= panel.content.winfo_reqheight() - 1                               # but all of it scrolls
    panel.canvas.yview_moveto(1.0)
    app.root.update()
    assert panel.canvas.yview()[1] == pytest.approx(1.0)                                   # the bottom is reachable


class _Wheel:
    def __init__(self, widget, delta):
        self.widget, self.delta = widget, delta


def test_the_wheel_scrolls_the_panel_but_not_over_the_log_or_a_dropdown(app):
    panel = app.panel
    calibrate_panel(panel)
    _short_window(app)
    start = panel.canvas.yview()[0]
    app._on_wheel(_Wheel(panel.content, -120))                      # wheel down over the page
    app.root.update()
    assert panel.canvas.yview()[0] > start
    here = panel.canvas.yview()[0]
    app._on_wheel(_Wheel(panel.logbox, -120))                        # over the log: the log takes it
    app._on_wheel(_Wheel(panel.mode_combo, -120))                    # over a dropdown: the dropdown takes it
    app.root.update()
    assert panel.canvas.yview()[0] == here
    app._on_wheel(_Wheel(panel.content, 1))                          # a gentle (touchpad) tick still scrolls
    app.root.update()
    assert panel.canvas.yview()[0] < here


def test_a_wheel_event_from_nowhere_is_ignored(app):
    app._on_wheel(_Wheel("not a widget", -120))                      # must not raise


def test_a_big_screen_gets_the_default_size(app, monkeypatch):
    monkeypatch.setattr(app.root, "winfo_screenheight", lambda: 5000)
    monkeypatch.setattr(app.root, "winfo_screenwidth", lambda: 5000)
    app._initial_size()
    app.root.update()
    assert _size(app) == gui.DEFAULT_SIZE


def _only_the_state_card(panel):
    """A panel whose cards are short, so that 'the window has room for them' can be tested on any screen."""
    for card in (panel.rules, panel.reading, panel.prep):
        card.grid_remove()
    panel.update_idletasks()
    panel._relayout()


def test_the_cards_do_not_scroll_when_the_window_has_room_for_them(app):
    """With room for everything there is no page scrollbar and the wheel has nothing to move."""
    panel = app.panel
    calibrate_panel(panel)
    _only_the_state_card(panel)
    app.root.geometry("1100x800")
    for _ in range(4):
        app.root.update()
    assert panel.content.winfo_reqheight() <= panel.canvas.winfo_height()
    assert not panel.vbar.winfo_ismapped()
    app._on_wheel(_Wheel(panel.content, -120))
    app.root.update()
    assert panel.canvas.yview()[0] == 0.0


# ── the log sits under the cards on a draggable divider ─────────────────────────

def _panel_at(app, geometry):
    app.root.geometry(geometry)
    for _ in range(4):
        app.root.update()
    return app.panel


def test_the_divider_gives_the_log_the_height_the_cards_do_not_need(app):
    """When the cards fit the log takes all the rest, so a big window shows more log, not blank space."""
    panel = app.panel
    _only_the_state_card(panel)
    _panel_at(app, "1100x1000")
    assert panel.content.winfo_reqheight() <= panel.canvas.winfo_height() + 6
    assert not panel.vbar.winfo_ismapped()
    assert panel.log_pane.winfo_height() > panel.log_pane.winfo_reqheight() + 60        # it grew into the spare room


def test_a_short_window_keeps_the_log_at_its_size_and_the_cards_scroll(app):
    panel = _panel_at(app, "900x640")
    assert panel.log_pane.winfo_height() >= panel.log_pane.winfo_reqheight() - 6        # the log did not shrink away
    assert panel.canvas.winfo_height() < panel.content.winfo_reqheight()
    assert panel.vbar.winfo_ismapped()


def test_dragging_the_divider_changes_the_split_and_a_resize_keeps_it(app):
    panel = _panel_at(app, "900x700")
    before = panel.paned.sash_coord(0)[1]
    panel.paned.sash_place(0, 0, before - 60)
    panel.paned.event_generate("<ButtonRelease-1>")          # what letting go of the divider sends
    app.root.update()
    assert panel.paned.sash_coord(0)[1] == before - 60
    log_height = panel.log_pane.winfo_height()
    app.root.geometry("900x740")
    for _ in range(3):
        app.root.update()
    assert panel.log_pane.winfo_height() == log_height           # the 40 px went to the cards, the user's split stayed


# ── the layout follows the width ────────────────────────────────────────────────

def test_the_cards_go_in_two_columns_when_wide_and_in_one_when_narrow(app):
    panel = app.panel
    calibrate_panel(panel)
    _panel_at(app, "1100x900")
    assert panel.layout == "wide"
    assert panel.rules.grid_info()["column"] == 1                       # rules beside the state card
    assert panel.state.grid_info()["column"] == 0
    _panel_at(app, "640x900")
    assert panel.layout == "narrow"
    assert panel.rules.grid_info()["column"] == 0                       # everything stacked
    assert panel.rules.grid_info()["row"] > panel.reading.grid_info()["row"] > panel.state.grid_info()["row"]
    _panel_at(app, "1100x900")
    assert panel.layout == "wide" and panel.rules.grid_info()["column"] == 1      # and back, nothing stuck


def test_the_reading_tiles_share_one_row_or_split_two_by_two(app):
    panel = app.panel
    panel._grid_tiles(4)
    assert {panel.tiles_grid.grid_slaves()[i].grid_info()["row"] for i in range(4)} == {0}
    panel._grid_tiles(2)
    assert sorted(w.grid_info()["row"] for w in panel.tiles_grid.grid_slaves()) == [0, 0, 1, 1]


def test_the_recoveries_counter_is_hidden_until_there_is_one(app):
    panel = app.panel
    calibrate_panel(panel)                      # the state card is only on screen once the setup is done
    app.root.update()
    assert not panel.recov_box.winfo_ismapped()
    panel._show_recoveries(3)
    app.root.update()
    assert panel.recov_box.winfo_ismapped() and panel.recov_counter.cget("text") == "3"
    panel._show_recoveries(0)
    app.root.update()
    assert not panel.recov_box.winfo_ismapped()


def test_the_panel_polls_the_recoveries_of_the_running_bot(app):
    panel = app.panel
    panel.bot = type("B", (), {"attacks_done": 4, "recoveries_done": 2})()
    panel._poll()
    app.root.update()
    assert panel.counter.cget("text") == "4" and panel.recov_counter.cget("text") == "2"


# ── the options follow the mode; one failing pass must not stop the window ─────

def _pick_mode(panel, app, label):
    panel.mode_combo.set(label)
    panel.mode_combo.event_generate("<<ComboboxSelected>>")
    for _ in range(3):
        app.root.update()


def test_the_heroes_option_and_the_help_line_follow_the_mode(app):
    panel = app.panel
    calibrate_panel(panel)
    app.root.geometry("1000x900")
    app.root.update()
    assert not panel.hero_chk.winfo_ismapped()                          # the default mode ignores heroes
    for key, label in gui.vm.MODES:
        _pick_mode(panel, app, label)
        assert panel.mode_help.cget("text") == gui.vm.mode_help(key), key
        assert bool(panel.hero_chk.winfo_ismapped()) == (key == "busy"), key
    _pick_mode(panel, app, gui.vm.mode_label("none"))
    assert not panel.hero_chk.winfo_ismapped()                          # and it goes away again


def test_a_failing_poll_still_arms_the_next_one(app):
    """Review finding: an exception in one pass of the 50 ms poll skipped the re-arm and froze the window for good."""
    panel = app.panel
    panel.bot = type("B", (), {"attacks_done": 1, "recoveries_done": 1})()

    def boom(_n):
        raise RuntimeError("one bad pass")

    panel._show_recoveries = boom
    panel.root.after_cancel(panel._after_id)
    panel._after_id = None
    with pytest.raises(RuntimeError):
        panel._poll()
    assert panel._after_id is not None                                  # the next pass is scheduled anyway
    panel.root.after_cancel(panel._after_id)
