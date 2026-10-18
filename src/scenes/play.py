"""Gameplay scene (fixed-step simulation + rendering) and the post-mission results screen."""
import random

import pygame

from src.config import BAL
from src.settings import save_dir
from src.scenes.base import ListMenu, Scene, draw_backdrop
from src.settings import C_AMBER, C_CYAN, C_DIM, C_GREEN, C_RED, C_TEXT, LOGICAL_H, LOGICAL_W, SIM_DT
from src.systems.commands import InputFrame
from src.ui import draw
from src.ui.fx import Fx
from src.ui.hud import Hud
from src.ui.world_view import WorldView
from src.utils.input_map import InputManager
from src.world.sim import Sim


class PlayScene(Scene):
    def __init__(self, game, roles, devices, seed=None, modifier=None):
        super().__init__(game)
        self.roles, self.devices = roles, devices
        s = game.save
        self.seed = seed if seed is not None else s.next_seed()
        self.modifier = modifier
        self.sim = Sim(self.seed, roles, modifier=modifier, upgrades=s.upgrades, known_logs=s.data["clues"],
                       solo_assist=s.settings["solo_assist"], director=True, director_dir=save_dir())
        self.view = WorldView(self.sim, debug=False)
        self.fx = Fx(shake_enabled=s.settings["shake"])
        self.hud = Hud(self.sim)
        from src.scenes.base import window_to_logical
        self.input = InputManager(devices, mouse_pos=lambda: window_to_logical(game, pygame.mouse.get_pos()),
                                  aim_origin=lambda i: self.view.S(self.sim.players[i].pos) if i < len(self.sim.players) else None)
        self.acc = 0.0
        self.paused = False
        self.pause_menu = ListMenu(game, [["Resume", self.resume, True], ["Restart (new seed)", self.restart, True],
                                          ["Abort to menu", self.abort, True]], top=300)
        self.end_timer = None
        self.intro = [(1.0 + i * 3.2, line) for i, line in enumerate(self.sim.story.opening)]
        self.log_t = 0.0
        self.show_debug = s.settings["debug"]
        self.view.debug = False
        mod = BAL.modifiers[self.sim.modifier]
        self.hud.show_banner(f"SHIFT ZERO  |  {mod['name']}: {mod['desc']}", C_AMBER, 4.0)
        self.game_over = False
        self.cine_ok = bool(s.settings.get("cinematics", True))
        self.intro_done = not self.cine_ok
        self.seen_scenes = set()

    def _play_scene(self, key):
        """Show a skippable story scene, then return to this exact PlayScene (the sim is frozen meanwhile)."""
        if not self.cine_ok or key in self.seen_scenes:
            return False
        from src.scenes.cinematic import CinematicScene
        self.seen_scenes.add(key)
        self.game.change(CinematicScene(self.game, key, self, seed=self.seed))
        return True

    # ---- pause ------------------------------------------------------------------
    def resume(self):
        self.paused = False

    def restart(self):
        self.game.change(PlayScene(self.game, self.roles, self.devices))

    def abort(self):
        from src.scenes.menus import MenuScene
        self.game.change(MenuScene(self.game))

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.paused = not self.paused
                return
            if ev.key == pygame.K_F3:
                self.show_debug = not self.show_debug
                self.view.debug = self.show_debug
        if self.paused:
            self.pause_menu.handle_event(ev)
            return
        if self.hud.log_open and (ev.type == pygame.KEYDOWN or ev.type == pygame.JOYBUTTONDOWN) and self.log_t > 0.6:
            if ev.type == pygame.JOYBUTTONDOWN or ev.key != pygame.K_F3:
                self.hud.log_open = None
        self.input.handle_event(ev)

    # ---- update -----------------------------------------------------------------
    def update(self, dt):
        super().update(dt)
        if self.paused:
            pygame.mouse.set_visible(True)
            return
        if not self.intro_done:
            self.intro_done = True
            if self._play_scene("intro"):
                return
        sim = self.sim
        if not sim.finished:
            frames = self.input.frames()
            if self.fx.hitstop > 0:                     # an impact frame: the world holds for a few ticks
                self.fx.hitstop = max(0.0, self.fx.hitstop - dt)
                dt = 0.0
            self.acc += dt
            first = True
            while self.acc >= SIM_DT and not sim.finished:
                if first:
                    sim.update(SIM_DT, frames)
                    first = False
                else:
                    sim.update(SIM_DT, {k: InputFrame(f.mx, f.my, f.aim_x, f.aim_y, f.fire, False, False, False, f.interact_held)
                                        for k, f in frames.items()})
                self.acc -= SIM_DT
            self._events(sim.drain_events())
        else:
            self._events(sim.drain_events())
            self.end_timer = (self.end_timer or 0.0) + dt
            if self.end_timer > 2.2:
                self._finish()
        pygame.mouse.set_visible(not (self.input.mouse_used and not self.paused and not sim.finished))   # the crosshair replaces the cursor
        self.fx.update(dt)
        self.view.update(dt)
        self.hud.update(dt)
        if self.hud.log_open:
            self.log_t += dt
            if self.log_t > 14:
                self.hud.log_open = None
        while self.intro and self.t >= self.intro[0][0]:
            line = self.intro.pop(0)[1]
            self.hud.say(line["who"], line["text"], 4.5)

    def _events(self, events):
        sim, hud = self.sim, self.hud
        barks = sim.story.barks
        rng = random.Random(self.seed + int(self.t * 10))
        for ev in events:
            self.fx.handle(ev)
            self.game.audio.play(ev["name"])
            n = ev["name"]
            if n == "relay_online":
                hud.say("MARA" if any(p.role == "mara" for p in sim.players) else "CREW", rng.choice(barks["relay_online"]))
                hud.show_banner(f"RELAY ONLINE  {ev['done']}/{ev['total']}", C_GREEN)
            elif n == "objective_complete":
                hud.say("STATION AI", rng.choice(barks["extraction_open"]))
                hud.show_banner("LIFE SUPPORT RESTORED: EXTRACT", C_GREEN, 3.5)
            elif n == "anchor_online":
                hud.say("CREW", "Second Rekindling anchor is powered.")
            elif n == "defeated":
                p = sim.players[ev["player"]]
                hud.say("STATION AI", f"{p.name}: " + rng.choice(barks["defeated"]))
                hud.show_banner(f"{p.name.upper()} IS DOWN: RECOVER THE ECHO", C_CYAN)
            elif n == "revived":
                p = sim.players[ev["player"]]
                hud.say(p.name.split()[0].upper(), rng.choice(barks["revived"]))
                hud.show_banner("REKINDLED. FRACTURE RISES", C_CYAN)
            elif n == "ritual_denied":
                hud.show_banner("CANNOT REKINDLE: " + ev["reason"].upper(), C_RED, 2.0)
            elif n == "ritual_disrupted":
                hud.show_banner("WARDEN DISRUPTS THE RITUAL", C_RED, 1.8)
            elif n == "core_taken":
                hud.say("CREW", rng.choice(barks["core"]))
            elif n == "surge_warning":
                hud.show_banner("POWER SURGE", C_AMBER, 1.2)
            elif n == "spawn_warning":
                hud.show_banner("HOSTILES INBOUND", C_RED, 1.6)
            elif n == "isolate_warning":
                hud.show_banner(f"THE FLOOR IS GOING TO TAKE P{ev['player'] + 1}. STAY TOGETHER", (190, 90, 255), 2.4)
            elif n == "teleport":
                hud.show_banner(f"P{ev['player'] + 1} WAS FOLDED AWAY. FIND THEM", (190, 90, 255), 2.8)
            elif n == "blackout_start":
                hud.show_banner("THE LIGHTS ARE GOING OUT. STAY CLOSE. THE BREAKER BRINGS THEM BACK", C_AMBER, 3.0)
            elif n == "blackout_end":
                hud.show_banner("POWER RETURNS", C_GREEN, 1.6)
            elif n == "seal_warning":
                hud.show_banner("A DOOR IS ABOUT TO SEAL FOR GOOD. FIND ANOTHER WAY", C_AMBER, 2.8)
            elif n == "door_glitch":
                hud.say("STATION AI", rng.choice(barks["glitch"]))
            elif n == "whisper":
                who, _, rest = ev["text"].partition(": ")
                hud.say(who if rest else "UNKNOWN", rest or ev["text"], 7.0)
            elif n == "log_read" and ev["first"]:
                self.hud.log_open = sim.story.logs[ev["log_id"]]
                self.log_t = 0.0
            elif n == "log_read":
                self.hud.log_open = sim.story.logs[ev["log_id"]]
                self.log_t = 0.0
            elif n == "rift_tell":
                hud.show_banner("THE LIGHTS STUTTER. SOMETHING IS ABOUT TO TEAR", C_AMBER, 3.2)
            elif n == "rift_fizzle":
                hud.show_banner("NOTHING TORE. THIS TIME", C_DIM, 2.6)
            elif n == "rift_tear":
                hud.show_banner("THE STATION TEARS. PAPERS WILL SCATTER", (190, 90, 255), 3.0)
            elif n == "rift_open":
                hud.show_banner("RIFT OPEN: FIND THE PAPERS. BURN OR TEAR THEM", (190, 90, 255), 4.0)
            elif n == "rift_shift_warning":
                hud.show_banner("A PAPER IS SLIPPING AWAY", (190, 90, 255), 1.6)
            elif n == "rift_failed":
                hud.show_banner("THE RIFT FAILED. NOBODY WAS CHOSEN", C_GREEN, 3.5)
            elif n == "rift_closed":
                hud.show_banner("THE RIFT CLOSES" + ("  (IT SCARRED THE STATION)" if ev.get("scarred") else ""), C_CYAN, 2.5)
            elif n == "paper_destroyed" and ev.get("reward"):
                hud.show_banner(f"PAPER BURNED  +{ev['reward']} SALVAGE", C_GREEN, 1.8)
            elif n == "machine_used":
                hud.show_banner(sim.machines[[m.id for m in sim.machines].index(ev["machine"])].spec["name"].upper() + " ACTIVE", C_CYAN, 1.4)
            elif n == "machine_glitch":
                hud.show_banner({"flicker": "THE WARD FLICKERS. IT WILL NOT HOLD", "sputter": "THE EMITTER SPUTTERS", "lie": "THE GAUGE STUTTERS. DO YOU TRUST IT?",
                                 "crossed": "THE SWITCHBOARD CROSSED A WIRE. CHECK THE DOORS", "overload": "THE BREAKER SCREAMS. THEY HEARD THAT",
                                 "early": "THE BEACON IS COUNTING WRONG. CLEAR OUT"}[ev["how"]], (255, 150, 60), 3.0)
            elif n == "machine_denied":
                hud.show_banner("NOT ENOUGH SALVAGE" if ev.get("reason") == "salvage" else "NO EFFECT", C_RED, 1.2)
            elif n == "gauge_used":
                hud.show_banner("THE GAUGE READS YOU BACK", C_AMBER, 2.0)
            elif n == "host_veil_broken":
                hud.show_banner("VEIL BROKEN: HIT IT NOW", C_GREEN, 2.0)
            elif n == "overlord_phase":
                hud.show_banner({2: "MERIDIAN HAS READ YOUR HANDS. TURN THE CONDUITS AGAIN", 3: "LASTLIGHT. THE SHIELD CLOSES AGAIN"}[ev["phase"]], C_RED, 4.0)
            elif n == "doctrine_learned":
                hud.show_banner(f"MERIDIAN LEARNED TO IGNORE: {ev['how'].upper()}. TRY SOMETHING ELSE", C_AMBER, 3.5)
            elif n == "doctrine_inherited":
                hud.show_banner("IT REMEMBERS WHAT WORKED LAST TIME", C_AMBER, 3.0)
            elif n == "surprised":
                hud.show_banner("SURPRISED. THE WINDOW OPENS WIDER", C_GREEN, 2.0)
            elif n == "foresight":
                hud.show_banner("IT SAW YOU COMING: MOVE OFF THE CONDUIT", C_RED, 1.4)
            elif n == "predecessors":
                hud.show_banner("THE ONES BEFORE YOU ARE BACK", C_RED, 3.5)
            elif n == "host_born" and not getattr(sim, "reveal_shown", False):
                sim.reveal_shown = True
                self._play_scene("reveal")
            elif n == "mission_end":
                txt = "EXTRACTED" if ev["status"] == "extracted" else "CREW LOST"
                hud.show_banner(txt, C_GREEN if ev["status"] == "extracted" else C_RED, 3.0)
            elif n == "director":
                if ev.get("banner"):
                    hud.show_banner(ev["text"].upper(), C_CYAN, ev.get("ttl", 3.0))
                else:
                    hud.say(ev.get("who", "MERIDIAN"), ev["text"], ev.get("ttl", 6.0))

    def _finish(self):
        if self.game_over:
            return
        self.game_over = True
        res = self.sim.result
        new = self.game.save.record_run(res)
        results = ResultsScene(self.game, res, new, self.roles, self.devices)
        key = {"director_destroyed": "finale", "extracted": "extracted"}.get(res["status"], "lost")
        if self.cine_ok:
            from src.scenes.cinematic import CinematicScene
            self.game.change(CinematicScene(self.game, key, results, seed=self.seed))
        else:
            self.game.change(results)

    # ---- draw -------------------------------------------------------------------
    def draw(self, surf):
        self.view.draw(surf, self.fx)
        self.fx.draw_screen(surf)
        self.hud.draw(surf, self.t, self.view.cam)
        if self.input.mouse_used and not self.paused and not self.sim.finished:
            self._crosshair(surf)
        if self.show_debug:
            self._debug(surf)
        if self.paused:
            s = pygame.Surface((LOGICAL_W, LOGICAL_H), pygame.SRCALPHA)
            s.fill((0, 0, 0, 160))
            surf.blit(s, (0, 0))
            draw.text(surf, "PAUSED", (LOGICAL_W // 2, 220), 70, C_TEXT, "center")
            self.pause_menu.draw(surf)

    def _crosshair(self, surf):
        from src.scenes.base import window_to_logical
        x, y = window_to_logical(self.game, pygame.mouse.get_pos())
        own = self.input._mouse_owner()
        col = self.view.player_color(self.sim.players[own]) if own is not None and own < len(self.sim.players) else (255, 255, 255)
        pygame.draw.circle(surf, (0, 0, 0), (int(x), int(y)), 14, 4)
        pygame.draw.circle(surf, col, (int(x), int(y)), 14, 2)
        for dx, dy in ((-22, 0), (22, 0), (0, -22), (0, 22)):
            pygame.draw.line(surf, (0, 0, 0), (x + dx * 0.55, y + dy * 0.55), (x + dx, y + dy), 4)
            pygame.draw.line(surf, col, (x + dx * 0.55, y + dy * 0.55), (x + dx, y + dy), 2)
        pygame.draw.circle(surf, col, (int(x), int(y)), 2)

    def _debug(self, surf):
        sim = self.sim
        lines = [f"seed {sim.seed}  mod {sim.modifier}  t={sim.time:0.1f}",
                 f"enemies {len(sim.enemies)}  bullets {len(sim.bullets)}  echoes {len(sim.echoes)}",
                 f"fracture {sim.fracture}  salvage {sim.team_salvage}  fps {self.game.clock.get_fps():0.0f}"]
        d = getattr(sim, "director", None)
        if d is not None:
            lines += d.debug_lines()
        y = LOGICAL_H - 20 * len(lines) - 10
        pygame.draw.rect(surf, (0, 0, 0), (LOGICAL_W - 560, y - 6, 550, 20 * len(lines) + 10))
        for i, l in enumerate(lines):
            draw.text(surf, l, (LOGICAL_W - 552, y + i * 20), 18, (180, 255, 180), shadow=False)


class ResultsScene(Scene):
    def __init__(self, game, result, new_clues, roles, devices):
        super().__init__(game)
        self.res, self.new, self.roles, self.devices = result, new_clues, roles, devices
        from src.systems.story import StoryBook
        self.story = StoryBook()
        known = game.save.data["clues"]
        self.deductions = self.story.unlocked_deductions(known)
        self.menu = ListMenu(game, [["New Expedition", self.again, True], ["Main Menu", self.menu_go, True]], top=600, w=320, h=48, gap=8)
        self.menu.rect = lambda i: pygame.Rect(LOGICAL_W // 2 - 340 + i * 360, 640, 320, 52)

    def again(self):
        self.game.change(PlayScene(self.game, self.roles, self.devices))

    def menu_go(self):
        from src.scenes.menus import MenuScene
        self.game.change(MenuScene(self.game))

    def handle_event(self, ev):
        if ev.type == pygame.KEYDOWN and ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_a, pygame.K_d):
            self.menu.sel = 1 - self.menu.sel
            return
        self.menu.handle_event(ev)

    def draw(self, surf):
        r = self.res
        ok = r["status"] == "extracted"
        draw_backdrop(surf, self.t, title=False)
        won = r["status"] == "director_destroyed"
        head = {"extracted": "EXPEDITION COMPLETE", "failed": "CREW LOST", "director_destroyed": "MERIDIAN DESTROYED"}.get(r["status"], "ABORTED")
        sub = {"extracted": "You left. It will wait.", "failed": "Your seed was kept. It always is.",
               "director_destroyed": "The count stops. The label reads: FREE."}.get(r["status"], "")
        draw.text(surf, head, (LOGICAL_W // 2, 70), 80, (255, 215, 110) if won else (C_GREEN if ok else C_RED), "center", maxw=LOGICAL_W - 100)
        if sub:
            draw.text(surf, sub, (LOGICAL_W // 2, 118), 26, C_DIM, "center")
        m, s = divmod(int(r["time"]), 60)
        mod = BAL.modifiers[r["modifier"]]["name"]
        rows = [
            ("Seed / modifier", f"{r['seed']} / {mod}"),
            ("Time", f"{m:02d}:{s:02d}"),
            ("Mandatory objective", f"relays {r['relays']}/{r['relays_total']}"),
            ("Optional: Archive Core", "recovered" if r["optional_done"] else "not recovered"),
            ("Salvage held / banked", f"{r['salvage']} / {r['banked']}" + ("" if ok else "  (25% kept on failure)")),
            ("Defeats / Rekindlings", f"{r['defeats']} / {r['revivals']}"),
            ("Peak Fracture", f"{r['fracture_max']}"),
            ("Hostiles destroyed", f"{r['kills']}"),
        ]
        y = 160
        for k, v in rows:
            draw.text(surf, k, (330, y), 28, C_DIM)
            draw.text(surf, v, (LOGICAL_W - 330, y), 28, C_TEXT, "topright", maxw=LOGICAL_W - 660 - draw.font(28).size(k)[0] - 20)
            y += 38
        y += 14
        draw.text(surf, "Discoveries", (330, y), 30, C_AMBER)
        y += 36
        if self.new:
            for cid in self.new[:4]:
                draw.text(surf, "+ " + self.story.logs[cid]["title"], (350, y), 24, C_CYAN)
                y += 28
        else:
            draw.text(surf, "No new pieces this time.", (350, y), 24, C_DIM)
            y += 28
        if self.deductions:
            draw.text(surf, f"Deductions unlocked: {len(self.deductions)} (see Chronicle)", (350, y + 6), 22, C_AMBER)
        self.menu.draw(surf)
