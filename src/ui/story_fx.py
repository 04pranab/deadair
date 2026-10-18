"""Story-bearing visuals for the world view: the Host, the Director's cameras, residues of the crew that came before,
sealed and contested doors, Host/isolation telegraphs, the Avatar and its conduits. All art is the supplied Kenney packs
(character poses, tiles, lights, particles, icons); only geometry (rings, lines) and tints are procedural."""
import math
import random

import pygame

from src.settings import C_AMBER, C_CYAN, C_GREEN, C_RED, TILE
from src.ui import anim, draw
from src.world.level import FLOOR, MAP_H, MAP_W

V = pygame.Vector2
VIOLET = (190, 90, 255)
BLOOD = (255, 60, 70)
CHARS = ["Player", "Female", "Adventurer", "Soldier"]


# ====================================================================== static story dressing (deterministic per seed)
def build_dressing(sim):
    """Surveillance cameras on walls and 'residues': replays of the crew that came before, standing where they last were."""
    lvl = sim.level
    rng = random.Random(lvl.seed * 77 + 5)
    cams, residues = [], []
    for r in lvl.rooms:
        if r.id == lvl.spawn_room:
            continue
        n_cam = rng.choice([1, 1, 2])
        tops = [(x, r.y0 - 1) for x in range(r.x0 + 1, r.x1 - 1) if lvl.grid[r.y0 - 1][x] != FLOOR]
        for _ in range(n_cam):
            if tops:
                x, y = tops.pop(rng.randrange(len(tops)))
                cams.append({"pos": V(x * TILE + TILE / 2, y * TILE + TILE - 6), "room": r.id, "phase": rng.random() * 6.28})
        if rng.random() < 0.55:
            cx, cy = r.center
            for _ in range(10):
                x = rng.randint(r.x0 + 2, r.x1 - 3)
                y = rng.randint(r.y0 + 2, r.y1 - 3)
                if lvl.grid[y][x] == FLOOR and not lvl.blocked[y][x]:
                    break
            else:
                continue
            script = rng.choice(["pound", "terminal", "crawl", "watch", "run", "kneel"])
            residues.append({"pos": V(x * TILE + TILE / 2, y * TILE + TILE / 2), "char": rng.choice(CHARS), "script": script,
                             "room": r.id, "phase": rng.random() * 6.28, "gone": False, "fade": 1.0, "flip": rng.random() < 0.5})
    return cams, residues


def _near_player(sim, pos, rad):
    return min((p.pos.distance_to(pos) for p in sim.players if p.alive), default=1e9) < rad


def draw_residues(view, surf):
    sim = view.sim
    t = view.t
    for r in view.residues:
        s = view.S(r["pos"])
        if not view.on_screen(s, 80):
            continue
        d = min((p.pos.distance_to(r["pos"]) for p in sim.players if p.alive), default=1e9)
        if d < 130 and not r["gone"]:
            r["gone"] = True
            view.fx_events.append(("residue_gone", V(r["pos"])))
        if r["gone"]:
            r["fade"] = max(0.0, r["fade"] - 0.03)
            if r["fade"] <= 0:
                continue
        reveal = 1.0 if sim.exposed else 0.6
        flick = 0.55 + 0.45 * math.sin(t * 13 + r["phase"]) * (1.0 if int(t * 7 + r["phase"] * 3) % 9 else 0.2)
        alpha = int(150 * reveal * max(0.0, flick) * r["fade"])
        if alpha < 8:
            continue
        sc = r["script"]
        pose, flip, bob, dx = "idle", r["flip"], 0.0, 0.0
        if sc == "pound":
            pose = "action1" if int(t * 3 + r["phase"]) % 2 == 0 else "action2"
        elif sc == "terminal":
            pose = "hold1"
        elif sc == "crawl":
            pose = "fall"
            bob = 4
        elif sc == "kneel":
            pose = "duck"
        elif sc == "run":
            dx = math.sin(t * 0.9 + r["phase"]) * 60
            pose = "walk1" if int(t * 8) % 2 == 0 else "walk2"
            flip = math.cos(t * 0.9 + r["phase"]) < 0
        elif sc == "watch":
            pose = "idle"
        if sim.exposed and sc != "run":
            tgt = min((p.pos for p in sim.players if p.alive), key=lambda q: q.distance_to(r["pos"]), default=None)
            if tgt is not None:
                flip = tgt.x < r["pos"].x                      # after the reveal every residue turns to look at you
        look = anim.Look(pose, flip, bob, 1, 1, (150, 235, 255), (0, 50, 90), alpha)
        anim.draw_look(surf, (s[0] + dx, s[1]), r["char"], look, 1.0)
        if sc == "crawl":
            g = view.A.glow("circle_b", 70, (90, 20, 30), 1.0)
            surf.blit(g, (s[0] - 35, s[1] - 28), special_flags=pygame.BLEND_RGB_ADD)


def draw_cameras(view, surf):
    """The Director's eyes. Before the reveal they read as ordinary station cameras with a slow red LED; after it they sweep a
    cone of light toward the nearest crew member."""
    sim = view.sim
    for c in view.cams:
        s = view.S(c["pos"])
        if not view.on_screen(s, 60):
            continue
        img = view.A.icon("video", 22, (200, 60, 70) if sim.exposed else (120, 130, 150))
        surf.blit(img, (s[0] - 11, s[1] - 14))
        led_on = int(view.t * (3.0 if sim.exposed else 0.7) + c["phase"]) % 2 == 0
        if led_on:
            pygame.draw.circle(surf, (255, 190, 60) if sim.rift.tell_until > sim.time else (255, 60, 60), (int(s[0] + 9), int(s[1] - 12)), 2 if sim.rift.tell_until <= sim.time else 3)
        if sim.exposed:
            tgt = min((p.pos for p in sim.players if p.alive), key=lambda q: q.distance_to(c["pos"]), default=None)
            if tgt is not None and tgt.distance_to(c["pos"]) < 800 and sim.solids.los(c["pos"], tgt):
                a = math.atan2(tgt.y - c["pos"].y, tgt.x - c["pos"].x)
                pts = [c["pos"], c["pos"] + V(math.cos(a - 0.16), math.sin(a - 0.16)) * 420, c["pos"] + V(math.cos(a + 0.16), math.sin(a + 0.16)) * 420]
                view.ground_poly(surf, pts, (255, 70, 90), 26, 0)


# ====================================================================== the Host
def draw_host(view, surf, p):
    sim = view.sim
    h = p.host
    s = view.S(p.pos)
    if not view.on_screen(s, 120):
        return
    t = view.t
    view.shadow(surf, p.pos, p.radius + 8, 130)
    # aura
    pulse = 0.5 + 0.5 * math.sin(t * 5)
    g = view.A.glow("circle_b", int(170 + 40 * pulse), (150, 25, 40), 1.0)
    surf.blit(g, (s[0] - g.get_width() / 2, s[1] - g.get_height() / 2 - 20), special_flags=pygame.BLEND_RGB_ADD)
    view.ground_ellipse(surf, p.pos, 40 + 6 * pulse, BLOOD, 30, 3)
    # the summon meter is public: the crew can read how close the horde is (an arc that fills, then a crown that throbs)
    if h.charge > 0.02:
        a0 = -math.pi / 2
        n = max(2, int(24 * h.charge))
        pts = [view.S(p.pos + V(math.cos(a0 + i * math.tau * h.charge / n), math.sin(a0 + i * math.tau * h.charge / n)) * 54) for i in range(n + 1)]
        pygame.draw.lines(surf, (255, 90, 90) if h.charge >= 1 else (190, 60, 80), False, pts, 3)
        if h.charge >= 1.0 and h.summon_cd <= 0:
            for i in range(5):
                ang = t * 3 + i * math.tau / 5
                q = view.S(p.pos + V(math.cos(ang), math.sin(ang)) * (60 + 8 * pulse))
                pygame.draw.circle(surf, (255, 70, 70), (int(q[0]), int(q[1])), 4)
    if h.hold > 0:                                           # summoning: converging ring
        k = min(1.0, h.hold / 1.6)
        view.ground_ellipse(surf, p.pos, 260 * (1 - k) + 40, BLOOD, 30, 4)
    if h.lunge_t > 0:
        for i in range(1, 4):
            ghost = anim.Look("slide", p.facing.x < 0, 0, 1.2, 0.9, (255, 70, 70), (80, 0, 0), 120 - 30 * i)
            gs = view.S(p.pos - h.lunge_dir * 22 * i)
            anim.draw_look(surf, gs, "Zombie", ghost, 1.5)
    if h.swing > 0:
        k = 1 - h.swing / 0.25
        a0 = math.atan2(p.facing.y, p.facing.x)
        pts = [p.pos] + [p.pos + V(math.cos(a0 + o), math.sin(a0 + o)) * (96 * (0.5 + 0.5 * k)) for o in (-0.65, -0.3, 0.0, 0.3, 0.65)]
        view.ground_poly(surf, pts, BLOOD, int(150 * (1 - k)), 2)
    flip, away = anim.facing_info(p.facing)
    if p.flash > 0.05:
        look = anim.Look("hurt", flip, 0, 1, 1, (255, 120, 120), (120, 60, 60))
    elif h.swing > 0:
        look = anim.Look("action1" if h.swing > 0.12 else "action2", flip, 0, 1.12, 0.92, (255, 90, 90), None)
    elif h.roar > 0:
        look = anim.Look("cheer1" if int(t * 10) % 2 == 0 else "cheer2", flip, math.sin(t * 40) * 2, 1.05, 1.05, (255, 70, 70), (70, 0, 0))
    elif p.moving:
        fr = "walk1" if int(sim.time * 10) % 2 == 0 else "walk2"
        look = anim.Look("back" if away else fr, flip, abs(math.sin(sim.time * 10 * math.pi)) * 4, 1, 1, (255, 90, 90), (40, 0, 0), lean=3)
    else:
        look = anim.Look("back" if away else "idle", flip, 0, 1, 1 + 0.03 * math.sin(t * 3), (255, 90, 90), (30, 0, 0))
    rect = anim.draw_look(surf, s, "Zombie", look, 1.55)
    draw_veil(view, surf, p)
    # the person underneath: a faint player-colour ring so the controller can find themselves
    col = view.player_color(p)
    pygame.draw.ellipse(surf, col, pygame.Rect(s[0] - 26, s[1] - 10, 52, 20), 3)
    view.labels.append(lambda sf, p=p, r=rect: _host_label(sf, p, r))


def _host_label(surf, p, r):
    w = 120
    x, y = int(r.centerx - w / 2), int(r.top - 18)
    pygame.draw.rect(surf, (30, 12, 18), (x - 2, y - 2, w + 4, 10))
    pygame.draw.rect(surf, BLOOD, (x, y, int(w * max(0.0, p.hp) / p.max_hp), 6))
    draw.text(surf, "THE HOST", (r.centerx, y - 20), 20, BLOOD, "center")


def draw_mark(view, surf):
    sim = view.sim
    if sim.host is None or sim.horde_idx is None or sim.horde_t <= 0:
        return
    t = sim.players[sim.horde_idx]
    if not t.alive:
        return
    s = view.S(t.pos)
    k = min(1.0, sim.horde_t / 12.0)
    view.ground_ellipse(surf, t.pos, 34 + 8 * math.sin(view.t * 9), BLOOD, 40, 4)
    surf.blit(view.A.icon("target", 34, BLOOD), (s[0] - 17, s[1] - 78))
    h = sim.host
    pygame.draw.line(surf, (255, 60, 70), view.S(h.pos), s, 1)
    pygame.draw.rect(surf, (40, 10, 14), (s[0] - 22, s[1] - 44, 44, 4))
    pygame.draw.rect(surf, BLOOD, (s[0] - 22, s[1] - 44, int(44 * k), 4))


# ====================================================================== telegraphs
def draw_telegraph(view, surf, t):
    k = 1 - t.t / t.total
    s = view.S(t.pos)
    if t.kind == "host":
        r = 60 + 14 * math.sin(view.t * 16)
        view.ground_ellipse(surf, t.pos, r * (1.2 - 0.4 * k), VIOLET, 40 + int(60 * k), 3)
        for i in range(6):                                   # rotating glyph spokes that tighten as the time runs out
            a = view.t * (2 + 6 * k) + i * math.tau / 6
            p1 = t.pos + V(math.cos(a), math.sin(a)) * (r * 1.3)
            p2 = t.pos + V(math.cos(a + 0.5), math.sin(a + 0.5)) * (r * 0.5)
            pygame.draw.line(surf, VIOLET, view.S(p1), view.S(p2), 2)
        surf.blit(view.A.icon("video", 36, (255, 70, 90)), (s[0] - 18, s[1] - 96))
    elif t.kind == "isolate":
        for i in range(3):
            rr = 70 * (1 - ((k * 2 + i / 3) % 1.0))
            view.ground_ellipse(surf, t.pos, max(6, rr), C_CYAN, 18, 2)
        surf.blit(view.A.icon("signal3", 30, C_CYAN), (s[0] - 15, s[1] - 76))
    elif t.kind == "wave" and t.payload and len(t.payload) > 4:
        view.ground_ellipse(surf, t.pos, 52 + 10 * math.sin(view.t * 12), BLOOD, 36, 3)
        surf.blit(view.A.icon("warning", 30, BLOOD), (s[0] - 15, s[1] - 44))
        draw.text(surf, f"{t.t:0.1f}", (s[0], s[1] + 18), 18, BLOOD, "center")
    else:
        return False
    return True


def host_jitter(view):
    """player idx -> jitter amplitude while a Host conversion is being telegraphed on them."""
    out = {}
    for t in view.sim.telegraphs:
        if t.kind == "host":
            for p in view.sim.players:
                if p.alive and p.pos.distance_to(t.pos) < 4:
                    out[p.idx] = 1.0 + 4.0 * (1 - t.t / t.total)
    return out


# ====================================================================== doors
def draw_door_state(view, surf, d, s0):
    if d.sealed:
        surf.blit(view.A.icon("cross", 34, BLOOD), (s0[0] - 17, s0[1] - 18))
        view.labels.append(lambda sf, c=s0: draw.text(sf, "SEALED", (c[0], c[1] - 40), 16, BLOOD, "center"))
        return True
    if d.crew_lock:
        surf.blit(view.A.icon("locked", 30, C_CYAN), (s0[0] - 15, s0[1] - 16))
        c = d.contest
        view.labels.append(lambda sf, c0=s0, v=c: _contest_bar(sf, c0, v))
        return True
    return False


def _contest_bar(surf, c, v):
    w = 64
    x, y = int(c[0] - w / 2), int(c[1] - 44)
    pygame.draw.rect(surf, (20, 24, 36), (x - 2, y - 2, w + 4, 10))
    pygame.draw.rect(surf, C_CYAN, (x, y, w, 6))
    pygame.draw.rect(surf, BLOOD, (x, y, int(w * min(1.0, v)), 6))
    draw.text(surf, "HOLD THE DOOR", (c[0], y - 14), 14, C_CYAN, "center")


# ====================================================================== the finale
def draw_overlord_ground(view, surf):
    sim = view.sim
    ov = sim.overlord
    if ov.stage != 2:
        return
    for c in ov.conduits:
        col = C_GREEN if c.ready else (90, 90, 110)
        view.ground_ellipse(surf, c.pos, 46 + 4 * math.sin(view.t * 4 + c.id), col, 30, 3)
        if c.progress > 0:
            view.ground_ellipse(surf, c.pos, 46 * c.progress, col, 70, 2)


def draw_conduit(view, surf, c):
    s = view.S(c.pos)
    if not view.on_screen(s, 100):
        return
    view.tile(surf, 130, c.pos, None if c.ready else (90, 90, 110), size=TILE + 20, dy=4 + 3 * math.sin(view.t * 3 + c.id))
    g = view.A.glow("circle_b", 120, (60, 200, 255) if c.ready else (40, 40, 60), 1.0)
    surf.blit(g, (s[0] - 60, s[1] - 60), special_flags=pygame.BLEND_RGB_ADD)
    view.labels.append(lambda sf, c=c, s=s: _conduit_label(sf, c, s))


def _conduit_label(surf, c, s):
    draw.text(surf, f"CONDUIT {c.id + 1}" + ("" if c.ready else f"  {c.cool:0.0f}s"), (s[0], s[1] + 34), 16, C_GREEN if c.ready else (140, 140, 150), "center")
    if c.progress > 0:
        pygame.draw.rect(surf, (30, 30, 40), (s[0] - 24, s[1] - 52, 48, 6))
        pygame.draw.rect(surf, C_GREEN, (s[0] - 24, s[1] - 52, int(48 * c.progress), 6))


def draw_avatar_overlay(view, surf, e):
    ov = view.sim.overlord
    s = view.S(e.pos)
    exposed = ov.exposed_t > 0
    r = 90
    if exposed:
        view.ground_ellipse(surf, e.pos, r + 6 * math.sin(view.t * 14), (255, 255, 255), 20, 3)
    else:
        for i in range(6):                                   # the shield: a hex of red arcs that pulse
            a = view.t * 0.8 + i * math.tau / 6
            p1 = e.pos + V(math.cos(a), math.sin(a)) * r
            p2 = e.pos + V(math.cos(a + 0.9), math.sin(a + 0.9)) * r
            pygame.draw.line(surf, (255, 70, 90), view.S(p1), view.S(p2), 4)
        g = view.A.glow("circle_b", 240, (120, 15, 40), 1.0)
        surf.blit(g, (s[0] - 120, s[1] - 120 - 30), special_flags=pygame.BLEND_RGB_ADD)
    # tethers: every conduit feeds the shield. A ready one pulses green (overload it); a spent one is a dead grey wire.
    pulse = 0.5 + 0.5 * math.sin(view.t * 8)
    for cd in ov.conduits:
        a, b = view.S(cd.pos), s
        if exposed:
            col = (255, 255, 255)
        else:
            col = (int(60 + 80 * pulse), 255, int(120 + 60 * pulse)) if cd.ready else (70, 70, 90)
        pygame.draw.line(surf, col, a, (b[0], b[1] - 30), 3 if cd.ready else 1)
        if cd.ready and not exposed:
            k = (view.t * 0.9 + cd.id * 0.33) % 1.0                      # a spark of charge runs down the wire
            pygame.draw.circle(surf, (230, 255, 240), (int(a[0] + (b[0] - a[0]) * k), int(a[1] + (b[1] - 30 - a[1]) * k)), 4)
    # orbiting shards: more of them, faster and redder in each phase
    phase = max(1, getattr(ov, "phase", 1))
    for i in range(3 + 2 * phase):
        ang = view.t * (0.9 + 0.5 * phase) + i * math.tau / (3 + 2 * phase)
        q = view.S(e.pos + V(math.cos(ang), math.sin(ang) * 0.6) * (r + 26 + 6 * math.sin(view.t * 3 + i)))
        pts = [(q[0], q[1] - 8), (q[0] + 5, q[1]), (q[0], q[1] + 8), (q[0] - 5, q[1])]
        pygame.draw.polygon(surf, (255, 255, 255) if exposed else (255, 70 + 20 * (3 - phase), 90), pts)
    _AV_SCREEN["pos"] = s
    view.labels.append(lambda sf, e=e, ex=exposed, ov=ov: _avatar_label(sf, e, ex, ov))


def _avatar_label(surf, e, exposed, ov):
    """The boss bar rides above the Avatar, clamped clear of the HUD panels and the banner band."""
    from src.settings import LOGICAL_W
    w = 360
    s = _AV_SCREEN.get("pos", (LOGICAL_W // 2, 300))
    cx = min(max(s[0], 340 + w // 2), 930 - w // 2)
    y = min(max(s[1] - 150, 214), 560)
    pygame.draw.rect(surf, (20, 8, 14), (cx - w // 2 - 3, y - 3, w + 6, 18))
    pygame.draw.rect(surf, (255, 255, 255) if exposed else (255, 70, 90), (cx - w // 2, y, int(w * max(0.0, e.hp) / e.max_hp), 12))
    draw.text(surf, "MERIDIAN" + ("  EXPOSED  " + f"{ov.exposed_t:0.0f}s" if exposed else "  SHIELDED"), (cx, y + 18), 22,
              (255, 255, 255) if exposed else (255, 90, 110), "midtop", maxw=w)


_AV_SCREEN = {}


# ====================================================================== machines
MACHINE_COL = {"incinerator": (255, 120, 60), "ward": (90, 220, 255), "gauge": (255, 210, 90), "switchboard": (130, 255, 160),
               "breaker": (255, 90, 90), "beacon": (255, 170, 60), "emitter": (200, 120, 255)}
PLAYER_NAMES = None


def draw_machine(view, surf, m):
    s = view.S(m.pos)
    if not view.on_screen(s, 100):
        return
    sim = view.sim
    col = MACHINE_COL.get(m.kind, C_CYAN)
    spec = m.spec
    busy = m.active_t > 0
    ready = m.ready if m.kind != "incinerator" else True
    tint = None if (ready or busy) else (120, 120, 140)
    view.tile(surf, spec["tile"], m.pos, tint, size=TILE + 6, dy=2)
    pulse = 0.6 + 0.4 * math.sin(view.t * (6 if busy else 2.2) + m.id)
    g = view.A.glow("circle_b", 110 + int(22 * pulse), col if (ready or busy) else (60, 60, 80), 1.0)
    surf.blit(g, (s[0] - g.get_width() / 2, s[1] - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
    if m.kind in ("ward", "emitter") and busy:
        view.ground_ellipse(surf, m.pos, spec["radius"], col, 14, 0)
        view.ground_ellipse(surf, m.pos, spec["radius"], col, 70, 3, fill=False)
    if m.kind == "beacon" and busy:
        warn = m.active_t <= spec["warn"]
        view.ground_ellipse(surf, m.pos, spec["blast_radius"], C_RED if warn else col, 60 if warn else 26, 3, fill=warn)
    if m.flash > 0:
        view.ground_ellipse(surf, m.pos, 40 + 60 * (0.6 - m.flash), (255, 255, 255), int(120 * m.flash), 3, fill=False)
    view.labels.append(lambda sf, m=m, s=s, col=col: _machine_label(sf, view, m, s, col))


def _machine_label(surf, view, m, s, col):
    spec = m.spec
    near = any(p.alive and p.pos.distance_to(m.pos) < 150 for p in view.sim.players)
    if m.kind == "incinerator" and m.progress > 0:
        pygame.draw.rect(surf, (30, 30, 40), (s[0] - 24, s[1] - 40, 48, 6))
        pygame.draw.rect(surf, col, (s[0] - 24, s[1] - 40, int(48 * m.progress), 6))
    if not near and m.active_t <= 0:
        return
    state = ""
    if m.active_t > 0:
        state = f" {m.active_t:0.0f}s"
    elif m.cd > 0:
        state = f" (recharging {m.cd:0.0f}s)"
    draw.text(surf, spec["name"].upper() + state, (s[0], s[1] + 30), 15, col if m.cd <= 0 else (150, 150, 160), "center")
    if m.kind == "gauge" and m.reading and (view.sim.time - m.reading["t"]) < spec["duration"]:
        r = m.reading
        txt = "RIFT: " + r["band"] + ("  |  next: " + ", ".join(r["forecast"]) if r["forecast"] else "")
        draw.text(surf, txt, (s[0], s[1] - 54), 16, (255, 220, 120), "center")


# ====================================================================== the Rift
PAPER_COL = (235, 235, 245)


def draw_paper(view, surf, pp):
    if pp.state == "gone":
        return
    sim = view.sim
    pos = pp.pos
    s = view.S(pos)
    if not view.on_screen(s, 80):
        return
    bob = 3 * math.sin(view.t * 3 + pp.id)
    carried = pp.state == "carried"
    lift = 46 if carried else 14
    w, h = 22, 28
    img = pygame.Surface((w, h), pygame.SRCALPHA)
    img.fill(PAPER_COL + (240,))
    pygame.draw.line(img, (70, 70, 85), (4, 8), (w - 4, 8), 2)
    pygame.draw.line(img, (70, 70, 85), (4, 14), (w - 4, 14), 2)
    pygame.draw.line(img, (70, 70, 85), (4, 20), (w - 9, 20), 2)
    ang = 6 * math.sin(view.t * 2 + pp.id)
    img = pygame.transform.rotate(img, ang)
    g = view.A.glow("circle_a", 96, VIOLET, 1.0)
    surf.blit(g, (s[0] - 48, s[1] - lift - 48 + bob), special_flags=pygame.BLEND_RGB_ADD)
    if not carried:
        view.shadow(surf, pos, 10, 70)
    surf.blit(img, img.get_rect(center=(int(s[0]), int(s[1] - lift + bob))))
    view.labels.append(lambda sf, pp=pp, s=s, lift=lift: _paper_label(sf, view, pp, s, lift))


def _paper_label(surf, view, pp, s, lift):
    sim = view.sim
    if pp.read:
        if pp.owner is None:
            draw.text(surf, "BLANK", (s[0], s[1] - lift - 30), 15, (150, 150, 165), "center")
        else:
            p = sim.players[pp.owner]
            draw.text(surf, p.name.split()[0].upper(), (s[0], s[1] - lift - 30), 16, view.player_color(p), "center")
    else:
        draw.text(surf, "?", (s[0], s[1] - lift - 30), 18, (210, 190, 255), "center")


def draw_rift(view, surf):
    """The seam, the countdown, and the telegraphed shift of a paper."""
    sim = view.sim
    r = sim.rift
    if r.phase is None:
        return
    s = view.S(r.seam)
    t = view.t
    k = 1.0 if r.phase == "open" else 1.0 - max(0.0, r.t) / 6.0
    for i in range(3):
        ring = 30 + 24 * i + 10 * math.sin(t * 5 + i)
        view.ground_ellipse(surf, r.seam, ring * (0.4 + 0.6 * k), VIOLET, int(60 * k), 3, fill=False)
    g = view.A.glow("circle_a", int(180 + 40 * math.sin(t * 6)), VIOLET, 1.0)
    surf.blit(g, (s[0] - g.get_width() / 2, s[1] - g.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
    if r.shift is not None:
        pp, newpos, t_fire = r.shift
        a = view.S(pp.pos)
        b = view.S(newpos)
        pygame.draw.line(surf, (200, 160, 255), a, b, 1)
        view.ground_ellipse(surf, newpos, 30 + 10 * math.sin(t * 10), VIOLET, 70, 3, fill=False)


def rift_flicker(view):
    """0..1: how much the station's lights stutter. A tell, never a number: before any Rift (selection or not) the lights stutter;
    high Rift pressure alone makes them stutter faintly."""
    sim = view.sim
    r = sim.rift
    if r.tell_until > sim.time:
        return 0.55 + 0.35 * math.sin(view.t * 31) * math.sin(view.t * 13)
    from src.systems import rift
    p = rift.pressure(sim, sim.time) if sim.host is None else 0.0
    if p > 0.75 and int(view.t * 2.3) % 7 == 0:
        return 0.25
    return 0.0


def draw_veil(view, surf, p):
    from src.systems import host as H
    h = p.host
    s = view.S(p.pos)
    t = view.t
    if H.veil_up(view.sim, p):
        for i in range(6):                                   # a hex of cold arcs: the Veil
            a0 = t * 0.9 + i * math.tau / 6
            pts = [p.pos + V(math.cos(a0 + o), math.sin(a0 + o)) * 62 for o in (-0.45, -0.15, 0.15, 0.45)]
            pygame.draw.lines(surf, (150, 230, 255), False, [view.S(q) for q in pts], 3)
    elif h.veil_down_t > 0:
        k = h.veil_down_t / 4.5
        for i in range(8):                                   # shards falling away: the Veil is broken
            a0 = i * math.tau / 8
            q = p.pos + V(math.cos(a0), math.sin(a0)) * (62 + 38 * (1 - k))
            pygame.draw.line(surf, (200, 240, 255), view.S(q), view.S(q + V(math.cos(a0 + 1), math.sin(a0 + 1)) * 12), 2)
