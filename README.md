# DEAD AIR: SHIFT ZERO (vertical slice)

Local co-op sci-fi action-survival roguelite in Python (pygame-ce). One to four players share one screen (keyboard and/or gamepad). Online multiplayer is **not implemented**; the simulation is deterministic and takes per-player `InputFrame` commands so a network layer can be added later.

All art is from the supplied Kenney ZIPs only (see `docs/ASSET_AUDIT.md`). No art was drawn or generated. There is no audio and no custom font because the ZIPs contain none.

## Install and launch

```
pip install -r requirements.txt        # pygame-ce, Pillow, pytest
python main.py                         # menu
python main.py --play --players 3      # skip the menu
python -m pytest -q                    # tests
```
Headless or CI: `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python main.py --frames 240 --play`.
Bot-driven screenshots: `python tools/screenshot.py <seed> <out_dir> 10,30,60 3`.
Regenerate the asset subset from the ZIPs: `python tools/build_assets.py <extracted_zip_root> .` (`<root>` holds `k1/ k2/ k3/`).
Save and controls files live in `~/.deadair` (override with `DEADAIR_SAVE_DIR`).

## Controls (rebindable in Settings -> Controls)

| Player | Move | Fire | Dodge | Ability | Interact (hold) |
|---|---|---|---|---|---|
| P1 (Keyboard 1) | WASD | F | G | R | E |
| P2 (Keyboard 2) | Arrows | . | / | , | Right Shift |
| P3 (Keyboard 3) | I J K L | U | O | P | Y |
| P4 (Keyboard 4) | Numpad 8 4 5 6 | 1 | 2 | 3 | 0 |

- **Rebind everything in-game:** Settings -> Controls has tabs for Keyboard 1-4, Mouse and Gamepad. Pick a row, press Enter, then press the new key (or click the mouse button, or press the gamepad button). Esc cancels. Duplicates inside one keyboard swap; a key already used by another keyboard is refused; Esc, F3 and F11 are reserved. Saved at once to `controls.json`; applies from the next expedition.
- **Mouse aim:** by default Keyboard 1 owns the mouse. Once you move it, your character aims at the cursor (a crosshair replaces the pointer), left click fires, right click dodges, middle click uses the ability. All of these are rebindable, you can give the mouse to another keyboard, or switch mouse aim off. Without touching the mouse, keyboard play is unchanged (you aim where you move).
- **Gamepad:** left stick move, right stick aim; fire, dodge, ability and interact buttons are rebindable (the right trigger always fires). The mapping is **untested on real hardware**; the rebinding logic is tested with synthetic events.
- Esc pauses, F3 toggles debug, F11 fullscreen.

## What the game contains

- **Expedition.** A seeded station of rooms with non-rectangular shapes (ellipse, octagon, cross, notch, L), doors, relays, Rekindling anchors, an optional Archive Core, log terminals and **machines** (incinerator, ward, gauge, switchboard, breaker, beacon, emitter) that interact with each other and with the monsters. `Level.validate` rejects any layout where a relay, anchor or machine is unreachable, so a bad seed regenerates.
- **Roles.** Mara (Fixer, barricade), Dax (Breacher, charge), Imani (Medic, stim pulse; the stim also makes a player immune to Host selection for its duration).
- **MERIDIAN, the Director.** A deterministic rule-based director (no machine learning) that reads the crew's actual behaviour, spends a budget on telegraphed events and counters repeated play. It starts hidden, is revealed by the first Host, and remembers across expeditions (`director_memory.json`). See `docs/MERIDIAN_DIRECTOR.md`.
- **The Rift and the Host.** A Host is never picked by a timer. Evidence accumulates (revivals, defeats, teleports, gauge use, relays, logs); when the conditions hold, a Rift tears open (with a visible, audible tell), scatters papers far apart, and one paper chooses the Host by seeded weighted draw. Ordinary Rifts also happen without a selection. The Host controls a monster (claw, lunge, mark, door-lock contest, a public summon meter), is protected by a Veil that a burst of damage, a Ward, an Emitter break, as do the Host's own summon channel and the moment after a lunge, and can be cured by the crew.
- **The finale.** Sever the Core, overload three conduits to open the Avatar's shield, and destroy it. It has three phases, learns damage categories (shot, charge, blast, surge, other) and ignores the ones you overuse, is *surprised* by a new one, uses foresight strikes and a blackout, and inherits doctrine from earlier expeditions.
- **Mess and mystery.** Machines glitch more as the station fractures (a Ward flickers, the Gauge lies, a Switchboard crosses a wire, a Beacon counts wrong), always with a banner and sparks. MERIDIAN can also play a **false tell**: the exact Rift cue, then nothing tears. It is harmless by construction. The world's colour grade, drifting motes and light breathing follow a 'dread' value built from Fracture, escalation, a loose Host and the Avatar.
- **Story.** 26 layered logs, deductions, and skippable cinematics (hold to skip; Settings can turn them off). One mode only.
- **Rekindling.** Carry the Echo to a powered anchor, pay salvage, channel the ritual; revival raises the shared Fracture.
- Menu, co-op setup (1-4), armory, chronicle, results, corruption-safe save.
- **Effects.** Hit-stop on heavy impacts, screen shake (Settings: off disables shake and hit-stop), colour washes for phase changes, Veil breaks, Rifts and the Host summon.

## Tests and tools

`python -m pytest -q` runs ~190 tests (rules, monsters, rooms over 40 seeds, Director, memory, Rift/Host, Avatar, cinematics, and a UI overflow audit that renders every menu and HUD state headless and fails on off-screen, spilled or colliding text).
`python tools/ui_audit.py <out_dir>` writes the audited screenshots. `python tools/batch_sim.py` runs the baseline-versus-MERIDIAN batch (see the doc for what the numbers do and do not show).

## Not done

- Online play (the simulation takes per-player `InputFrame`s so a network layer can be added; nothing is implemented). A custom font. True animation sheets: characters switch between 24 supplied poses plus procedural bob/lean/squash. The setup screen offers 4 players (the code scales to 6).
- Gamepad mapping is untested on hardware.
- No human playtest has been done. Every balance number comes from scripted bots, which cannot tell you whether the game is fun or whether the Director is "near impossible" for people.

## Known issues

- Art style is the supplied flat Kenney art plus lighting and effects, not the dark detailed concept image (see `docs/ASSET_AUDIT.md`).
- The cinematics are procedural drawings built from supplied tiles and shapes; they are stylised, not animated film.
