"""Colours and small flat widgets for the window (dark, gold accent), see the design canvas."""
import tkinter as tk
from tkinter import ttk

BG, CARD, BORDER = "#14181f", "#1d232d", "#2d3544"
TEXT, MUTED, DIM = "#e8ecf3", "#a3adbf", "#7d8799"
GOLD, GREEN, RED, PINK = "#f2c14e", "#238636", "#c93c37", "#e08ae0"
OK, WARN, BAD = "#3fb950", "#f2c14e", "#f85149"
FONT = "Segoe UI"

DOT = {"ok": OK, "warn": WARN, "bad": BAD}
HINT = {"ok": OK, "no": MUTED, "none": MUTED}

# kind -> (background, foreground, active background)
BUTTON_KINDS = {
    "primary": (GREEN, "#ffffff", "#2ea043"),
    "danger": (RED, "#ffffff", "#da3633"),
    "gold": (GOLD, BG, "#ffd36b"),
    "secondary": (BG, TEXT, BORDER),
    "ghost": (CARD, TEXT, BORDER),
}


def font(size: int = 10, bold: bool = False) -> tuple:
    return (FONT, size, "bold") if bold else (FONT, size)


def card(parent, border: str = BORDER) -> tk.Frame:
    return tk.Frame(parent, bg=CARD, highlightbackground=border, highlightcolor=border, highlightthickness=1)


def label(parent, text: str = "", size: int = 10, bold: bool = False, fg: str = TEXT, bg: str = CARD,
          **kw) -> tk.Label:
    return tk.Label(parent, text=text, font=font(size, bold), fg=fg, bg=bg, anchor=kw.pop("anchor", "w"), **kw)


def caption(parent, text: str, bg: str = CARD) -> tk.Label:
    return label(parent, text.upper(), 8, True, MUTED, bg)


def button(parent, text: str, command, kind: str = "secondary", size: int = 10, **kw) -> tk.Button:
    bgc, fgc, active = BUTTON_KINDS[kind]
    return tk.Button(parent, text=text, command=command, font=font(size, True), bg=bgc, fg=fgc,
                     activebackground=active, activeforeground=fgc, disabledforeground=DIM, relief="flat",
                     bd=0, highlightthickness=1, highlightbackground=BORDER if kind in ("secondary", "ghost") else bgc,
                     cursor="hand2", padx=kw.pop("padx", 14), pady=kw.pop("pady", 8), **kw)


def set_enabled(btn: tk.Button, enabled: bool, kind: str) -> None:
    bgc, fgc, _ = BUTTON_KINDS[kind]
    btn.configure(state="normal" if enabled else "disabled", bg=bgc if enabled else CARD,
                  highlightbackground=bgc if enabled and kind not in ("secondary", "ghost") else BORDER,
                  cursor="hand2" if enabled else "arrow")


def entry(parent, var: tk.StringVar, width: int = 10, justify: str = "left") -> tk.Entry:
    return tk.Entry(parent, textvariable=var, width=width, justify=justify, font=font(11), bg=BG, fg=TEXT,
                    insertbackground=TEXT, relief="flat", highlightthickness=1, highlightbackground=BORDER,
                    highlightcolor=GOLD, disabledbackground=BG, disabledforeground=DIM)


def apply_ttk_style(root: tk.Tk) -> None:
    st = ttk.Style(root)
    st.theme_use("clam")
    st.configure("Dark.TCombobox", fieldbackground=BG, background=BORDER, foreground=TEXT, arrowcolor=TEXT,
                 bordercolor=BORDER, lightcolor=BG, darkcolor=BG, selectbackground=BG, selectforeground=TEXT)
    st.map("Dark.TCombobox", fieldbackground=[("readonly", BG), ("disabled", BG)],
           foreground=[("disabled", DIM)], selectbackground=[("readonly", BG)], selectforeground=[("readonly", TEXT)])
    st.configure("Dark.Vertical.TScrollbar", background=BORDER, troughcolor=CARD, bordercolor=CARD,
                 arrowcolor=MUTED, lightcolor=BORDER, darkcolor=BORDER, relief="flat")
    st.map("Dark.Vertical.TScrollbar", background=[("active", DIM)])
    root.option_add("*TCombobox*Listbox.background", BG)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", BORDER)
    root.option_add("*TCombobox*Listbox.selectForeground", TEXT)
