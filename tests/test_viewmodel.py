import pytest

from cocmacro import config, viewmodel as vm


def test_fmt_int_uses_dots_and_a_dash_for_none():
    assert vm.fmt_int(1664232) == "1.664.232"
    assert vm.fmt_int(912) == "912"
    assert vm.fmt_int(None) == "—"


def test_loot_hint_against_the_minimum():
    assert vm.loot_hint(1664232, 500000) == ("ok", "supera 500.000")
    assert vm.loot_hint(383078, 500000) == ("no", "no llega a 500.000")
    assert vm.loot_hint(500000, 500000) == ("no", "no llega a 500.000")     # must be strictly more
    assert vm.loot_hint(None, 500000) == ("none", "")


def test_damage_fraction_fills_towards_the_surrender_threshold():
    assert vm.damage_fraction(36, 50) == 0.72
    assert vm.damage_fraction(80, 50) == 1.0
    assert vm.damage_fraction(None, 50) == 0.0
    assert vm.damage_fraction(10, 0) == 0.0


def test_time_hint():
    assert vm.time_hint(config.Config()) == "se rinde bajo 2:20"
    assert vm.time_hint(config.Config(surrender_time_s=0)) == "regla del reloj desactivada"


def test_titles():
    assert vm.state_title("idle", None) == "Listo para atacar"
    assert vm.state_title("setup", None, missing_steps=2) == "Falta preparar 2 pasos"
    assert vm.state_title("setup", None, missing_steps=1) == "Falta preparar 1 paso"
    assert vm.state_title("running", "watch") == "Vigilando la batalla"
    assert vm.state_title("running", "search") == "Buscando aldea"
    assert vm.state_title("running", None) == "Empezando…"


def test_phase_steps_mark_done_current_and_todo():
    steps = vm.phase_steps("watch")
    assert [s[0] for s in steps] == ["Buscar", "Evaluar", "Desplegar", "Vigilar", "Rendirse", "Volver"]
    assert [s[1] for s in steps] == ["done", "done", "done", "current", "todo", "todo"]
    assert [s[1] for s in vm.phase_steps(None)] == ["todo"] * 6


def test_chips():
    chips = vm.chips(game=(951, 535), missing=[], deployment="DragonElectrico", deployment_ok=True)
    assert chips == [("ok", "Juego conectado · 951×535"), ("ok", "Calibrado"), ("ok", "Despliegue: DragonElectrico")]
    chips = vm.chips(game=None, missing=["battle"], deployment=None, deployment_ok=False)
    assert chips == [("bad", "Juego no encontrado"), ("warn", "Sin calibrar"), ("warn", "Sin despliegue")]


def test_setup_steps():
    both = vm.setup_steps(missing=["battle"], deployment_ok=False)
    assert [(s["n"], s["done"], s["active"]) for s in both] == [(1, False, True), (2, False, False)]
    after_cal = vm.setup_steps(missing=[], deployment_ok=False)
    assert [(s["done"], s["active"]) for s in after_cal] == [(True, False), (False, True)]
    assert all(s["done"] for s in vm.setup_steps(missing=[], deployment_ok=True))


def test_mode_labels_roundtrip_and_unknown_means_none():
    from cocmacro import viewmodel as vm
    for key, label in vm.MODES:
        assert vm.mode_from_label(vm.mode_label(key)) == key == vm.mode_from_label(label)
    assert vm.mode_from_label("???") == "none" and vm.mode_label("???") == vm.MODES[0][1]


# ── texts of the new states and the mode help ──────────────────────────────────

@pytest.mark.parametrize("phase,title", [("upgrade", "Mejorando"), ("wait_builder", "Esperando un constructor libre"),
                                         ("recover", "Recuperandose de un atasco")])
def test_phases_between_attacks_have_a_title(phase, title):
    assert vm.state_title("running", phase) == title


def test_phases_between_attacks_are_no_step_of_the_stepper():
    for phase in ("upgrade", "wait_builder", "recover"):
        assert all(state == "todo" for _, state in vm.phase_steps(phase))


@pytest.mark.parametrize("mode", [k for k, _ in vm.MODES])
def test_every_mode_says_what_it_does(mode):
    assert vm.mode_help(mode).strip()


def test_the_walls_help_says_it_waits_for_a_builder():
    assert "constructor" in vm.mode_help("walls") and "llenar" in vm.mode_help("walls")


def test_an_unknown_mode_gets_the_plain_text_not_an_error():
    assert vm.mode_help("zzz") == vm.mode_help("none")


def test_the_heroes_option_only_applies_to_the_cheapest_upgrade_mode():
    assert [m for m, _ in vm.MODES if vm.hero_option_applies(m)] == ["busy"]


@pytest.mark.parametrize("line,level", [
    ("Atacando: oro 1, elixir 2", "ok"), ("Mejora lanzada (constructor)", "ok"), ("Ataque 7 completado", "ok"),
    ("Siguiente: oro 1, elixir 2", "warn"), ("Aviso de recarga: pulso y espero la aldea", "warn"),
    ("Deposito lleno y sin constructor libre: espero a que quede uno", "warn"), ("Cancelo una busqueda que no avanza", "warn"),
    ("Error inesperado: boom", "bad"), ("Tiempo agotado esperando: aldea enemiga", "bad"), ("Durante la recuperacion: x", "bad"),
    ("Tiempo agotado esperando: aldea enemiga. Intento recuperar", "bad"),
    ("La busqueda no arranco. Intento recuperar", "bad"),          # the reason can be any message: the recovery wins
    ("Mejorando muros", ""), ("Ataque raro", ""),
])
def test_log_lines_get_their_colour(line, level):
    assert vm.log_level(line) == level
