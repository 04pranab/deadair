import json

import pygame
import pytest

from src.config import BAL
from src.entities.models import Enemy
from src.settings import TILE
from src.systems import combat, ritual
from src.systems.commands import InputFrame
from src.systems.save import SaveData
from src.systems.story import StoryBook
from src.world import level as L
from src.world.sim import Sim
from tests.helpers import DT, V, press, put, quiet_sim, run

# ---------------------------------------------------------------- level generation

def test_levels_are_deterministic_and_solvable():
    for seed in range(120):
        a, b = L.generate(seed), L.generate(seed)
        assert a.rooms == b.rooms and a.props == b.props and a.enemy_spawns == b.enemy_spawns
        assert L.validate(a) == []
        assert len(a.rooms) == L.GRID_W * L.GRID_H >= 20
        assert 3 <= len(a.relays) <= 5


def test_generated_levels_have_required_objects():
    lv = L.generate(3)
    assert len(lv.anchors) == 2 and lv.anchors[0]["online"] and not lv.anchors[1]["online"]
    assert lv.logs and lv.core and lv.extraction
    assert any(d.kind == "barrier" for d in lv.doors)


# ---------------------------------------------------------------- collision

def test_player_cannot_walk_through_walls():
    s = quiet_sim()
    p = s.players[0]
    for _ in range(300):   # push left for 5 s from the spawn room
        s.update(DT, {0: InputFrame(mx=-1)})
        tx, ty = int(p.pos.x // TILE), int(p.pos.y // TILE)
        assert not s.solids.tile_solid(tx, ty)


def test_closed_doors_and_barriers_are_solid():
    s = quiet_sim()
    barrier = next(d for d in s.doors if d.kind == "barrier")
    s._rebuild_dynamic()
    assert any(r == barrier.rect for r in s.solids.dyn)
    # a body placed against the barrier cannot move into it
    c = V(barrier.rect.center)
    horiz = barrier.spec.horizontal_wall
    start = c + (V(0, -(barrier.rect.h / 2 + 20)) if horiz else V(-(barrier.rect.w / 2 + 20), 0))
    pos, hx, hy, _ = s.solids.move(start, V(0, 40) if horiz else V(40, 0), 13)
    assert hx or hy


def test_no_attacking_through_walls():
    s = quiet_sim()
    p = s.players[0]
    spawn = s.level.rooms[s.level.spawn_room]
    p.pos = V(spawn.x0 * TILE + 14, (spawn.y0 + 3) * TILE + 24)   # hugging the west wall
    p.facing = V(-1, 0)
    muzzle = p.pos + p.facing * (p.radius + 8)
    assert s.solids.point_solid(muzzle.x, muzzle.y)              # the muzzle is inside the wall
    s.bullets.clear()
    combat.fire_player(s, p)
    assert s.bullets == []


def test_bullets_are_cleaned_up():
    s = quiet_sim()
    s.players[0].facing = V(1, 0)
    for _ in range(40):
        s.update(DT, {0: InputFrame(fire=True)})
    run(s, 3.0, {0: InputFrame()})
    assert s.bullets == []


# ---------------------------------------------------------------- combat

def test_enemy_windup_precedes_damage():
    s = quiet_sim(roles=("mara",))
    p = s.players[0]
    e = Enemy("drifter", p.pos + V(30, 0))
    e.state = "chase"
    e.alert_t = 5
    s.enemies.append(e)
    hp0 = p.hp
    for _ in range(int(0.3 / DT)):    # shorter than the 0.45 s wind-up
        s.update(DT, {0: InputFrame()})
    assert p.hp == hp0
    run(s, 1.0, {0: InputFrame()})
    assert p.hp < hp0


def test_dodge_gives_invulnerability_and_cooldown():
    s = quiet_sim(roles=("mara",))
    p = s.players[0]
    s.update(DT, {0: InputFrame(mx=1, dodge=True)})
    assert p.dodge_t > 0 and p.dodge_cd > 0
    hp = p.hp
    assert combat.damage_player(s, p, 20) == 0 and p.hp == hp


def test_post_hit_invulnerability():
    s = quiet_sim(roles=("mara",))
    p = s.players[0]
    assert combat.damage_player(s, p, 10) == 10
    assert combat.damage_player(s, p, 10) == 0


def test_charge_breaks_barrier():
    s = quiet_sim(roles=("dax",))
    barrier = next(d for d in s.doors if d.kind == "barrier")
    p = s.players[0]
    horiz = barrier.spec.horizontal_wall
    p.pos = V(barrier.rect.center) + (V(0, -(barrier.rect.h / 2 + 30)) if horiz else V(-(barrier.rect.w / 2 + 30), 0))
    p.facing = V(0, 1) if horiz else V(1, 0)
    s.update(DT, {0: InputFrame(ability=True)})
    run(s, 0.5, {0: InputFrame()})
    assert barrier.broken


# ---------------------------------------------------------------- Rekindling

def _setup_down(s, idx=1):
    """Defeat player idx where it stands; returns its Echo."""
    combat.defeat_player(s, s.players[idx])
    return next(e for e in s.echoes if e.player_idx == idx)


def test_defeat_creates_single_echo_and_ghost():
    s = quiet_sim()
    e = _setup_down(s)
    assert s.players[1].state == "down" and e.state == "dropped"
    assert len([x for x in s.echoes if x.player_idx == 1]) == 1


def test_full_rekindling_ritual_consumes_resources_and_adds_fracture():
    s = quiet_sim()
    a = s.anchors[0]
    put(s, 0, a.pos + V(60, 0))
    put(s, 1, a.pos + V(60, 20))
    put(s, 2, a.pos + V(-60, 0))
    echo = _setup_down(s, 1)
    echo.pos = V(s.players[0].pos)
    s.team_salvage = 10
    carrier = s.players[0]
    s.update(DT, {0: press(interact=True)})
    assert echo.state == "carried" and carrier.carry is echo
    put(s, 0, a.pos + V(40, 0))
    s.update(DT, {0: press(interact=True)})
    cost = ritual.echo_cost(s)
    assert echo.state == "placed" and a.echo is echo
    assert s.team_salvage == 10 - cost
    hold = {0: press(interact_held=True), 2: press(interact_held=True)}
    run(s, 12, hold)
    p1 = s.players[1]
    assert p1.alive and p1.hp == pytest.approx(p1.max_hp * 0.5, rel=0.05) and p1.weakened
    assert s.fracture == 1 and s.revivals == 1
    assert a.echo is None and echo not in s.echoes
    assert s.team_salvage == 10 - cost       # spent exactly once


def test_no_revival_without_salvage_or_with_offline_anchor():
    s = quiet_sim()
    a_on, a_off = s.anchors[0], s.anchors[1]
    echo = _setup_down(s, 1)
    echo.pos = V(s.players[0].pos)
    s.update(DT, {0: press(interact=True)})          # pick up
    put(s, 0, a_off.pos + V(30, 0))
    s.team_salvage = 99
    s.update(DT, {0: press(interact=True)})
    assert a_off.echo is None and not a_off.online   # offline anchor refuses
    put(s, 0, a_on.pos + V(30, 0))
    s.team_salvage = 0
    s.update(DT, {0: press(interact=True)})
    assert a_on.echo is None and echo.state == "carried"   # not enough salvage
    assert s.team_salvage == 0


def test_no_duplicate_resurrection():
    s = quiet_sim()
    a = s.anchors[0]
    echo = _setup_down(s, 1)
    echo.state, echo.anchor, echo.paid = "placed", a, True
    a.echo = echo
    assert ritual.revive(s, echo) is True
    assert ritual.revive(s, echo) is False
    assert s.revivals == 1 and s.fracture == 1


def test_warden_disrupts_ritual():
    s = quiet_sim()
    a = s.anchors[0]
    put(s, 0, a.pos + V(40, 0))
    echo = _setup_down(s, 1)
    echo.state, echo.anchor, echo.paid, a.echo = "placed", a, True, echo
    w = Enemy("warden", a.pos + V(80, 0))
    w.state = "idle"
    s.enemies.append(w)
    run(s, 5, {0: press(interact_held=True)})
    assert echo.progress == 0.0 and not s.players[1].alive


def test_imani_channels_faster_than_mara():
    def time_to_revive(role):
        s = quiet_sim(roles=(role, "dax"))
        a = s.anchors[0]
        put(s, 0, a.pos + V(40, 0))
        echo = _setup_down(s, 1)
        echo.state, echo.anchor, echo.paid, a.echo = "placed", a, True, echo
        t = 0
        while s.players[1].state == "down" and t < 30:
            s.update(DT, {0: press(interact_held=True)})
            t += DT
        return t
    assert time_to_revive("imani") < time_to_revive("mara") * 0.8


def test_all_players_down_fails_without_softlock():
    s = quiet_sim()
    for p in s.players:
        combat.defeat_player(s, p)
    run(s, 5, {})
    assert s.finished and s.result["status"] == "failed" and s.result["reason"] == "crew_lost"


def test_solo_auto_rekindle_succeeds_with_salvage_and_fails_without():
    s = quiet_sim(roles=("mara",))
    s.team_salvage = 20
    combat.defeat_player(s, s.players[0])
    run(s, 25, {})
    assert s.players[0].alive and s.revivals == 1 and not s.finished
    s2 = quiet_sim(roles=("mara",))
    s2.team_salvage = 0
    combat.defeat_player(s2, s2.players[0])
    run(s2, 8, {})
    assert s2.finished and s2.result["status"] == "failed"


def test_carrier_death_drops_echo():
    s = quiet_sim()
    echo = _setup_down(s, 1)
    echo.pos = V(s.players[0].pos)
    s.update(DT, {0: press(interact=True)})
    assert echo.state == "carried"
    combat.defeat_player(s, s.players[0])
    assert echo.state == "dropped" and echo.carrier is None


# ---------------------------------------------------------------- Fracture and hazards

def test_fracture_bounds_and_stabilization():
    s = quiet_sim()
    s.add_fracture(50)
    assert s.fracture == BAL.fracture.max
    s.add_fracture(-99)
    assert s.fracture == 0
    s.add_fracture(3)
    r = s.relays[0]
    from src.systems import mission
    mission._relay_online(s, r)
    assert s.fracture == 2     # repairs stabilise


def test_surge_is_telegraphed_before_damage():
    s = quiet_sim(roles=("mara",))
    s.fracture = 3
    s.t_surge = 0.0
    p = s.players[0]
    hp0 = p.hp
    s.update(DT, {})
    assert any(t.kind == "surge" for t in s.telegraphs)
    assert p.hp == hp0
    t = next(t for t in s.telegraphs if t.kind == "surge")
    assert t.t >= BAL.fracture.surge_warning - 0.1


def test_door_glitch_never_locks_with_someone_inside():
    s = quiet_sim(roles=("mara",))
    d = next(d for d in s.doors if d.kind == "normal")
    put(s, 0, d.center)
    d.warn_t = 0.05
    run(s, 0.5, {})
    assert d.lock_t == 0.0


# ---------------------------------------------------------------- mission

def test_no_extraction_before_objective():
    s = quiet_sim()
    for i in range(3):
        put(s, i, s.extract_pos + V(10 * i, 0))
    run(s, 5, {})
    assert not s.finished and s.extract_progress == 0.0


def test_extraction_after_objective():
    s = quiet_sim()
    s.objective_done = True
    for i in range(3):
        put(s, i, s.extract_pos + V(10 * i, 0))
    run(s, 5, {})
    assert s.finished and s.result["status"] == "extracted"
    assert s.result["banked"] == s.result["salvage"]


def test_relay_requires_hold_and_decays():
    s = quiet_sim(roles=("mara",))
    r = s.relays[0]
    put(s, 0, r.pos + V(30, 0))
    run(s, 1.0, {0: press(interact_held=True)})
    assert 0 < r.progress < 1
    p = r.progress
    run(s, 1.0, {0: press()})
    assert r.progress < p


def test_mara_repairs_faster():
    def t(role):
        s = quiet_sim(roles=(role,))
        r = s.relays[0]
        put(s, 0, r.pos + V(30, 0))
        n = 0
        while not r.online and n < 20 * 60:
            s.update(DT, {0: press(interact_held=True)})
            n += 1
        return n
    assert t("mara") < t("dax") * 0.7


def test_all_relays_reachable_and_completable_by_bot():
    from src.utils.bot import TeamBot
    s = Sim(11, ["mara", "dax", "imani"])
    bot = TeamBot(s)
    for _ in range(60 * 400):
        if s.finished:
            break
        s.update(DT, bot.frames(DT))
    assert s.finished and s.result["status"] == "extracted"
    assert s.result["relays"] == s.result["relays_total"]


# ---------------------------------------------------------------- story and save

def test_story_pick_is_deterministic_and_prefers_unread():
    sb = StoryBook()
    a = sb.pick_logs(7, set(), 6)
    assert a == sb.pick_logs(7, set(), 6)
    assert sb.logs[a[0]].get("tag") == "archive"
    known = set(sb.logs) - {"menu", "lullaby", "medbay_note", "work_order", "report_official"}
    b = sb.pick_logs(7, known, 6)
    assert {"menu", "lullaby", "medbay_note", "work_order", "report_official"} <= set(b)


def test_deductions_order_independent():
    sb = StoryBook()
    assert sb.unlocked_deductions(["anchor_memo", "protocol_draft"]) == sb.unlocked_deductions(["protocol_draft", "anchor_memo"])
    assert sb.unlocked_deductions(["anchor_memo"]) == []


def test_save_recovers_from_corruption(tmp_path):
    p = tmp_path / "save.json"
    p.write_text("{not json")
    s = SaveData(p)
    assert s.recovered and s.data["bank"] == 0
    assert any(f.name.startswith("save.json.corrupt") for f in tmp_path.iterdir())
    s.save()
    assert json.loads(p.read_text())["version"] == 1


def test_save_rejects_bad_values(tmp_path):
    p = tmp_path / "save.json"
    p.write_text(json.dumps({"bank": -5, "upgrades": {"plating": 99, "fingers": 2}, "runs": [1, {"status": "x"}], "clues": ["a", 3],
                             "settings": {"volume": "loud", "fullscreen": 1}}))
    s = SaveData(p)
    assert s.data["bank"] == 0 and s.upgrades == {"fingers": 2}
    assert s.data["runs"] == [{"status": "x"}] and s.data["clues"] == ["a"]
    assert s.settings["fullscreen"] is False and isinstance(s.settings["volume"], float)


def test_record_run_banks_and_buying_works(tmp_path):
    s = SaveData(tmp_path / "s.json")
    res = {"status": "extracted", "seed": 1, "modifier": "swarm", "time": 100, "salvage": 20, "banked": 20, "revivals": 1, "defeats": 1,
           "kills": 5, "optional_done": True, "relays": 3, "relays_total": 3, "fracture_max": 2, "logs": ["menu"]}
    new = s.record_run(res)
    assert new == ["menu"] and s.data["bank"] == 20
    assert s.buy("plating") and s.data["bank"] == 12 and s.upgrades["plating"] == 1
    assert not s.buy("efficiency")      # 14 > 12


def test_upgrades_apply():
    s = quiet_sim(upgrades={"plating": 2, "efficiency": 1})
    assert s.players[0].max_hp == BAL.roles.mara.hp + 20
    assert ritual.echo_cost(s) == BAL.ritual.base_cost - 1


# ---------------------------------------------------------------- app shell

def test_scenes_transition_headlessly():
    from src.game import Game
    from src.scenes.menus import ArmoryScene, ChronicleScene, CoopSetupScene, MenuScene, SettingsScene, default_coop
    from src.scenes.play import PlayScene, ResultsScene
    g = Game(SaveData(None))
    for cls in (MenuScene, CoopSetupScene, SettingsScene, ArmoryScene, ChronicleScene):
        sc = cls(g)
        g.change(sc)
        sc.update(0.016)
        sc.draw(g.logical)
    cfg = default_coop(g, 2)
    g.save.settings["cinematics"] = False          # story scenes are covered in test_cinematic.py
    play = PlayScene(g, cfg["roles"], cfg["devices"], seed=4)
    g.change(play)
    for _ in range(120):
        play.update(0.016)
        play.draw(g.logical)
    play.sim.team_salvage = 5
    play.sim.finish("extracted")
    for _ in range(200):
        play.update(0.016)
        if isinstance(g.scene, ResultsScene):
            break
    assert isinstance(g.scene, ResultsScene)
    g.scene.draw(g.logical)
    pygame.quit()
