"""Display, tile and path constants. Balance values live in data/balance.json."""
import os
from pathlib import Path

TITLE = "DEAD AIR"
TAGLINE = "Survive. Rebuild. Discover the Truth."
LOGICAL_W, LOGICAL_H = 1280, 720
FPS = 60
SIM_DT = 1.0 / 60.0
TILE_SRC = 16
TILE_SCALE = 3
TILE = TILE_SRC * TILE_SCALE  # 48 px
MAX_PLAYERS = 6
LOCAL_PLAYERS = 4
RESOLUTIONS = [(1280, 720), (1600, 900), (1920, 1080)]

# Colour accents (procedural UI/effects only; all art comes from supplied assets)
C_BG = (8, 10, 18)
C_CYAN = (80, 200, 255)
C_RED = (255, 80, 70)
C_AMBER = (255, 190, 70)
C_GREEN = (110, 230, 140)
C_TEXT = (220, 230, 240)
C_DIM = (120, 135, 155)
PLAYER_COLORS = [(110, 230, 140), (255, 190, 70), (80, 200, 255), (230, 120, 255), (255, 120, 120), (200, 200, 200)]


def save_dir() -> Path:
    env = os.environ.get("DEADAIR_SAVE_DIR")
    return Path(env) if env else Path.home() / ".deadair"
