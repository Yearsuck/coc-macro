# Prioritize heroes in busy mode (2026-11-07)

Toggle `prioritize_heroes` (GUI checkbox, default off), busy mode only.

- Builders tab: select the **Heroe** filter (clearing Permanente / Coste min), press its first allowed row.
  Nothing to upgrade, or the price is red -> fall back to Permanente + Coste min as before.
- The Heroe filter also lists siege machines. **Arrojatroncos, Destructor and Tiradora are never upgraded**
  (user rule): rows are recognised by their name text (`skip_*` templates) and skipped, on every builders-tab flow.
- The game remembers filters: the plain flow now switches the Heroe filter off if it is left on.
- Walls mode's surplus step does not use heroes.

Verified live (main account, 1 free builder): Heroe filter on, first row = Rey barbaro, confirmed, dark elixir
239 139 -> 218 559 (-20 580). Not verified live: the fallback path, and a skipped row.
