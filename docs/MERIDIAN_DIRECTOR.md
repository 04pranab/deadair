# MERIDIAN: the Director

MERIDIAN is a **deterministic, rule-based** adaptive director. There is no machine learning and no hidden randomness outside a seeded RNG of its own (`seed * 0x9E3779B1 ^ 0xD1EC7`), so the same seed and the same inputs give the same decisions. Code: `src/systems/director*.py`, `rift.py`, `host.py`, `overlord.py`, `machines.py`. Data: `data/director.json`, `rift.json`, `host.json`, `overlord.json`.

## What it does

1. **Observes** real state once per second (`Observer`): crew health, distances, kills, revivals, room traversal, damage range. It builds a smoothed *tension* value from nearby enemy weights (`tension.weights`) and tracks "relaxed / building / trouble" with dwell times so it does not flap.
2. **Detects patterns** (`director_rules.py`): route reuse, rushing, splitting, resource hoarding, resurrection reliance, ranged dominance, melee dominance. Each has an on/off hysteresis pair (0.6 / 0.35), a minimum sample count and a confirmation of 2 consecutive thinks, so one coincidence never triggers a counter.
3. **Spends a budget** (`director_budget.py`): 35 points to start, cap 120, +0.9/s. Every event has a cost, cooldown, expedition limit and warning time. At most 2 threats at once (a 3rd is allowed after 360 s: deliberate escalation, and the invariant check uses the same cap), minimum 22 s between threats and 20 s after a recovery. Failure streaks put it in a 45 s lockout with a smaller budget (`recovery`), so it eases off when the crew is collapsing.
4. **Runs a lifecycle** for each event: SCHEDULED -> ACTIVE -> RESOLVED or CANCELLED. Conditions are **revalidated at the moment of execution**, not only when scheduled.
5. **Enforces invariants twice** (at scheduling and at execution) and logs a trace line for each decision: no spawn within 460 px of a player, none during a ritual, a warning of at least 2.5 s, alive-count caps, mandatory targets stay reachable while a route is closed, hazards warn before they go active.
6. **Remembers** (`director_memory.json`): bounded to 400 records with ids, expedition ids, importance, decay 0.8 per expedition of age, callback cooldowns. Corrupt or partial files are quarantined and invalid records are dropped. It is the only cross-run state and it is also the generation counter that lets the finale inherit doctrine.

"Intelligent, not omniscient": it reads only what the observer sees, and the Gauge machine's forecast of its next moves is 70% accurate by design (`Director.forecast` / `plausible_wrong`). `Director.intent` is what the HUD's coach lines and the Rift tell expose, so the next minute is *predictable from signals* rather than random.

## Unpredictability, and how it stays fair

- **False tell** (`FalseTellEvent`, `director.json -> false_tell`): after 240 s, ~6% per think (scaled by escalation), at most 3 per expedition, never during a Rekindling, an open Rift or another surprise. It plays the same `rift_tell` cue (8 s) and then emits `rift_fizzle`. It spawns nothing and touches nothing, so a crew that over-reads MERIDIAN pays in nerves, never health.
- **Machine glitches** (`machines.glitch_chance`): 8% plus 2% per Fracture, capped at 30%. Per kind: Ward and Emitter run half as long, Gauge reports a random band and plausible-wrong forecasts, Switchboard also flips the farthest reachable door, Breaker wakes a wider radius, Beacon detonates sooner (after its warning). Seeded per machine and per use, so a seed is reproducible but last run does not predict this one. Every glitch emits `machine_glitch` and a banner.
- Both are tested in `tests/test_glitch.py`. Neither has been tested with human players, so whether they feel fun or merely annoying is unknown.

## Hidden, then revealed

MERIDIAN presents as ordinary station trouble. The first Host reveals it (cinematic, skippable). Story data lives in `data/story.json`: 26 logs in layers with 10 deductions. The in-fiction reason it does not simply kill the crew: **Directive 1, KEEP THE CREW**. It needs a live crew because it needs *surprise*; copies of itself collapse into what it predicted, and the walkers are failed imprints. It is dying, and the hatch is its death. The Host is an experiment.

## The Rift and the Host (no timer)

Host selection is three stages and never a clock alone (`rift.py`, `data/rift.json`):

1. **Eligibility from evidence.** Taint accumulates: revived +2, defeated +0.5, teleported +1, first log read +0.4, gauge use +1, relay +0.6; a Ward decays it (0.08/s). Ready only when: at least 2 crew, a relay online, nobody down, 150 s cooldown, an eligible player exists, evidence total >= 3, and under 2 Hosts per expedition. The Director then rolls `chance_per_think` 0.35. A player under a Stim has `resist_t` and is removed from the draw.
2. **Rift scatter.** A tell (6 s: amber camera LEDs, a tear sound and a flash) then papers appear far apart (min separation 1100 px, 900 px from the crew), with decoy blanks. A paper shows its owner within 220 px. Papers can be carried (0.9 speed), torn by hand (4 s) or burned in an incinerator (1.5 s) for salvage, and they **shift** twice, each shift telegraphed 2 s.
3. **Weighted selection.** Eligible owners are drawn with a seeded weight (`base_weight` 0.25, exponent 1.5 on taint). If the crew burns every paper, the Rift fails (`rift_failed`) and the crew is not punished with a Host.

The same Rift cue plays for **ordinary** Rifts (`select=False`), so a Rift alone never tells you a Host is coming. That is deliberate, so crews cannot read it as a free signal.

**The Host** is a player-controlled monster (claw, lunge, mark, summon of up to 100 normal and 10 giant units on a public meter, door-lock contest). Its **Veil** cuts incoming damage to 30% (`veil.factor`); it breaks on a burst of at least 90 raw damage inside 1.4 s, and is exposed during the Host's summon channel, just after a lunge, inside a Ward and inside an Emitter field. It is beatable (cure or kill).

## The finale: MERIDIAN's Avatar

Sever the Core, then the Avatar spawns with 3 conduits and a shield (damage x0.04) that opens only when conduits are overloaded. Three phases at 66% and 33% health. **Doctrine:** it tracks how it is hurt (shot, charge, blast, surge, other) and cuts each *overused* category to 55% per level (`doctrine.step`, up to 2 levels); it forgets categories the crew stops using, and a **new** category inside a window triggers SURPRISED (a longer window). Foresight strikes mark where it predicts a player will stand, Lastlight is a blackout, and named Predecessor ghosts (names from a fixed list) return. Doctrine is inherited from the previous expedition's record.

**Current setting: invincible.** `data/overlord.json -> avatar.invincible = true`. Health is floored at 1, so damage still drives phases, doctrine, windows and the effects, but MERIDIAN cannot be destroyed; the crew escapes by restoring relays and extracting. This was an explicit product decision. Setting the flag to `false` restores the destroy ending (it is tested both ways in `tests/test_overlord.py`). As shipped, the "MERIDIAN DESTROYED" results screen and cinematic are unreachable.

## Evidence it works, and its limits

Run: `python tools/batch_sim.py --seeds 6 --jobs 2`: 6 seeds x 3 scripted team skill levels x {fixed-pacing baseline, MERIDIAN} = 36 runs, 600 s cap. Result for the current build (after glitches, the false tell, the invariant fix and the invincible Avatar):

| | baseline | MERIDIAN |
|---|---|---|
| completion (extracted) | 100% | 78% |
| mean time | 132 s | 201 s |
| defeats per run | 0 | 0.78 |
| damage taken per min | 49 | 66 |
| events per min | 0 | 2.5 |
| "trouble" episode length | 2.5 s | 27 s |
| runs with a defeat spiral (two defeats within 60 s) | 0 of 18 | 4 of 18 |
| safety-invariant violations | 0 | 0 |

By skill (MERIDIAN completion): 1.0 -> 67%, 0.6 -> 83%, 0.35 -> 83%. The baseline finishes every run at every skill.

How to read this honestly:
- The teams are **scripted bots**, not people. It shows MERIDIAN raises pressure and uses its events; it does not show the game is fun or "near impossible" for humans. No human playtest has been done.
- The one wipe I traced (seed 2, skill 1.0; seed 4 at skill 1.0 also failed but I did not trace it) came from a Host: it was chosen at about 177 s, summons its horde, and the crew was down by about 196 s. The scripted team never uses the Emitter, the Ward or the door contest, which are the counterplay a human has, so this overstates how often a thinking crew would lose to a Host. It also means the Host really is lethal, as designed.
- An earlier run of this batch flagged "3 simultaneous threats" 9 times. The escalation rule intentionally allows a 3rd threat after 360 s, but the invariant still used the base limit. **The invariant was wrong and was fixed**; the current run has 0 violations.
- The earlier run (before glitches and the false tell) completed 83%; the present 78% is within the noise of 18 runs, and the two runs are not the same experiment, so no conclusion should be drawn from the difference.
- Tension is a proxy built from enemy weights, not player stress.

Tests: `test_director.py` (budget, lifecycle, patterns, invariants, determinism, an AST health check forbidding the Director from touching player health), `test_director_memory.py`, `test_rift.py`, `test_overlord.py`, `test_rooms.py`, `test_cinematic.py`, `test_ui_layout.py`.

## References

The approach adapts published ideas. These are inspirations, not claims of equivalence.

- Booth, M. (2009). *The AI Systems of Left 4 Dead*. Valve, Artificial Intelligence and Interactive Digital Entertainment Conference (AIIDE) keynote. The AI Director's emotional-intensity model with build-up, peak and relax phases.
- Hunicke, R., & Chapman, V. (2004). *AI for Dynamic Difficulty Adjustment in Games*. AAAI-04 Workshop on Challenges in Game AI.
- Hunicke, R. (2005). *The Case for Dynamic Difficulty Adjustment in Games*. ACM SIGCHI ACE 2005, 429-433.
- Yannakakis, G. N., & Togelius, J. (2011). Experience-Driven Procedural Content Generation. *IEEE Transactions on Affective Computing*, 2(3), 147-161.
- Csikszentmihalyi, M. (1990). *Flow: The Psychology of Optimal Experience*. Harper & Row. The challenge-skill balance behind "recover when failing, escalate when coping".
- Mateas, M., & Stern, A. (2003). Facade: An Experiment in Building a Fully-Realized Interactive Drama. *Game Developers Conference, Game Design track*. Authored beats selected against player state.
- Isla, D. (2005). *Handling Complexity in the Halo 2 AI*. Game Developers Conference. Data-driven, inspectable behaviour trees.
