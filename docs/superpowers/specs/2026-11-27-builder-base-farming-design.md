# Builder Base farming while walls mode waits

## Intent
Walls mode stops attacking when a main-village storage is full and no builder is free, and then waits, often for hours
(live 2026-11-27: "Deposito lleno y sin constructor libre: espero a que quede uno"). That time is wasted. The user farms
the Builder Base by hand in that situation; the bot should do it instead and come back when there is something to do in
the main village.

## The user's own loop (their words, condensed)
Tap the boat in the main village -> Batalla -> Buscar -> deploy the troops around the village -> when they die, collect
the elixir cart and attack again. 100% in the first stage opens a second stage that can reach 200%.
Stop farming there "when the storages are full".

## Goals
- In walls mode, while the bot would wait for a builder, farm the Builder Base in a loop.
- Leave the Builder Base and go back to the main village when either:
  - the Builder Base storages are full (the user's rule; attacks only give gold, elixir comes from the cart, so in
    practice gold full), or
  - a main-village builder is free again (the wall routine is the priority). *Builder's call how often this is checked;
    the Builder Base HUD shows its own builders, so the main-village counter is only readable after sailing back.*
- Collect the star bonus popup and the elixir cart when possible.

## Non-goals
- No upgrades in the Builder Base (no buildings, walls, troops).
- No new GUI mode: it is part of walls mode. *(My call: an option to switch it off may be added if cheap.)*
- No recorded deployment: troops are spread around the village by fixed points.

## Anti-goals (a failure even if it "works")
- Spending gems or items: never press "Potenciar ejercito", "Potenciar heroes", "Usar", any gem button.
- Leaving the game stuck in the Builder Base: the main-village bot must never be run on the Builder Base screen (live:
  it pressed Batalla there and waited for ever on a screen it did not know).
- Breaking the existing walls loop or the attack loop of the main village.

## Facts verified live (2026-11-27, three manual attacks, frames normalised to 1296x729)
- Boat: in the main village it may be off screen; a pan dragging from the forest edge (never starting on a building,
  a tap there opened the profile) uncovers it, then a tap travels. In the Builder Base the boat is at the right edge
  (~0.86, 0.44-0.54 depending on the pan) and a tap sails back. Each trip takes ~5-8 s.
- Batalla (same spot as the main village, 0.0747, 0.882) opens "Empezar ataque"; "Buscar" at (0.744, 0.654).
  "Usar" (a potion) can appear in that panel: never press it.
- Battle: ~60 s countdown "La batalla empieza en"; deploying starts it. Troop bar at y 0.90: hero card x 0.167, troop
  cards from x 0.242 every ~0.066 px; stage 2 adds cards 7 and 8 and greys the dead ones. A tap on a card then a tap on
  the field drops it; a drop inside the red no-deploy zone is ignored (the card stays coloured).
- Stage 2 starts by itself after 100%: a new base, its own countdown, survivors keep their cards. Deploy again.
- End: "Terminar batalla" / "Rendirse" button at bottom left; result screen with "Volver" (0.5, 0.84) and rewards.
  200% paid 130 000 gold; 79% paid 68 000. Gold keeps coming after the daily star bonus.
- Star bonus: after the 8th star a "Bonus estelar" popup with "Vale" (0.5, 0.763). Next one in ~18 h.
- Elixir cart: a building near the top of the Builder Base; its window "Carro de elixir" has "Recoger" (0.735, 0.844)
  and an X (0.838, 0.1). With full elixir it shows "Espacio insuficiente" and collects nothing.
- Storage bars in the Builder Base HUD sit near the main-village ones, but the current `storage_full` read gave
  "not full" on a full elixir bar in 3 of 4 captures: the Builder Base needs its own regions/thresholds.
- Hero ability (tapping the hero card again) was tried but not confirmed to do anything.

## How it fits (decided)
Walls mode, at the point where it now logs "espero a que quede uno": sail to the Builder Base, run the farming loop,
sail back, then continue as today (read builders, upgrade walls or wait).

## Decisions after the builder check (*my calls*, marked so the user can overrule them)
- *After leaving because the Builder Base storage is full and no main builder is free, the bot waits in the main village
  as today. It does not sail back while the Builder Base is known full* (nothing spends its gold), so there is no
  ping-pong between villages. *The "full" mark is cleared when the bot is restarted.*
- *A visit is at most 5 attacks*; then the bot sails back, looks at the main builders and may return. Full Builder
  Base gold is read with the main village's gold-bar reading (same bar geometry); never seen full live.
- Only the `wait_builder` point ("espero a que quede uno") triggers it, not `wait_if_full` / `stop_when_full`.
- The army needs no handling: three attacks in a row were started with the same army, no training or cooldown.
- The first task is a reliable "this is the Builder Base" recogniser (and "this is the main village"); no Builder Base
  action is taken without it, and every recovery first makes sure the game is back in the main village.
- Raw captures are git-ignored live material (session scratchpad `bb/`, to be copied to `tests/fixtures/raw/`); masked
  fixtures (no player or clan names) go to `tests/fixtures/ui/`.

## Left to the builder
- Screen recognition (templates for the Builder Base village, battle, result, cart, boat, star popup) from the captures.
- Deployment points and retries for cards that did not drop; whether to use the hero ability.
- When to give up on a battle (wait for the troops to die vs "Terminar batalla" once all cards are used and damage
  stops rising).
- Recovery: any stuck state in the Builder Base sails back to the main village before the usual recovery.
- Tests (lean, parametrised, on masked captures) and the live check.

## Not verified
- Collecting the cart with room in the elixir storage; the hero ability; what "full" looks like for Builder Base gold.
