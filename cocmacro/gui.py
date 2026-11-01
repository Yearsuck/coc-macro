"""Single-window tkinter app: start/stop the bot, record deployments, calibrate."""
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from cocmacro import (__version__, bot, calibrate, config, frames, game, hotkeys, ocr, overlay, paths,
                      preflight, recorder, updater, winctl)
from cocmacro.config import format_mmss, parse_mmss

DATA = paths.data_dir()
CFG_PATH, TPL_DIR, REC_DIR = DATA / "config.json", DATA / "templates", DATA / "recordings"
WARNING = ("Supercell prohibe automatizar ataques con macros.\n"
           "Usar esta app puede suponer el BAN de tu cuenta. Lo haces bajo tu responsabilidad.\n\n"
           "F8 = parar todo, F9 = terminar de grabar un despliegue.")


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(f"CoC Macro v{__version__}")
        self.cfg = config.load(CFG_PATH)
        self.q: queue.Queue = queue.Queue()
        self.stop_ev = threading.Event()
        self.bot: bot.Bot | None = None
        self.recorder: recorder.Recorder | None = None
        self.busy = False
        self.overlay: overlay.Overlay | None = None
        self._build()
        self.refresh_recordings()
        self.unregister = hotkeys.start(lambda: self.q.put(("stop", None)),
                                        lambda: self.q.put(("end_record", None)))
        root.protocol("WM_DELETE_WINDOW", self.close)
        if getattr(sys, "frozen", False):
            updater.cleanup_old(Path(sys.executable))
        if self.cfg.auto_check_updates:
            threading.Thread(target=self._check_update, args=(False,), daemon=True).start()
        self.root.after(50, self._poll)

    # -- layout --------------------------------------------------------
    def _build(self):
        f = ttk.Frame(self.root, padding=8)
        f.grid()
        self.btn_start = ttk.Button(f, text="Empezar", command=self.start)
        self.btn_stop = ttk.Button(f, text="Parar (F8)", command=self.stop)
        self.btn_rec = ttk.Button(f, text="Grabar despliegue", command=self.toggle_record)
        self.btn_cal = ttk.Button(f, text="Calibrar", command=self.calibrate)
        self.btn_read = ttk.Button(f, text="Leer ahora", command=self.read_now)
        self.btn_cal_timer = ttk.Button(f, text="Calibrar reloj", command=self.calibrate_timer)
        for i, b in enumerate((self.btn_start, self.btn_stop, self.btn_rec, self.btn_cal, self.btn_cal_timer,
                               self.btn_read)):
            b.grid(row=0, column=i, padx=2, pady=2)
        self.dry = tk.BooleanVar()
        ttk.Checkbutton(f, text="Solo simular", variable=self.dry).grid(row=1, column=0, columnspan=2, sticky="w")
        self.auto_upd = tk.BooleanVar(value=self.cfg.auto_check_updates)
        ttk.Checkbutton(f, text="Buscar actualizaciones al abrir", variable=self.auto_upd).grid(
            row=1, column=2, columnspan=3, sticky="w")
        ttk.Button(f, text="Buscar actualizaciones", command=lambda: threading.Thread(
            target=self._check_update, args=(True,), daemon=True).start()).grid(row=2, column=3, columnspan=2)
        ttk.Label(f, text="Despliegue:").grid(row=2, column=0, sticky="e")
        self.combo = ttk.Combobox(f, state="readonly", width=20)
        self.combo.grid(row=2, column=1, columnspan=2, sticky="w")
        self.gold, self.elixir, self.pct = (tk.StringVar(value=str(v)) for v in
                                            (self.cfg.gold_min, self.cfg.elixir_min, self.cfg.surrender_pct))
        for r, (label, var) in enumerate((("Oro minimo", self.gold), ("Elixir minimo", self.elixir),
                                          ("Rendirse al %", self.pct)), start=3):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="e")
            ttk.Entry(f, textvariable=var, width=12).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="Rendirse si quedan < (m:ss)").grid(row=6, column=0, sticky="e")
        self.time_var = tk.StringVar(value=format_mmss(self.cfg.surrender_time_s))
        ttk.Entry(f, textvariable=self.time_var, width=12).grid(row=6, column=1, sticky="w")
        ttk.Label(f, text="(0:00 = desactivado)").grid(row=6, column=2, sticky="w")
        self.counter = ttk.Label(f, text="Ataques: 0")
        self.counter.grid(row=3, column=3, columnspan=2)
        self.logbox = scrolledtext.ScrolledText(f, width=70, height=16, state="disabled")
        self.logbox.grid(row=7, column=0, columnspan=6, pady=6)

    # -- helpers -------------------------------------------------------
    def log(self, msg: str):
        self.q.put(("log", msg))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", val + "\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "stop":
                    self.stop()
                elif kind == "end_record":
                    if self.recorder:
                        self.toggle_record()
                elif kind == "done":
                    self.busy = False
                elif kind == "update":
                    self._offer_update(*val)
                elif kind == "quit":
                    self.close()
                elif kind.startswith("ov_"):
                    self._overlay_event(kind, val)
        except queue.Empty:
            pass
        if self.bot:
            self.counter.configure(text=f"Ataques: {self.bot.attacks_done}")
        self.root.after(50, self._poll)

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
        self.cfg.auto_check_updates = self.auto_upd.get()
        DATA.mkdir(exist_ok=True)
        config.save(self.cfg, CFG_PATH)
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
        if not self._read_cfg():
            return
        dry = self.dry.get()
        err = preflight.check(self.cfg, TPL_DIR, REC_DIR, dry)
        if err:
            self.log(err)
            return

        def job():
            win = winctl.find_game_window()
            rec = None if dry else recorder.load_recording(self.cfg.deployment, REC_DIR)
            g = game.RealGame(win, self.cfg, rec, self.stop_ev, TPL_DIR)
            self.bot = bot.Bot(g, self.cfg, self.log, self.stop_ev, dry_run=dry)
            self.log("Simulacion (no pulsa nada)" if dry else "Empezando bucle de ataques (F8 para parar)")
            if dry:
                self.bot.run_once()
            else:
                self.bot.run()
            self.log("Parado")
        self._worker(job)

    def stop(self):
        self.stop_ev.set()
        self.log("Parando...")

    def toggle_record(self):
        if self.recorder is None:
            try:
                win = winctl.find_game_window()
            except winctl.WindowNotFound as e:
                self.log(str(e))
                return
            name = simpledialog.askstring("Grabar despliegue", "Nombre del despliegue:", parent=self.root)
            if not name:
                return
            self.recorder = recorder.Recorder.for_window(win, name.strip())
            self.recorder.start()
            self.btn_rec.configure(text="Terminar grabacion (F9)")
            self.log(f"Grabando '{name}': haz tu despliegue en el juego y pulsa F9")
        else:
            rec = self.recorder.stop()
            self.recorder = None
            self.btn_rec.configure(text="Grabar despliegue")
            if rec.events:
                recorder.save_recording(rec, REC_DIR)
                self.cfg.deployment = rec.name
                self.refresh_recordings()
                self.log(f"Guardado '{rec.name}' ({len(rec.events)} eventos)")
            else:
                self.log("Grabacion vacia: no se guardo")

    def calibrate(self):
        steps = calibrate.STEPS

        def job():
            win = winctl.find_game_window()
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
        def job():
            win = winctl.find_game_window()
            prompt = "Entra en una batalla y arrastra un rectangulo sobre el reloj (ej. 2m 51s)"
            self.log(f"[timer] {prompt}")
            self._calibrate_step(win, "timer", "region", prompt)
            self.log("Reloj calibrado")
            self.q.put(("ov_hide", 2500))
        self._worker(job)

    def _calibrate_step(self, win, name: str, kind: str, banner: str):
        """One calibration step with on-screen feedback (overlay events go through the queue)."""
        self.q.put(("ov_banner", banner))
        self.cfg = calibrate.run_step(
            win, self.cfg, name, kind, TPL_DIR,
            on_rect=lambda r: self.q.put(("ov_rect", r)),
            on_click=lambda p: self.q.put(("ov_marker", (p, name))),
            on_invalid=lambda m: self.q.put(("ov_banner", f"Atencion: {m}")))
        if kind == "region":
            self.q.put(("ov_saved", (name, self.cfg.regions[name])))
        DATA.mkdir(exist_ok=True)
        config.save(self.cfg, CFG_PATH)

    def _overlay_event(self, kind: str, val):
        try:
            if self.overlay is None:
                self.overlay = overlay.Overlay(self.root)
            if kind == "ov_banner":
                self.overlay.banner(val)
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
            win = winctl.find_game_window()
            frame = frames.grab(win)
            vals = {k: ocr.read_number(frame, self.cfg.regions[k])
                    for k in ("gold", "elixir", "damage") if k in self.cfg.regions}
            vals["timer"] = ocr.read_time_left(frame, self.cfg.regions["timer"]) if "timer" in self.cfg.regions else None
            self.log(f"Lectura: {vals}")
        self._worker(job)

    # -- updates -------------------------------------------------------
    def _check_update(self, manual: bool):
        try:
            info = updater.check(__version__)
        except Exception as e:  # offline, rate limited...: only bother the user if they asked
            if manual:
                self.log(f"No se pudo comprobar actualizaciones: {e}")
            return
        if info:
            self.q.put(("update", (info, manual)))
        elif manual:
            self.log(f"Estas al dia (v{__version__})")

    def _offer_update(self, info: "updater.UpdateInfo", manual: bool):
        if not messagebox.askyesno(
                "Actualizacion",
                f"Hay una version nueva: v{info.version} (tienes v{__version__}).\n\n"
                "Se descarga de GitHub, se comprueba su hash y la app se reinicia.\n"
                "¿Instalarla ahora?"):
            return
        if not getattr(sys, "frozen", False):
            self.log("Estas ejecutando desde el codigo: actualiza con git pull")
            return
        if self.busy:
            self.log("Para el bot antes de actualizar")
            return

        def job():
            exe = Path(sys.executable)
            dest = updater.new_path_for(exe)
            last = [0]

            def progress(n):
                if n - last[0] >= 10_000_000 or (info.size and n >= info.size):
                    last[0] = n
                    self.log(f"Descargando... {n // 1_000_000} MB")
            self.log(f"Descargando v{info.version}...")
            updater.download(info, dest, progress=progress)
            self.log("Hash correcto. Instalando y reiniciando...")
            updater.apply_update(dest, exe)
            self.q.put(("quit", None))
        self._worker(job)

    def close(self):
        self.stop_ev.set()
        self.unregister()
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
