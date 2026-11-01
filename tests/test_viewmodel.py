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
