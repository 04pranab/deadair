"""Headless UI audit: renders every screen and the HUD in the hard states (Rift, Host, Avatar finale, 4-6 players, long logs) and reports
text that leaves the screen, spills out of its panel, or collides with other text. Usage: python tools/ui_audit.py [out_dir]"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pygame  # noqa: E402

from src.game import Game  # noqa: E402
from src.settings import LOGICAL_H, LOGICAL_W  # noqa: E402
from src.systems.save import SaveData  # noqa: E402
from src.ui import draw  # noqa: E402

LOG = {"text": [], "panel": []}
_orig_text, _orig_panel = draw.text, draw.panel


def _text(surf, s, pos, size=24, color=(220, 230, 240), anchor="topleft", shadow=True, alpha=255, maxw=None):
    r = _orig_text(surf, s, pos, size, color, anchor, shadow, alpha, maxw)
    if alpha > 40:
        LOG["text"].append((str(s), pygame.Rect(r), size))
    return r


def _panel(surf, rect, *a, **k):
    LOG["panel"].append(pygame.Rect(rect))
    return _orig_panel(surf, rect, *a, **k)


draw.text, draw.panel = _text, _panel


def analyse():
    issues = []
    screen = pygame.Rect(0, 0, LOGICAL_W, LOGICAL_H)
    texts = LOG["text"]
    for s, r, size in texts:
        if not screen.contains(r):
            issues.append(f"OFFSCREEN {s[:50]!r} {tuple(r)}")
    for s, r, size in texts:
        for p in LOG["panel"]:
            if p.colliderect(r) and not p.contains(r) and p.w < LOGICAL_W - 40 and r.w > 6:
                # the text starts inside the panel but crosses its edge
                if p.collidepoint(r.left + 2, r.centery) or p.collidepoint(r.right - 2, r.centery):
                    issues.append(f"SPILL {s[:50]!r} {tuple(r)} out of panel {tuple(p)}")
                    break
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            (s1, r1, _), (s2, r2, _) = texts[i], texts[j]
            if s1 == s2:
                continue
            inter = r1.clip(r2)
            if inter.w > 4 and inter.h > 4 and inter.w * inter.h > 0.25 * min(r1.w * r1.h, r2.w * r2.h):
                issues.append(f"OVERLAP {s1[:30]!r} x {s2[:30]!r} {tuple(r1)} {tuple(r2)}")
    return sorted(set(issues))


def snap(g, name, out, scene_draw):
    LOG["text"].clear()
    LOG["panel"].clear()
    scene_draw(g.logical)
    pygame.image.save(g.logical, str(out / f"{name}.png"))
    return analyse()


def run_all(out):
    out.mkdir(parents=True, exist_ok=True)
    from src.scenes.menus import ArmoryScene, ChronicleScene, ControlsScene, CoopSetupScene, MenuScene, SettingsScene, default_coop
    from src.scenes.play import PlayScene, ResultsScene
    from src.systems import host, rift
    g = Game(SaveData(None))
    g.save.settings["cinematics"] = False
    report = {}

    for cls in (MenuScene, CoopSetupScene, SettingsScene, ArmoryScene):
        sc = cls(g)
        g.change(sc)
        for _ in range(30):
            sc.update(1 / 60)
        report[cls.__name__] = snap(g, cls.__name__, out, sc.draw)
    for tab in range(6):                                      # every Controls tab, with a long message and a capture prompt showing
        sc = ControlsScene(g)
        sc.tab, sc.row, sc.msg = tab, 2, "Keyboard 2: RIGHT SHIFT is already taken by another player's action"
        sc.capture = sc.rows()[1][0]
        g.change(sc)
        report[f"Controls_tab{tab}"] = snap(g, f"controls_tab{tab}", out, sc.draw)
    g.save.data["clues"] = list(__import__("src.systems.story", fromlist=["StoryBook"]).StoryBook().logs)
    sc = ChronicleScene(g)
    g.change(sc)
    sc.update(0.1)
    report["Chronicle"] = snap(g, "Chronicle", out, sc.draw)

    def play(n, seed=3):
        cfg = default_coop(g, min(n, 4))
        roles = (cfg["roles"] + ["mara", "dax", "imani"] * 2)[:n]
        devs = (cfg["devices"] + [cfg["devices"][0]] * 6)[:n]
        sc = PlayScene(g, roles, devs, seed=seed)
        g.change(sc)
        return sc

    def run(sc, secs):
        for _ in range(int(secs * 60)):
            sc.update(1 / 60)

    for n in (1, 4, 6):
        sc = play(n)
        run(sc, 5)
        report[f"Play_{n}p_start"] = snap(g, f"play_{n}p_start", out, sc.draw)
    sc = play(3)
    run(sc, 3)
    sc.hud.log_open = sc.sim.story.logs["core_decay"]
    sc.log_t = 1.0
    report["Play_log_open"] = snap(g, "play_log_open", out, sc.draw)
    sc.hud.log_open = None
    s = sc.sim
    for p in s.players:
        p.taint = 3
    s.relays_done = 1
    rift.open_rift(s, True)
    run(sc, 8)
    sc.hud.show_banner("RIFT OPEN: FIND THE PAPERS. BURN OR TEAR THEM", (190, 90, 255), 4.0)
    report["Play_rift"] = snap(g, "play_rift", out, sc.draw)
    host.convert(s, s.players[1])
    run(sc, 1)
    sc.hud.show_banner("MERIDIAN HAS READ YOUR HANDS. TURN THE CONDUITS AGAIN", (255, 80, 70), 4.0)
    report["Play_host"] = snap(g, "play_host", out, sc.draw)
    sc.paused = True
    report["Play_pause"] = snap(g, "play_pause", out, sc.draw)
    sc.paused = False
    # the Avatar fight
    from src.systems import overlord
    sc = play(3, 5)
    s = sc.sim
    s.exposed = True
    s.overlord.stage = 0
    overlord._awaken(s, s.overlord)
    s.overlord.adapted = {"shot": 2, "charge": 1}
    s.overlord.phase = 2
    run(sc, 2)
    for p in s.players:                                       # a real fight happens near the Avatar, with it in frame
        p.pos = type(p.pos)(s.overlord.avatar.pos) + type(p.pos)(-160 + 160 * p.idx, 190)
    sc.view.snap_camera()
    sc.hud.say("MERIDIAN", "I have read your hands. Every hand on those conduits, I have already held.", 7.0)
    sc.hud.show_banner("MERIDIAN LEARNED TO IGNORE: SHOT. TRY SOMETHING ELSE", (255, 190, 70), 3.5)
    report["Play_avatar"] = snap(g, "play_avatar", out, sc.draw)
    for status in ("extracted", "lost", "director_destroyed"):
        sc = play(3, 6)
        run(sc, 1)
        sc.sim.finish(status)
        res = sc.sim.result
        rs = ResultsScene(g, res, g.save.record_run(res), sc.roles, sc.devices)
        rs.update(3.0)
        report[f"Results_{status}"] = snap(g, f"results_{status}", out, rs.draw)
    return report


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/ui_audit")
    report = run_all(out)
    bad = 0
    for k, v in report.items():
        print(f"{k}: {len(v)} issue(s)")
        for i in v[:12]:
            print("   ", i)
        bad += len(v)
    print("TOTAL", bad)


if __name__ == "__main__":
    main()
