# DEAD AIR: SHIFT ZERO

**A local co-op sci-fi action-survival roguelite built with Python and pygame-ce.**

The station is failing. The systems are lying. Something inside the Rift is learning how your crew fights.

Dead Air: Shift Zero is a playable vertical slice about surviving a fractured station together. Up to four players share one screen, operate interconnected machines, revive fallen teammates, uncover the station's story, and face a finale shaped by earlier expeditions.

> **Release status:** Baseline release for the current vertical slice. Local play is implemented; online multiplayer is not.

## At a glance

- **Genre:** Sci-fi action-survival roguelite
- **Players:** 1-4 on one computer
- **Technology:** Python, pygame-ce
- **Input:** Keyboard, mouse, and configurable gamepad controls
- **Structure:** Seeded expeditions through interconnected station rooms
- **Director:** MERIDIAN, a deterministic rule-based system, not machine learning
- **Story:** Layered logs, deductions, and skippable cinematics
- **License:** MIT
- **Art:** Supplied Kenney asset packs only; see [the asset audit](docs/ASSET_AUDIT.md)

## Features

### Explore a station that pushes back

Each expedition assembles a seeded station from varied room shapes, connected doors, relays, anchors, terminals, and machines. Layout validation checks critical objectives for reachability and regenerates invalid layouts. Machines include an incinerator, ward, gauge, switchboard, breaker, beacon, and emitter. Their behaviour can change as the station fractures.

### Work as a crew

- **Mara, the Fixer:** deploys a barricade.
- **Dax, the Breacher:** uses a charge.
- **Imani, the Medic:** sends out a stim pulse that also protects a player from Host selection for its duration.

Coordinate movement, firing, dodging, abilities, interactions, and revivals. Rekindling a fallen teammate requires carrying their Echo to a powered anchor, paying salvage, and completing the channel. Revival raises shared Fracture.

### Survive MERIDIAN

MERIDIAN observes crew behaviour, allocates a budget to telegraphed events, and counters repeated tactics. It begins hidden, is revealed by the first Host, and retains memory across expeditions. More details are in [MERIDIAN Director notes](docs/MERIDIAN_DIRECTOR.md).

The Rift and Host systems use accumulated evidence rather than a simple timer. When conditions are met, a Rift opens with a visible cue; scattered papers determine the Host through a seeded weighted draw. Other Rifts can occur without selecting a Host. The Host controls a monster with attacks and objectives of its own. The crew can contest its actions, break its protections, and work toward a cure. MERIDIAN can also produce a harmless false Rift tell.

### Face the finale

Sever the Core, overload three conduits to expose the Avatar's shield, and destroy the Avatar across three phases. The encounter responds to the damage categories used by the crew, with foresight strikes and blackout events. Its doctrine can carry over from earlier expeditions.

### Uncover the story

Find layered logs and deductions throughout the station. Cinematics can be skipped by holding the skip control or disabled in Settings. This build contains one game mode.

### Make it yours

- Rebind keyboard, mouse, and gamepad controls in Settings.
- Configure one to four players from the menu.
- Use the armory, chronicle, and results screens between expeditions.
- Adjust effects and screen shake in Settings.
- Saves are stored separately from the project and include corruption protection.

## Requirements and installation

Install Python 3 and the dependencies listed in requirements.txt:

```bash
python -m pip install -r requirements.txt
```

## Run the game

Launch the menu:

```bash
python main.py
```

Start an expedition directly with three players:

```bash
python main.py --play --players 3
```

Run the tests:

```bash
python -m pytest -q
```

Run a headless smoke test:

```bash
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python main.py --frames 240 --play
```

Generate bot-driven screenshots:

```bash
python tools/screenshot.py <seed> <out_dir> 10,30,60 3
```

Rebuild the asset subset from extracted Kenney packs. The extracted root should contain k1/, k2/, and k3/:

```bash
python tools/build_assets.py <extracted_zip_root> .
```

Run the UI audit and write screenshots:

```bash
python tools/ui_audit.py <out_dir>
```

Run the baseline-versus-MERIDIAN batch simulation:

```bash
python tools/batch_sim.py
```

Scripted outcomes help compare deterministic scenarios; they are not evidence of human enjoyment or balanced difficulty.

## Controls

Controls can be rebound in **Settings → Controls**. Select a row, press Enter, then press the new key or button. Esc cancels. Duplicate bindings on the same keyboard swap; a key already used by another keyboard is refused. Esc, F3, and F11 are reserved. Changes save immediately and apply from the next expedition.

| Player | Move | Fire | Dodge | Ability | Interact (hold) |
|---|---|---|---|---|---|
| P1 | WASD | F | G | R | E |
| P2 | Arrow keys | . | / | , | Right Shift |
| P3 | I J K L | U | O | P | Y |
| P4 | Numpad 8 4 5 6 | 1 | 2 | 3 | 0 |

**Mouse:** Keyboard 1 owns mouse aim by default. Move the mouse to aim; left-click fires, right-click dodges, and middle-click uses the ability. These bindings can be changed, the mouse can be assigned to another keyboard, or mouse aim can be disabled. If the mouse is untouched, keyboard aim follows movement.

**Gamepad:** The left stick moves and the right stick aims. Fire, dodge, ability, and interact can be rebound; the right trigger always fires. Real gamepad hardware testing has not been completed.

**Global keys:** Esc pauses, F3 toggles debug display, and F11 toggles fullscreen.

## Tests and validation

The test suite covers game rules, monsters, room generation across multiple seeds, MERIDIAN and its memory, Rift/Host selection, the Avatar, cinematics, and UI layout. The UI overflow audit renders menu and HUD states headlessly and checks for off-screen, overflowing, or colliding text.

```bash
python -m pytest -q
```

The project also includes screenshot generation, UI auditing, and scripted batch simulation. These tools help catch regressions but do not replace hands-on playtesting.

## Known limitations

- **No online multiplayer.** The simulation accepts per-player InputFrame commands, which could support a future network layer, but no network layer or online mode is implemented.
- **Player setup is limited to 1-4.** Some underlying code scales to six players, but the setup screen exposes four.
- **Gamepad support is not hardware-verified.** Rebinding logic has been exercised with synthetic events.
- **No human playtest has been completed.** Current balance observations come from scripted bots, which cannot establish whether the game is fun, fair, or too difficult.
- **Visuals use supplied Kenney art.** Lighting and effects add atmosphere, but the art does not match a dark, highly detailed concept painting.
- **Cinematics are stylised procedural compositions** built from supplied tiles and shapes, not full animated films.
- **No custom font or audio is included** in the supplied asset packs.
- Character animation uses supplied poses and procedural movement effects rather than full custom animation sheets.

## Data and saves

Save data and controls are stored under ~/.deadair by default. Set the DEADAIR_SAVE_DIR environment variable to use another location.

## Project documentation
- [MERIDIAN Director notes](docs/MERIDIAN_DIRECTOR.md)

## Contributing and feedback

Bug reports, reproducible issues, and focused suggestions are welcome through GitHub Issues. Include your operating system, Python version, steps to reproduce, and relevant error output. Please distinguish verified behaviour from future plans, especially regarding online multiplayer and gamepad hardware validation.

## License

This project is released under the MIT License. See [LICENSE](LICENSE).

---

*Dead Air: Shift Zero is a work in progress. This release establishes the current playable local-co-op vertical slice, with known limitations documented above.*
