"""Copy the selected subset of the supplied Kenney ZIP contents into assets/ and
generate assets/manifest.json plus docs/ASSET_AUDIT.md from the real files.

Usage:  python3 -I tools/build_assets.py <extracted_zip_root> [<project_root>]
<extracted_zip_root> contains k1/, k2/, k3/ (each an extracted ZIP).
"""
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

# (source dir relative to zip root, destination under assets/, recursive glob)
SELECTION = [
    ("k2/kenney_platformer-characters/standalone_tiles/PNG", "chars2d", "*/Poses/*.png"),
    ("k2/kenney_modular-space-kit_1.0/standalone_tiles/Previews", "hub/modular", "*.png"),
    ("k2/kenney_particle-pack/standalone_tiles/PNG (Transparent)", "fx/particles", "*.png"),
    ("k1/kenney_light-masks-1.0/standalone_tiles/Transparent", "fx/lights", "*.png"),
    ("k3/kenney_ui-pack-space-expansion/standalone_tiles/PNG/Blue/Default", "ui/blue", "*.png"),
    ("k3/kenney_ui-pack-space-expansion/standalone_tiles/PNG/Red/Default", "ui/red", "*.png"),
    ("k1/kenney_game-icons/sheet_white1x", "ui/icons", "*.png"),
    ("k3/kenney_space-station-kit/standalone_tiles/Previews", "hub/station", "*.png"),
    ("k3/kenney_tiny-factory/standalone_tiles/Tiles", "hub/factory", "*.png"),
]
LICENSE_EVIDENCE = [
    ("k3/kenney_space-station-kit/standalone_tiles/Preview.png", "licenses/space-station-kit_Preview.png"),
    ("k3/kenney_tiny-factory/standalone_tiles/Preview.png", "licenses/tiny-factory_Preview.png"),
    ("k2/kenney_particle-pack/standalone_tiles/Preview.png", "licenses/particle-pack_Preview.png"),
    ("k1/kenney_light-masks-1.0/standalone_tiles/Preview.png", "licenses/light-masks_Preview.png"),
    ("k3/kenney_ui-pack-space-expansion/standalone_tiles/Preview.png", "licenses/ui-pack-space-expansion_Preview.png"),
]


def main():
    zroot = Path(sys.argv[1])
    proj = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent
    assets = proj / "assets"
    manifest = {}
    per_group = defaultdict(lambda: {"count": 0, "sizes": defaultdict(int), "src": ""})
    for src, dst, pat in SELECTION:
        sdir = zroot / src
        files = sorted(p for p in sdir.rglob(pat) if "Rotated" not in p.parts)
        if not files:
            raise SystemExit(f"no files found for {src}")
        for f in files:
            rel = f.relative_to(sdir)
            out = assets / dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, out)
            with Image.open(out) as im:
                size = im.size
                mode = im.mode
            key = f"{dst}/{rel.as_posix()}"
            manifest[key] = {"w": size[0], "h": size[1], "mode": mode, "source": f"{src}/{rel.as_posix()}"}
            g = per_group[dst]
            g["count"] += 1
            g["sizes"][f"{size[0]}x{size[1]}"] += 1
            g["src"] = src
    for src, dst in LICENSE_EVIDENCE:
        out = assets / dst
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(zroot / src, out)
    (assets / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    lines = ["| Group (assets/...) | Files | Source in ZIP | Sizes (WxH: count) |", "|---|---|---|---|"]
    for dst, g in per_group.items():
        sizes = ", ".join(f"{k}: {v}" for k, v in sorted(g["sizes"].items(), key=lambda kv: -kv[1])[:6])
        lines.append(f"| `{dst}` | {g['count']} | `{g['src']}` | {sizes} |")
    (proj / "docs" / "_asset_table.md").write_text("\n".join(lines) + "\n")
    print(f"copied {len(manifest)} files")


if __name__ == "__main__":
    main()
