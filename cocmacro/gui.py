"""Single-window tkinter app: start/stop the bot, record deployments, calibrate."""
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from cocmacro import (accounts, __version__, bot, calibrate, config, defaults, frames, game, hotkeys, ocr, overlay, paths,
                      preflight, recorder, theme, updater, viewmodel as vm, winctl)
from cocmacro.config import format_mmss, parse_mmss
from cocmacro.theme import BG, BORDER, CARD, DIM, GOLD, MUTED, PINK, TEXT

DATA = paths.data_dir()
CFG_PATH, TPL_DIR, REC_DIR = DATA / "config.json", DATA / "templates", DATA / "recordings"
WARNING = ("Supercell prohibe automatizar ataques con macros.\n"
           "Usar esta app puede suponer el BAN de tu cuenta. Lo haces bajo tu responsabilidad.\n\n"
           "F8 = parar todo, F9 = terminar de grabar un despliegue.")
WIDTH = 900
REFRESH_EVERY = 40          # polls (about 2 s) between status refreshes
SCREEN_MARGIN = 110         # title bar + taskbar: the window is never taller than the screen minus this
MIN_HEIGHT = 420


class AccountPanel(tk.Frame):
    """All per-account state and UI: one panel == one account / one Clash window."""

    def __init__(self, parent, app, cfg_path: Path, index: int = 1):
        super().__init__(parent, bg=BG)
        self.app = app
        self.root = app.root
        self.cfg_path = cfg_path
        self.index = index
        self.cfg = config.load(self.cfg_path)
        if defaults.apply(self.cfg, TPL_DIR):
            DATA.mkdir(parents=True, exist_ok=True)
            config.save(self.cfg, self.cfg_path)
        self.q: queue.Queue = queue.Queue()
        self.stop_ev = threading.Event()
        self.bot: bot.Bot | None = None
        self.recorder: recorder.Recorder | None = None
        self.busy = False
        self.mode, self.phase, self.missing = "idle", None, []
        self.overlay: overlay.Overlay | None = None
        self._ticks = 0
        self._make_scroll_area()
        self._build()
        self.refresh_recordings()
        self.refresh_state()
        self._after_id = self.root.after(50, self._poll)

    # -- layout --------------------------------------------------------
    def _make_scroll_area(self):
        """The whole panel scrolls: on a screen shorter than the panel (the window is capped to the screen) the
        parts below the fold stay reachable instead of falling off the screen."""
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                  style="Dark.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
        self._content_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._content_id, width=e.width))

    def scroll_by(self, units: int):
        """Scroll the panel (the App routes the mouse wheel here); nothing to do when it all fits."""
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(units, "units")

    def _build(self):
        pad = {"padx": 24}
        self._selector_row().pack(fill="x", pady=(16, 0), **pad)
        self._header().pack(fill="x", pady=(12, 0), **pad)
        body = tk.Frame(self.content, bg=BG)
        body.pack(fill="x", pady=(16, 0), **pad)
        body.columnconfigure(0, weight=1)
        self.left = tk.Frame(body, bg=BG)
        self.left.grid(row=0, column=0, sticky="nsew")
        self._state_card(self.left)
        self._setup_card(self.left)
        self._reading_card(self.left)
        self._rules_card(body).grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        self.prep = self._prep_card(self.content)
        self.prep.pack(fill="x", pady=(16, 0), **pad)
        self.log_card = self._log_card(self.content)
        self.log_card.pack(fill="both", expand=True, pady=(16, 0), **pad)
        self._footer(self.content).pack(fill="x", pady=(10, 14), **pad)

    def _selector_row(self) -> tk.Frame:
        row = tk.Frame(self.content, bg=BG)
        theme.label(row, "Ventana", 10, True, bg=BG).pack(side="left", padx=(0, 8))
        self.win_combo = ttk.Combobox(row, state="readonly", width=36, style="Dark.TCombobox",
                                      font=theme.font(10))
        self.win_combo.pack(side="left", padx=(0, 8))
        self.win_combo.bind("<<ComboboxSelected>>", self._on_window_selected)
        self.btn_win_refresh = theme.button(row, "Actualizar", self.refresh_windows, "secondary", 9, padx=10, pady=2)
        self.btn_win_refresh.pack(side="left")
        return row

    def _header(self) -> tk.Frame:
        f = tk.Frame(self.content, bg=BG)
        title = tk.Frame(f, bg=BG)
        title.pack(side="left")
        theme.label(title, "CoC Macro", 17, True, bg=BG).pack(side="left")
        theme.label(title, f"v{__version__}", 9, fg=MUTED, bg=BG).pack(side="left", padx=(10, 0), pady=(6, 0))
        self.chip_frames = []
        for _ in range(3):
            c = tk.Frame(f, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
            c.pack(side="right", padx=(8, 0))
            dot = tk.Label(c, text="●", font=theme.font(9), bg=CARD, fg=DIM)
            dot.pack(side="left", padx=(8, 4), pady=4)
            txt = tk.Label(c, text="", font=theme.font(9), bg=CARD, fg=TEXT)
            txt.pack(side="left", padx=(0, 10), pady=4)
            self.chip_frames.append((dot, txt))
        self.chip_frames.reverse()      # packed right-to-left: keep game, calibration, deployment order
        return f

    def _state_card(self, parent):
        self.state = theme.card(parent)
        inner = tk.Frame(self.state, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)
        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x")
        left = tk.Frame(top, bg=CARD)
        left.pack(side="left")
        theme.caption(left, "Estado").pack(anchor="w")
        self.title_lbl = theme.label(left, "", 18, True)
        self.title_lbl.pack(anchor="w")
        right = tk.Frame(top, bg=CARD)
        right.pack(side="right")
        theme.label(right, "Ataques en esta sesión", 9, fg=MUTED, anchor="e").pack(anchor="e")
        self.counter = theme.label(right, "0", 18, True, anchor="e")
        self.counter.pack(anchor="e")
        self.stepper = tk.Frame(inner, bg=CARD)
        self.step_cells = []
        for i, (_, label) in enumerate(vm.PHASES):
            cell = tk.Frame(self.stepper, bg=BG)
            cell.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            self.stepper.columnconfigure(i, weight=1)
            lbl = tk.Label(cell, text=label, font=theme.font(9), bg=BG, fg=MUTED, pady=5)
            lbl.pack(fill="x")
            bar = tk.Frame(cell, bg=BORDER, height=3)
            bar.pack(fill="x")
            self.step_cells.append((lbl, bar))
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(14, 0))
        self.btn_start = theme.button(row, "▶  Empezar", self.start, "primary", 12, width=14)
        self.btn_start.pack(side="left")
        self.btn_stop = theme.button(row, "■  Parar (F8)", self.stop, "danger", 12, width=14)
        self.btn_stop.pack(side="left", padx=(12, 0))
        self.dry = tk.BooleanVar()
        self.dry_chk = tk.Checkbutton(inner, text="Solo simular (no pulsa nada)", variable=self.dry, bg=CARD, fg=TEXT,
                                      activebackground=CARD, activeforeground=TEXT, selectcolor=BG,
                                      font=theme.font(9), highlightthickness=0, bd=0)
        self.dry_chk.pack(anchor="w", pady=(10, 0))
        self.hint_lbl = theme.label(inner, "", 9, fg=MUTED, wraplength=470, justify="left")
        self.hint_lbl.pack(anchor="w", pady=(10, 0))

    def _setup_card(self, parent):
        self.setup = theme.card(parent, GOLD)
        inner = tk.Frame(self.setup, bg=CARD)
        inner.pack(fill="x", padx=18, pady=16)
        theme.caption(inner, "Estado").pack(anchor="w")
        self.setup_title = theme.label(inner, "", 18, True)
        self.setup_title.pack(anchor="w")
        theme.label(inner, "Solo hace falta una vez por cuenta y por tamaño de ventana. Haz un ataque normal y "
                    "sigue las instrucciones que aparecen sobre el juego.", 9, fg=MUTED, wraplength=470,
                    justify="left").pack(anchor="w", pady=(4, 10))
        self.setup_rows = []
        actions = [("Calibrar", self.calibrate), ("Grabar despliegue", self.toggle_record)]
        for i in range(2):
            row = tk.Frame(inner, bg=BG, highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x", pady=4)
            num = tk.Label(row, text=str(i + 1), font=theme.font(10, True), bg=BORDER, fg=MUTED, width=3, pady=3)
            num.pack(side="left", padx=10, pady=10)
            text = tk.Frame(row, bg=BG)
            text.pack(side="left", fill="x", expand=True)
            t = theme.label(text, "", 10, True, bg=BG)
            t.pack(anchor="w")
            h = theme.label(text, "", 8, fg=MUTED, bg=BG, wraplength=250, justify="left")
            h.pack(anchor="w")
            b = theme.button(row, actions[i][0], actions[i][1], "gold", 10)
            b.pack(side="right", padx=10)
            self.setup_rows.append((row, num, t, h, b))
        go = tk.Frame(inner, bg=CARD)
        go.pack(fill="x", pady=(10, 0))
        self.btn_start_setup = theme.button(go, "▶  Empezar", lambda: None, "primary", 12, width=14)
        self.btn_start_setup.pack(side="left")
        theme.set_enabled(self.btn_start_setup, False, "primary")
        self.why_lbl = theme.label(go, "Completa los pasos para poder empezar.", 9, fg=GOLD)
        self.why_lbl.pack(side="left", padx=(12, 0))

    def _reading_card(self, parent):
        self.reading = theme.card(parent)
        inner = tk.Frame(self.reading, bg=CARD)
        inner.pack(fill="x", padx=18, pady=14)
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x")
        theme.caption(head, "Lo que ve el bot").pack(side="left")
        theme.button(head, "Leer ahora", self.read_now, "ghost", 9, padx=10, pady=2).pack(side="right")
        grid = tk.Frame(inner, bg=CARD)
        grid.pack(fill="x", pady=(10, 0))
        self.tiles = {}
        for i, (key, name, colour) in enumerate((("gold", "Oro", GOLD), ("elixir", "Elixir", PINK),
                                                 ("damage", "Daño", TEXT), ("time", "Reloj", TEXT))):
            grid.columnconfigure(i, weight=1, uniform="tile")
            t = tk.Frame(grid, bg=BG, highlightbackground=BORDER, highlightthickness=1)
            t.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            theme.label(t, name, 9, fg=MUTED, bg=BG).pack(anchor="w", padx=8, pady=(8, 0))
            val = theme.label(t, "—", 11, True, fg=colour, bg=BG)
            val.pack(anchor="w", padx=8)
            bar = tk.Canvas(t, height=5, bg=BORDER, highlightthickness=0)
            if key == "damage":
                bar.pack(fill="x", padx=8, pady=(4, 0))
            hint = theme.label(t, "", 8, fg=MUTED, bg=BG, wraplength=100, justify="left")
            hint.pack(anchor="w", padx=8, pady=(2, 8))
            self.tiles[key] = (val, hint, bar)

    def _rules_card(self, parent) -> tk.Frame:
        self.rules = theme.card(parent)
        inner = tk.Frame(self.rules, bg=CARD)
        inner.pack(fill="both", expand=True, padx=18, pady=16)
        self.rules_caption = theme.caption(inner, "Reglas")
        self.rules_caption.pack(anchor="w")
        self.gold, self.elixir, self.pct = (tk.StringVar(value=str(v)) for v in
                                            (self.cfg.gold_min, self.cfg.elixir_min, self.cfg.surrender_pct))
        self.time_var = tk.StringVar(value=format_mmss(self.cfg.surrender_time_s))
        theme.label(inner, "Atacar si hay más de", 10, True).pack(anchor="w", pady=(10, 4))
        pair = tk.Frame(inner, bg=CARD)
        pair.pack(fill="x")
        self.rule_entries = []
        for i, (name, var) in enumerate((("Oro", self.gold), ("Elixir", self.elixir))):
            col = tk.Frame(pair, bg=CARD)
            col.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            pair.columnconfigure(i, weight=1)
            theme.label(col, name, 8, fg=MUTED).pack(anchor="w")
            e = theme.entry(col, var, 9)
            e.pack(fill="x", ipady=4)
            self.rule_entries.append(e)
        theme.label(inner, "Rendirse cuando…", 10, True).pack(anchor="w", pady=(14, 4))
        r1 = tk.Frame(inner, bg=CARD)
        r1.pack(fill="x", pady=2)
        theme.label(r1, "el daño supera", 9).pack(side="left")
        e = theme.entry(r1, self.pct, 5, "right")
        e.pack(side="left", padx=(8, 4), ipady=3)
        self.rule_entries.append(e)
        theme.label(r1, "%", 9).pack(side="left")
        r2 = tk.Frame(inner, bg=CARD)
        r2.pack(fill="x", pady=2)
        theme.label(r2, "o quedan menos de", 9).pack(side="left")
        e = theme.entry(r2, self.time_var, 6, "right")
        e.pack(side="left", padx=(8, 0), ipady=3)
        self.rule_entries.append(e)
        theme.label(inner, "0:00 desactiva la regla del reloj.", 8, fg=MUTED).pack(anchor="w", pady=(2, 0))
        theme.label(inner, "Entre ataques", 10, True).pack(anchor="w", pady=(14, 4))
        self.mode_combo = ttk.Combobox(inner, state="readonly", width=22, style="Dark.TCombobox",
                                       font=theme.font(10), values=[v for _, v in vm.MODES])
        self.mode_combo.set(vm.mode_label(self.cfg.mode))
        self.mode_combo.pack(fill="x", ipady=3)
        self.full_var = tk.BooleanVar(value=self.cfg.stop_when_full)
        self.full_chk = tk.Checkbutton(inner, text="Parar si los depositos estan llenos", variable=self.full_var,
                                       bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=TEXT,
                                       selectcolor=BG, font=theme.font(9), highlightthickness=0, bd=0)
        self.full_chk.pack(anchor="w", pady=(6, 0))
        self.hero_var = tk.BooleanVar(value=self.cfg.prioritize_heroes)
        self.hero_chk = tk.Checkbutton(inner, text="Heroes primero (modo Mejorar lo mas barato)", variable=self.hero_var,
                                       bg=CARD, fg=TEXT, activebackground=CARD, activeforeground=TEXT,
                                       selectcolor=BG, font=theme.font(9), highlightthickness=0, bd=0)
        self.hero_chk.pack(anchor="w", pady=(2, 0))
        theme.label(inner, "Despliegue", 10, True).pack(anchor="w", pady=(14, 4))
        self.combo = ttk.Combobox(inner, state="readonly", width=22, style="Dark.TCombobox",
                                  font=theme.font(10))
        self.combo.pack(fill="x", ipady=3)
        return self.rules

    def _prep_card(self, parent) -> tk.Frame:
        c = theme.card(parent)
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="x", padx=18, pady=12)
        head = tk.Frame(inner, bg=CARD)
        head.pack(fill="x")
        theme.caption(head, "Preparación").pack(side="left")
        theme.label(head, "Si cambias de cuenta o de tamaño de ventana, vuelve a calibrar.", 8,
                    fg=MUTED, anchor="e").pack(side="right")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(8, 0))
        self.prep_btns = []
        for i, (text, cmd) in enumerate((("Calibrar botones y zonas", self.calibrate),
                                         ("Calibrar reloj", self.calibrate_timer),
                                         ("Grabar despliegue nuevo", self.toggle_record))):
            row.columnconfigure(i, weight=1, uniform="prep")
            b = theme.button(row, text, cmd, "secondary", 9, pady=10)
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.prep_btns.append(b)
        self.btn_cal, self.btn_cal_timer, self.btn_rec = self.prep_btns
        return c

    def _log_card(self, parent) -> tk.Frame:
        c = theme.card(parent)
        inner = tk.Frame(c, bg=CARD)
        inner.pack(fill="both", expand=True, padx=18, pady=12)
        theme.caption(inner, "Registro").pack(anchor="w")
        wrap = tk.Frame(inner, bg=CARD)
        wrap.pack(fill="both", expand=True, pady=(6, 0))
        self.logbox = tk.Text(wrap, width=10, height=4, bg=CARD, fg="#c9d1de", font=("Consolas", 10), relief="flat", bd=0,
                              highlightthickness=0, wrap="word", state="disabled", padx=0, pady=0)
        sb = ttk.Scrollbar(wrap, command=self.logbox.yview, style="Dark.Vertical.TScrollbar")
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)
        for tag, colour in (("ok", theme.OK), ("bad", theme.BAD), ("warn", GOLD)):
            self.logbox.tag_configure(tag, foreground=colour)
        return c

    def _footer(self, parent) -> tk.Frame:
        f = tk.Frame(parent, bg=BG)
        theme.label(f, "F8 para todo · F9 termina una grabación", 8, fg=MUTED, bg=BG).pack(side="left")
        self.btn_close = theme.button(f, "Cerrar esta cuenta", lambda: self.app.close_account(self), "danger", 8, padx=10, pady=2)
        if self.index != 1:
            self.btn_close.pack(side="left", padx=(14, 0))
        else:
            theme.set_enabled(self.btn_close, False, "danger")
        theme.button(f, "Buscar actualizaciones", lambda: threading.Thread(
            target=self.app.check_update, args=(True,), daemon=True).start(), "secondary", 8, padx=10, pady=2
        ).pack(side="right")
        self.auto_upd = tk.BooleanVar(value=self.cfg.auto_check_updates)
        tk.Checkbutton(f, text="Buscar actualizaciones al abrir", variable=self.auto_upd, bg=BG, fg=MUTED,
                       activebackground=BG, activeforeground=MUTED, selectcolor=BG, font=theme.font(8),
                       highlightthickness=0, bd=0).pack(side="right", padx=(0, 14))
        return f

    def _find_window(self) -> winctl.GameWindow:
        return winctl.find_game_window(self.cfg.window_title)

    def refresh_windows(self):
        windows = winctl.list_game_windows()
        items = []
        for w in windows:
            in_use = self.app.window_in_use_by_other(self, w.hwnd)
            items.append(f"{w.title} (en uso)" if in_use else w.title)
        self.win_combo["values"] = items
        target = self.cfg.window_title
        match = ""
        for item in items:
            clean = item[:-len(" (en uso)")] if item.endswith(" (en uso)") else item
            if clean == target:
                match = item
                break
        self.win_combo.set(match)

    def _on_window_selected(self, event=None):
        raw = self.win_combo.get()
        is_in_use = raw.endswith(" (en uso)")
        title = raw[:-len(" (en uso)")] if is_in_use else raw
        if is_in_use:
            self.log("La ventana ya la usa otra cuenta")
            self.refresh_windows()
            return
        windows = winctl.list_game_windows()
        for w in windows:
            if w.title == title and self.app.window_in_use_by_other(self, w.hwnd):
                self.log("La ventana ya la usa otra cuenta")
                self.refresh_windows()
                return
        self.cfg.window_title = title
        self.cfg.account_name = accounts.account_name_from_title(title, f"Cuenta {self.index}")
        DATA.mkdir(parents=True, exist_ok=True)
        config.save(self.cfg, self.cfg_path)
        self.app.update_tab_title(self)
        self.refresh_state()

    # -- state ---------------------------------------------------------
    def refresh_state(self):
        """Recompute chips, mode and which cards are visible from the config and the game window."""
        self.refresh_windows()
        self.missing = preflight.calibration_missing(self.cfg, TPL_DIR)
        names = recorder.list_recordings(REC_DIR)
        dep_ok = self.cfg.deployment in names
        try:
            w = self._find_window()
            game_size = (w.client_w, w.client_h)
        except winctl.WindowNotFound:
            game_size = None
        for (dot, txt), (level, text) in zip(self.chip_frames,
                                             vm.chips(game_size, self.missing, self.cfg.deployment, dep_ok)):
            dot.configure(fg=theme.DOT[level])
            txt.configure(text=text)
        if self.mode != "running" and self.mode != "stopping":
            self.mode = "setup" if (self.missing or not dep_ok) else "idle"
        self._apply_mode(dep_ok)

    def _apply_mode(self, dep_ok: bool):
        running = self.mode in ("running", "stopping")
        setup = self.mode == "setup"
        blocked_by_exclusive = (self.app.exclusive is not None and self.app.exclusive is not self)
        for w in (self.state, self.setup, self.reading):
            w.pack_forget()
        if setup:
            self.setup.pack(fill="x")
            steps = vm.setup_steps(self.missing, dep_ok)
            self.setup_title.configure(text=vm.state_title("setup", None, sum(not s["done"] for s in steps)))
            for (row, num, t, h, b), s in zip(self.setup_rows, steps):
                active = s["active"] and not blocked_by_exclusive
                num.configure(text="✓" if s["done"] else str(s["n"]), bg=GOLD if active else (theme.OK if s["done"] else BORDER),
                              fg=BG if (active or s["done"]) else MUTED)
                t.configure(text=s["title"], fg=TEXT if (active or s["done"]) else MUTED)
                h.configure(text=s["help"])
                row.configure(highlightbackground=GOLD if active else BORDER)
                theme.set_enabled(b, active, "gold")
        else:
            self.state.pack(fill="x")
            self.reading.pack(fill="x", pady=(16, 0))
            self.state.configure(highlightbackground=GOLD if running else BORDER, highlightcolor=GOLD if running else BORDER)
            self.title_lbl.configure(text=vm.state_title("stopping" if self.mode == "stopping" else self.mode,
                                                         self.phase))
            if running:
                self.stepper.pack(fill="x", pady=(12, 0), before=self.btn_start.master)
                self._paint_stepper()
            else:
                self.stepper.pack_forget()
            theme.set_enabled(self.btn_start, (not running) and (not blocked_by_exclusive), "primary")
            theme.set_enabled(self.btn_stop, running, "danger")
            self.dry_chk.configure(state="disabled" if running else "normal")
            self.hint_lbl.configure(text="Empieza desde tu pueblo: Batalla, Buscar batalla, Atacar. Si la aldea no cumple "
                                    "las reglas pulsa Siguiente hasta encontrar una." if not running else
                                    "Pulsa F8 o Parar para detener el bucle.")
        if setup or running:
            self.prep.pack_forget()
        elif not self.prep.winfo_ismapped():
            self.prep.pack(fill="x", pady=(16, 0), padx=24, before=self.log_card)
        self._fit()
        locked = running
        for e in self.rule_entries:
            e.configure(state="disabled" if locked else "normal")
        self.combo.configure(state="disabled" if locked else "readonly")
        self.mode_combo.configure(state="disabled" if locked else "readonly")
        self.win_combo.configure(state="disabled" if locked else "readonly")
        theme.set_enabled(self.btn_win_refresh, not locked, "secondary")
        self.full_chk.configure(state="disabled" if locked else "normal")
        self.hero_chk.configure(state="disabled" if locked else "normal")
        self.rules_caption.configure(text="REGLAS (BLOQUEADAS MIENTRAS ATACA)" if locked else "REGLAS")
        theme.set_enabled(self.btn_cal, not blocked_by_exclusive, "secondary")
        theme.set_enabled(self.btn_cal_timer, not blocked_by_exclusive, "secondary")
        theme.set_enabled(self.btn_rec, not blocked_by_exclusive, "secondary")

    def _fit(self):
        """Width is fixed; the height follows what the current mode shows."""
        self.root.update_idletasks()
        self.canvas.configure(height=self.content.winfo_reqheight())     # natural size; the cap below scrolls
        self.root.update_idletasks()
        height = min(self.root.winfo_reqheight(), max(MIN_HEIGHT, self.root.winfo_screenheight() - SCREEN_MARGIN))
        self.root.geometry(f"{WIDTH}x{height}")

    def _paint_stepper(self):
        for (lbl, bar), (_, state) in zip(self.step_cells, vm.phase_steps(self.phase)):
            colour = {"done": theme.OK, "current": GOLD, "todo": BORDER}[state]
            bar.configure(bg=colour)
            lbl.configure(fg={"done": MUTED, "current": GOLD, "todo": MUTED}[state],
                          font=theme.font(9, state == "current"))

    def _show_reading(self, r: dict):
        gold, elixir = r.get("gold"), r.get("elixir")
        for key, value, minimum in (("gold", gold, self.cfg.gold_min), ("elixir", elixir, self.cfg.elixir_min)):
            val, hint, _ = self.tiles[key]
            val.configure(text=vm.fmt_int(value))
            level, text = vm.loot_hint(value, minimum)
            hint.configure(text=text, fg=theme.HINT[level])
        pct, left = r.get("damage"), r.get("time_left")
        val, hint, bar = self.tiles["damage"]
        val.configure(text="—" if pct is None else f"{pct}%")
        hint.configure(text=f"se rinde sobre {self.cfg.surrender_pct}%" if self.cfg.surrender_pct else "")
        bar.update_idletasks()
        bar.delete("all")
        width = max(1, bar.winfo_width())
        bar.create_rectangle(0, 0, width * vm.damage_fraction(pct, self.cfg.surrender_pct), 5, fill=GOLD, width=0)
        val, hint, _ = self.tiles["time"]
        val.configure(text="—" if left is None else format_mmss(left))
        hint.configure(text=vm.time_hint(self.cfg))

    # -- helpers -------------------------------------------------------
    def log(self, msg: str):
        self.q.put(("log", msg))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    tag = ("ok" if val.startswith(("Atacando", "Hash correcto")) else
                           "bad" if val.startswith(("Error", "No se pudo", "Atencion", "Tiempo agotado")) else
                           "warn" if val.startswith(("Siguiente", "Sigo esperando", "Rindiendose")) else "")
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", val + "\n", tag)
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "stop":
                    self.stop()
                elif kind == "end_record":
                    if self.recorder:
                        self.toggle_record()
                elif kind == "done":
                    self.busy = False
                    if self.mode in ("running", "stopping"):
                        self.mode, self.phase = "idle", None
                    self.app.release_window(self)
                    if self.recorder is None:        # a recording keeps its exclusivity until it ends
                        self.app.release_exclusive(self)
                    self.refresh_state()
                elif kind == "refresh_all":
                    self.app._refresh_all()
                elif kind == "phase":
                    self.phase = val
                    self._apply_mode(self.cfg.deployment in recorder.list_recordings(REC_DIR))
                elif kind == "reading":
                    self._show_reading(val)
                elif kind == "update":
                    self.app.offer_update(*val)
                elif kind == "quit":
                    self.app.close()
                elif kind.startswith("ov_"):
                    self._overlay_event(kind, val)
        except queue.Empty:
            pass
        if self.bot:
            self.counter.configure(text=str(self.bot.attacks_done))
        self._ticks += 1
        if self._ticks % REFRESH_EVERY == 0:
            self.refresh_state()
        self._after_id = self.root.after(50, self._poll)

    def refresh_recordings(self):
        names = recorder.list_recordings(REC_DIR)
        self.combo["values"] = names
        if self.cfg.deployment in names:
            self.combo.set(self.cfg.deployment)
        elif names:
            self.combo.set(names[0])

    def _read_cfg(self) -> bool:
        try:
            self.cfg.gold_min, self.cfg.elixir_min = int(self.gold.get()), int(self.elixir.get())
            self.cfg.surrender_pct = int(self.pct.get())
        except ValueError:
            messagebox.showerror("CoC Macro", "Oro, elixir y % deben ser numeros enteros")
            return False
        try:
            self.cfg.surrender_time_s = parse_mmss(self.time_var.get())
        except ValueError as e:
            messagebox.showerror("CoC Macro", str(e))
            return False
        self.cfg.deployment = self.combo.get() or self.cfg.deployment
        self.cfg.mode = vm.mode_from_label(self.mode_combo.get())
        self.cfg.stop_when_full = self.full_var.get()
        self.cfg.prioritize_heroes = self.hero_var.get()
        self.cfg.auto_check_updates = self.auto_upd.get()
        DATA.mkdir(exist_ok=True)
        config.save(self.cfg, self.cfg_path)
        return True

    def _worker(self, fn):
        if self.busy:
            self.log("Ya hay una tarea en marcha")
            return
        self.busy = True
        self.stop_ev.clear()

        def run():
            try:
                fn()
            except Exception as e:  # show every failure in the log, never silently die
                self.log(f"Error: {e}")
            finally:
                self.q.put(("done", None))
        threading.Thread(target=run, daemon=True).start()

    # -- actions -------------------------------------------------------
    def start(self):
        if self.busy or not self._read_cfg():
            return
        if self.app.exclusive is not None and self.app.exclusive is not self:
            return
        dry = self.dry.get()
        err = preflight.check(self.cfg, TPL_DIR, REC_DIR, dry, find_window=self._find_window)
        if err:
            self.log(err)
            return
        try:
            self._find_window()
        except winctl.WindowNotFound as e:
            self.log(str(e))
            return
        self.mode, self.phase = "running", None
        self._show_reading({})
        self.refresh_state()

        def job():
            try:
                win = self._find_window()
            except winctl.WindowNotFound as e:
                self.log(str(e))
                return
            if not self.app.claim_window(self, win.hwnd):
                self.log("La ventana ya la usa otra cuenta")
                return
            self.q.put(("refresh_all", None))          # the other tabs show this window as (en uso)
            rec = None if dry else recorder.load_recording(self.cfg.deployment, REC_DIR)
            g = game.RealGame(win, self.cfg, rec, self.stop_ev, TPL_DIR,
                              debug_dir=accounts.debug_dir(DATA, self.cfg_path.name))
            self.bot = bot.Bot(g, self.cfg, self.log, self.stop_ev, dry_run=dry,
                               on_phase=lambda p: self.q.put(("phase", p)),
                               on_reading=lambda r: self.q.put(("reading", r)))
            self.log("Simulacion (no pulsa nada)" if dry else "Empezando bucle de ataques (F8 para parar)")
            if dry:
                self.bot.run_once()
            else:
                self.bot.run()
            self.log("Parado")
        self._worker(job)

    def stop(self):
        self.stop_ev.set()
        if self.mode == "running":
            self.mode = "stopping"
            self._apply_mode(self.cfg.deployment in recorder.list_recordings(REC_DIR))
        self.log("Parando...")

    def toggle_record(self):
        if self.recorder is None:
            if not self.app.try_exclusive(self):
                self.log("Para los demas bots antes de calibrar o grabar")
                return
            try:
                win = self._find_window()
            except winctl.WindowNotFound as e:
                self.app.release_exclusive(self)
                self.log(str(e))
                return
            name = simpledialog.askstring("Grabar despliegue", "Nombre del despliegue:", parent=self.root)
            if not name:
                self.app.release_exclusive(self)
                return
            try:
                self.recorder = recorder.Recorder.for_window(win, name.strip())
                self.recorder.start()
            except Exception as e:
                self.recorder = None
                self.app.release_exclusive(self)
                self.log(f"No pude empezar a grabar: {e}")
                return
            self.btn_rec.configure(text="Terminar grabación (F9)")
            self.setup_rows[1][4].configure(text="Terminar grabación (F9)")
            self.log(f"Grabando '{name}': haz tu despliegue en el juego y pulsa F9")
        else:
            rec = self.recorder.stop()
            self.recorder = None
            self.app.release_exclusive(self)
            self.btn_rec.configure(text="Grabar despliegue nuevo")
            self.setup_rows[1][4].configure(text="Grabar despliegue")
            if rec.events:
                recorder.save_recording(rec, REC_DIR)
                self.cfg.deployment = rec.name
                config.save(self.cfg, self.cfg_path)
                self.refresh_recordings()
                self.log(f"Guardado '{rec.name}' ({len(rec.events)} eventos)")
            else:
                self.log("Grabacion vacia: no se guardo")
            self.refresh_state()

    def calibrate(self):
        if not self.app.try_exclusive(self):
            self.log("Para los demas bots antes de calibrar o grabar")
            return
        steps = calibrate.STEPS

        def job():
            win = self._find_window()
            self.q.put(("ov_clear", None))
            for i, (name, kind, prompt) in enumerate(steps, 1):
                if self.stop_ev.is_set():
                    self.log("Calibracion cancelada")
                    self.q.put(("ov_hide", 0))
                    return
                self.log(f"[{name}] {prompt}")
                self._calibrate_step(win, name, kind, f"Paso {i} de {len(steps)}: {prompt}")
            self.q.put(("ov_banner", "Calibracion terminada: estas son las zonas guardadas"))
            self.log("Calibracion terminada")
            self.q.put(("ov_hide", 4000))
        self._worker(job)

    def calibrate_timer(self):
        if not self.app.try_exclusive(self):
            self.log("Para los demas bots antes de calibrar o grabar")
            return

        def job():
            win = self._find_window()
            prompt = "Entra en una batalla y arrastra un rectangulo sobre el reloj (ej. 2m 51s)"
            self.log(f"[timer] {prompt}")
            self._calibrate_step(win, "timer", "region", prompt)
            self.log("Reloj calibrado")
            self.q.put(("ov_hide", 2500))
        self._worker(job)

    def _calibrate_step(self, win, name: str, kind: str, banner: str):
        """One calibration step with on-screen feedback (overlay events go through the queue)."""
        guide = calibrate.suggested_region(name) if kind == "region" else None
        known = self.cfg.buttons.get(name) if kind == "button" else None
        avoid = guide or (known and (known[0] - 0.07, known[1] - 0.09, known[0] + 0.07, known[1] + 0.09))
        order = ("middle", "top", "bottom") if kind == "region" else ("top", "middle", "bottom")

        def say(text):
            self.q.put(("ov_banner", (text, avoid, order)))
        say(banner)
        self.q.put(("ov_guide", guide))
        self.cfg = calibrate.run_step(
            win, self.cfg, name, kind, TPL_DIR,
            on_rect=lambda r: self.q.put(("ov_rect", r)),
            on_click=lambda p: self.q.put(("ov_marker", (p, name))),
            on_invalid=lambda m: say(f"Atencion: {m}"))
        if kind == "region":
            self.q.put(("ov_guide", None))
            self.q.put(("ov_saved", (name, self.cfg.regions[name])))
        DATA.mkdir(exist_ok=True)
        config.save(self.cfg, self.cfg_path)

    def _overlay_event(self, kind: str, val):
        try:
            if self.overlay is None:
                self.overlay = overlay.Overlay(self.root, find_window=self._find_window)
            if kind == "ov_banner":
                self.overlay.banner(*val) if isinstance(val, tuple) else self.overlay.banner(val)
            elif kind == "ov_guide":
                self.overlay.guide(val)
            elif kind == "ov_rect":
                self.overlay.rect(val)
            elif kind == "ov_marker":
                self.overlay.marker(*val)
            elif kind == "ov_saved":
                self.overlay.saved_rect(*val)
            elif kind == "ov_clear":
                self.overlay.clear()
            elif kind == "ov_hide":
                self.root.after(int(val), self.overlay.hide)
        except Exception as e:  # the overlay is only feedback: never break the calibration
            self.log(f"(sin capa visual: {e})")

    def read_now(self):
        def job():
            win = self._find_window()
            frame = frames.grab(win)
            vals = {k: ocr.read_number(frame, self.cfg.regions[k])
                    for k in ("gold", "elixir", "damage") if k in self.cfg.regions}
            left = ocr.read_time_left(frame, self.cfg.regions["timer"]) if "timer" in self.cfg.regions else None
            self.q.put(("reading", {"gold": vals.get("gold"), "elixir": vals.get("elixir"),
                                    "damage": vals.get("damage"), "time_left": left}))
            self.log(f"Lectura: {vals} · reloj {left}")
        self._worker(job)

    def dispose(self):
        """Stop timers and the bot; leaves hotkeys and the Tk root alone."""
        self.stop_ev.set()
        if self.recorder:
            try:
                self.recorder.stop()
            except Exception:
                pass
            self.recorder = None
        if self._after_id:
            self.root.after_cancel(self._after_id)
        self.app.release_window(self)
        self.app.release_exclusive(self)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"CoC Macro v{__version__}")
        root.configure(bg=BG)
        root.minsize(WIDTH, 0)
        root.resizable(False, True)
        theme.apply_ttk_style(root)
        self._apply_notebook_style(root)

        self._owned: dict[int, AccountPanel] = {}
        self._owned_lock = threading.Lock()
        self.exclusive: AccountPanel | None = None

        self.nb = ttk.Notebook(root, style="Dark.TNotebook")
        self.nb.pack(fill="both", expand=True)

        files = accounts.load_registry(DATA)
        self.panels = []
        for file in files:
            if file == "config.json":
                p = AccountPanel(self.nb, self, CFG_PATH, 1)
            else:
                p = AccountPanel(self.nb, self, DATA / file, accounts.account_index(file))
            tab_title = p.cfg.account_name or f"Cuenta {p.index}"
            self.nb.add(p, text=tab_title)
            self.panels.append(p)
        self.panel = self.panels[0]

        ctrl_row = tk.Frame(root, bg=BG)
        ctrl_row.pack(side="bottom", fill="x", padx=24, pady=(8, 10), before=self.nb)   # always visible
        self.btn_add = theme.button(ctrl_row, "+ Añadir cuenta", self.add_account, "secondary", 9, padx=10, pady=4)
        self.btn_add.pack(side="left")
        self._update_btn_add()

        root.bind("<MouseWheel>", self._on_wheel)      # one handler for the whole window (replaces any older one)
        self.unregister = hotkeys.start(self._hotkey_stop, self._hotkey_end_record)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if getattr(sys, "frozen", False):
            updater.cleanup_old(Path(sys.executable))
        if self.panel.cfg.auto_check_updates:
            threading.Thread(target=self.check_update, args=(False,), daemon=True).start()

    def _on_wheel(self, event):
        """Mouse wheel scrolls the visible tab, except over a log or a dropdown, which use it themselves."""
        try:
            if event.widget.winfo_class() in ("Text", "TCombobox", "Combobox"):
                return
            panel = self.nb.nametowidget(self.nb.select())
        except (AttributeError, KeyError, tk.TclError):
            return
        panel.scroll_by(-1 if event.delta > 0 else 1)

    def _apply_notebook_style(self, root: tk.Tk):
        st = ttk.Style(root)
        st.configure("Dark.TNotebook", background=BG, borderwidth=0)
        st.configure("Dark.TNotebook.Tab", background=CARD, foreground=MUTED, borderwidth=0,
                     padding=[14, 6], font=theme.font(10))
        st.map("Dark.TNotebook.Tab",
               background=[("selected", BORDER), ("active", CARD)],
               foreground=[("selected", TEXT), ("active", TEXT)])

    def _update_btn_add(self):
        can_add = len(self.panels) < accounts.MAX_ACCOUNTS
        theme.set_enabled(self.btn_add, can_add, "secondary")

    def _refresh_all(self):
        for p in self.panels:
            p.refresh_state()

    def claim_window(self, panel: AccountPanel, hwnd: int) -> bool:
        with self._owned_lock:             # bot threads race here when two tabs start at once
            owner = self._owned.get(hwnd)
            if owner is not None and owner is not panel:
                return False
            self._owned[hwnd] = panel      # no widgets here (bot thread): the job posts "refresh_all"
            return True

    def release_window(self, panel: AccountPanel) -> None:
        with self._owned_lock:
            hwnds = [h for h, p in self._owned.items() if p is panel]
            for h in hwnds:
                del self._owned[h]
        if hwnds:
            self._refresh_all()

    def window_in_use_by_other(self, panel: AccountPanel, hwnd: int) -> bool:
        with self._owned_lock:
            owner = self._owned.get(hwnd)
        return owner is not None and owner is not panel

    def try_exclusive(self, panel: AccountPanel) -> bool:
        if self.exclusive not in (None, panel):
            return False
        for p in self.panels:
            if p is not panel and (p.busy or p.mode in ("running", "stopping")):
                return False
        if panel.busy or panel.mode in ("running", "stopping"):
            return False
        self.exclusive = panel
        self._refresh_all()
        return True

    def release_exclusive(self, panel: AccountPanel) -> None:
        if self.exclusive is panel:
            self.exclusive = None
            self._refresh_all()

    def add_account(self):
        if len(self.panels) >= accounts.MAX_ACCOUNTS:
            self.panel.log(f"Ya hay el maximo de cuentas ({accounts.MAX_ACCOUNTS})")
            return
        try:
            filename, cfg = accounts.add_account(DATA)
        except (ValueError, OSError) as e:
            self.panel.log(f"No se pudo anadir la cuenta: {e}")
            return
        idx = accounts.account_index(filename)
        panel = AccountPanel(self.nb, self, DATA / filename, idx)
        title = panel.cfg.account_name or f"Cuenta {panel.index}"
        self.nb.add(panel, text=title)
        self.panels.append(panel)
        self.nb.select(panel)
        self._update_btn_add()
        panel._fit()

    def close_account(self, panel: AccountPanel):
        if panel.index == 1:
            return
        if panel.busy or panel.mode in ("running", "stopping"):
            messagebox.showwarning("CoC Macro", "Para la cuenta antes de cerrarla")
            return
        title = panel.cfg.account_name or f"Cuenta {panel.index}"
        if not messagebox.askyesno("Cerrar cuenta", f"¿Cerrar {title}?"):
            return
        panel.dispose()
        accounts.remove_account(DATA, panel.cfg_path.name)
        self.nb.forget(panel)
        panel.destroy()
        if panel in self.panels:
            self.panels.remove(panel)
        self._update_btn_add()

    def update_tab_title(self, panel: AccountPanel):
        title = panel.cfg.account_name or f"Cuenta {panel.index}"
        try:
            self.nb.tab(panel, text=title)
        except Exception:
            pass

    # -- hotkeys (they run on the listener thread: only post to the Tk thread's queues) ----------
    def _hotkey_stop(self):
        for p in list(self.panels):
            p.q.put(("stop", None))

    def _hotkey_end_record(self):
        for p in list(self.panels):
            if p.recorder is not None:
                p.q.put(("end_record", None))

    # -- updates -------------------------------------------------------
    def check_update(self, manual: bool):
        try:
            info = updater.check(__version__)
        except Exception as e:  # offline, rate limited...: only bother the user if they asked
            if manual:
                self.panel.log(f"No se pudo comprobar actualizaciones: {e}")
            return
        if info:
            self.panel.q.put(("update", (info, manual)))
        elif manual:
            self.panel.log(f"Estas al dia (v{__version__})")

    def offer_update(self, info: "updater.UpdateInfo", manual: bool):
        if not messagebox.askyesno(
                "Actualizacion",
                f"Hay una version nueva: v{info.version} (tienes v{__version__}).\n\n"
                "Se descarga de GitHub, se comprueba su hash y la app se reinicia.\n"
                "¿Instalarla ahora?"):
            return
        if not getattr(sys, "frozen", False):
            self.panel.log("Estas ejecutando desde el codigo: actualiza con git pull")
            return
        if any(p.busy for p in self.panels):
            self.panel.log("Para el bot antes de actualizar")
            return

        def job():
            exe = Path(sys.executable)
            dest = updater.new_path_for(exe)
            last = [0]

            def progress(n):
                if n - last[0] >= 10_000_000 or (info.size and n >= info.size):
                    last[0] = n
                    self.panel.log(f"Descargando... {n // 1_000_000} MB")
            self.panel.log(f"Descargando v{info.version}...")
            updater.download(info, dest, progress=progress)
            self.panel.log("Hash correcto. Instalando y reiniciando...")
            updater.apply_update(dest, exe)
            self.panel.q.put(("quit", None))
        self.panel._worker(job)

    def dispose(self):
        """Stop timers, hotkeys and every panel; leaves the Tk root alone (tests reuse one)."""
        for p in self.panels:
            p.dispose()
        self.root.unbind("<MouseWheel>")
        self.unregister()

    def close(self):
        self.dispose()
        self.root.destroy()


def main():
    root = tk.Tk()
    DATA.mkdir(exist_ok=True)
    flag = DATA / "accepted.flag"
    if not flag.exists():
        if not messagebox.askokcancel("Aviso", WARNING):
            return
        flag.write_text("ok")
    App(root)
    root.mainloop()
