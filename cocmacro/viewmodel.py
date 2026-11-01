"""Texts and states the window shows, kept free of tkinter so they can be tested."""
from cocmacro.config import Config, format_mmss

PHASES = [("search", "Buscar"), ("evaluate", "Evaluar"), ("deploy", "Desplegar"),
          ("watch", "Vigilar"), ("surrender", "Rendirse"), ("back", "Volver")]
PHASE_TITLES = {"search": "Buscando aldea", "evaluate": "Evaluando aldea", "deploy": "Desplegando tropas",
                "watch": "Vigilando la batalla", "surrender": "Rindiéndose", "back": "Volviendo al pueblo"}


def fmt_int(n: int | None) -> str:
    return "—" if n is None else f"{n:,}".replace(",", ".")


def loot_hint(value: int | None, minimum: int) -> tuple[str, str]:
    if value is None:
        return "none", ""
    if value > minimum:
        return "ok", f"supera {fmt_int(minimum)}"
    return "no", f"no llega a {fmt_int(minimum)}"


def damage_fraction(pct: int | None, threshold: int) -> float:
    if pct is None or threshold <= 0:
        return 0.0
    return min(1.0, pct / threshold)


def time_hint(cfg: Config) -> str:
    if cfg.surrender_time_s <= 0:
        return "regla del reloj desactivada"
    return f"se rinde bajo {format_mmss(cfg.surrender_time_s)}"


def state_title(mode: str, phase: str | None, missing_steps: int = 0) -> str:
    if mode == "setup":
        return f"Falta preparar {missing_steps} paso" + ("" if missing_steps == 1 else "s")
    if mode == "stopping":
        return "Parando…"
    if mode == "running":
        return PHASE_TITLES.get(phase or "", "Empezando…")
    return "Listo para atacar"


def phase_steps(phase: str | None) -> list[tuple[str, str]]:
    keys = [k for k, _ in PHASES]
    cur = keys.index(phase) if phase in keys else -1
    out = []
    for i, (_, label) in enumerate(PHASES):
        out.append((label, "todo" if cur < 0 else "done" if i < cur else "current" if i == cur else "todo"))
    return out


def chips(game: tuple[int, int] | None, missing: list[str], deployment: str | None,
          deployment_ok: bool) -> list[tuple[str, str]]:
    return [
        ("ok", f"Juego conectado · {game[0]}×{game[1]}") if game else ("bad", "Juego no encontrado"),
        ("ok", "Calibrado") if not missing else ("warn", "Sin calibrar"),
        ("ok", f"Despliegue: {deployment}") if deployment_ok and deployment else ("warn", "Sin despliegue"),
    ]


def setup_steps(missing: list[str], deployment_ok: bool) -> list[dict]:
    cal_done = not missing
    return [
        {"n": 1, "title": "Calibrar botones y zonas", "done": cal_done, "active": not cal_done,
         "help": "Un ataque guiado: clica los botones y arrastra sobre los números del oro, elixir, daño y reloj. "
                 "Verás un recuadro punteado con la zona sugerida."},
        {"n": 2, "title": "Grabar tu despliegue", "done": deployment_ok, "active": cal_done and not deployment_ok,
         "help": "Despliega tus tropas una vez y pulsa F9 para terminar. Puedes guardar varios."},
    ]
