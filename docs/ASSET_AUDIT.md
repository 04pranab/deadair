# DEAD AIR: Asset Audit

Generated from the three supplied ZIPs (`kenney_1.zip`, `kenney_2.zip`, `kenney_3.zip`; 12,600 files, 30 Kenney packs).
`tools/build_assets.py` copies the selected subset into `assets/` and writes `assets/manifest.json` (path, size, mode, source path for every file).

## What the ZIPs contain, and what they do not

- **Only PNG files.** No audio, no fonts, no TMX/JSON maps, no licence text files.
- **Audio gap:** the supplied packs contain no sound files, so the game has no sound. The audio module loads sounds from `assets/audio/` if the person adds them, and does nothing otherwise.
- **Font gap:** no font files were supplied. Text uses pygame's built-in default font. This is a documented gap, not a substitution.
- **Character animation gap:** the supplied `platformer-characters` pack has five characters (Adventurer, Female, Player, Soldier, Zombie), each as 24 single front/side poses of 80x110 px (idle, stand, walk1/2, back, hold1/2, action1/2, hurt, duck, slide, kick, cheer1/2, fall, climb, swim and others). There are no sprite sheets or true animation strips. The game animates by switching pose frames (walk1/walk2 at 8 fps, aim pose, action, hurt, duck for dodge, slide for charge, hold2 for carrying an Echo, cheer for the ritual, fall for downed) and adds procedural bob, squash, lean and mirroring. Weapons are not drawn: the packs have no weapon sprites for these characters, so shots come from a muzzle flash and the aim pip.
- **Only five character bodies:** the six enemy types and three crew roles reuse them. Crew = Female (Mara), Soldier (Dax), Player (Imani). Enemies = Zombie (Husk, Skitter, Brute, Warden) and Adventurer (Sentry, Spitter), separated by tint and scale. That is a reuse limit of the supplied art, not new art.
- **Style gap against the concept image:** the concept image is dark, detailed, neon-lit pixel art with spacesuit crew and alien enemies. No supplied pack contains that art. The game uses the supplied flat Kenney art and approaches the mood with darkened lighting, light masks, glows, particles and colour grading.
- **Perspective:** `space-station-kit` and `modular-space-kit` are 3D model kits. Only 64x64 isometric preview renders of single pieces are PNGs. They are used for the menu backdrop and the extraction gate. The playable map stays top-down (the person asked to keep the map the same); only the characters use the 2.5D side-view pose art. An earlier isometric prototype of the whole map was built from these renders and dropped at the person's request.

## Licences

No licence file exists in the ZIPs. The bundled `Preview.png` images of `space-station-kit`, `tiny-factory`, `particle-pack`, `light-masks` and `ui-pack-space-expansion` state: "CC0 1.0. This content is free to use in personal, educational and commercial projects. Written permission not required, support us by crediting or donating (voluntary)." Copies are in `assets/licenses/`.
`platformer-characters`, `top-down-shooter` (no longer used) and `game-icons` have no preview image or licence text in the supplied files, so their licence is **not verifiable from the ZIP**. Kenney's published terms are at https://kenney.nl/support; check them before release.
Attribution is voluntary under CC0; the game's credits screen credits Kenney (kenney.nl).

## Selected subset (copied to `assets/`)

| Group (assets/...) | Files | Source in ZIP | Sizes (WxH: count) |
|---|---|---|---|
| `hub/factory` | 132 | `k3/kenney_tiny-factory/standalone_tiles/Tiles` | 16x16: 132 |
| `chars2d` | 120 | `k2/kenney_platformer-characters/standalone_tiles/PNG/*/Poses` | 80x110: 120 |
| `hub/modular` | 40 | `k2/kenney_modular-space-kit_1.0/standalone_tiles/Previews` | 64x64: 40 |
| `fx/particles` | 80 | `k2/kenney_particle-pack/standalone_tiles/PNG (Transparent)` | 512x512: 80 |
| `fx/lights` | 152 | `k1/kenney_light-masks-1.0/standalone_tiles/Transparent` | 512x512: 152 |
| `ui/blue` | 60 | `k3/kenney_ui-pack-space-expansion/standalone_tiles/PNG/Blue/Default` | 12x24: 8, 24x24: 8, 8x16: 8, 16x16: 8, 192x64: 8, 64x64: 8 |
| `ui/red` | 60 | `k3/kenney_ui-pack-space-expansion/standalone_tiles/PNG/Red/Default` | 12x24: 8, 24x24: 8, 8x16: 8, 16x16: 8, 192x64: 8, 64x64: 8 |
| `ui/icons` | 105 | `k1/kenney_game-icons/sheet_white1x` | 50x50: 105 |
| `hub/station` | 97 | `k3/kenney_space-station-kit/standalone_tiles/Previews` | 64x64: 97 |

## Packs inspected and not used

`animal-pack-remastered`, `background-elements`, `block-pack`, `desert-shooter-pack`, `fish-pack`, `flag-pack`, `generic-items`, `input-prompts`, `isometric-vehicles`, `map-pack`, `minimap-pack`, `modular-characters`, `particle-pack` rotated variants, `platformer-art-requests`, `puzzle-pack-2`, `roguelike-*` (bright, light-coloured medieval/city art that clashes with the dark factory set), `sci-fi-rts` (Mars terrain and small units, not station interiors), `ui-pack` (non-space variant).

## Chosen visual style

Top-down map with 2.5D character art:

| Role | Pack | Notes |
|---|---|---|
| Floors, walls, props, terminals, crates, hazard stripes, siren | `tiny-factory` (16x16) | Dark plum floor and steel panels suit a dark station. Drawn at 3x nearest-neighbour (48 px). |
| Crew and enemies | `platformer-characters` poses (80x110, drawn at 0.6x = 48x66 px) | Smooth cartoon art on a pixel-art map. Documented style mismatch. |
| Effects | `particle-pack` (512 px) | Muzzle flash, sparks, smoke, flames, circles, scaled down. |
| Lighting | `light-masks` (512 px) | Radial and cone masks for the darkness and light pass. |
| HUD and menus | `ui-pack-space-expansion` Blue and Red, `game-icons` white | Bars, buttons, crosshair, icons. |
| Menu backdrop, extraction gate | `space-station-kit` and `modular-space-kit` previews | Isometric 64x64 renders, not used for the playable floor. |

## Entity to asset mapping

| Entity | Asset (under `assets/`) |
|---|---|
| Mara, the Fixer | `chars2d/Female/Poses/female_*.png` |
| Dax, the Breacher | `chars2d/Soldier/Poses/soldier_*.png` |
| Imani, the Medic | `chars2d/Player/Poses/player_*.png` |
| Husk (pursuer), Skitter (fast swarmer), Brute (mid heavy), Warden (boss heavy, 1.45x) | `chars2d/Zombie/Poses/zombie_*.png` with tint and scale |
| Sentry (ranged), Spitter (3-shot burst) | `chars2d/Adventurer/Poses/adventurer_*.png` with tint |
| Floor / walls / doors / frames | `hub/factory/tile_0003`, `0032`, `0011`, `0007-0008`, `0019-0023`, `0044-0047` (walls, closed doors), `0117/0118` (open door strip, barrier) |
| Loot and cover | `tile_0073`, `0085` (crates), `0072`, `0084` (lockers), `0097`, `0126` (barrels), `0123` (toolbox) |
| Terminals / objectives | `tile_0075` (relay offline), `0099` (relay online), `0112` (log terminal), `0123` (Archive Core chest) |
| Revival anchor | `tile_0130` (blue energy item) plus `fx/lights/circle_rings_*` and `fx/particles/magic_*` |
| Alarm / hazard | `tile_0129` (siren), `0117-0119` (hazard stripes), `fx/particles/spark_*` |
| Extraction point | `hub/modular/gate-door` and `gate-lasers` previews plus a pulsing ring; barricade ability uses `tile_0124` |
| Muzzle / hits / dash | `fx/particles/muzzle_*`, `spark_*`, `smoke_*`, `trace_*` |
| HUD | `ui/blue/bar_*`, `ui/red/bar_*`, `ui/icons/*`, `ui/blue/crosshair_color_*` |

Tile indices are verified against `assets/hub/factory` contact sheets during implementation. Any mapping that turns out wrong will be corrected here.

## Addendum: effects, machines and cinematics

No new image files were added. Machines, papers, the Rift, the Veil, the Avatar overlay, hit-stop flashes and the cinematics are drawn at run time from the supplied tiles, particle masks (`fx/particles`), light masks (`fx/lights`), the 64x64 modular-kit previews, game icons and pygame primitives (lines, ellipses, polygons). They are procedural, so they carry the supplied art's flat look; they are not hand-painted art. The cinematics (`src/ui/cine_art.py`) are staged stills with camera moves and text, not animation sheets.
