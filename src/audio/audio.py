"""Sound playback. The supplied ZIPs contain no audio files, so this plays sounds only if the user adds
assets/audio/<event>.ogg|wav (event names listed in docs/ASSET_AUDIT.md). Without them it does nothing."""
import pygame

from src.config import ASSET_DIR

EVENTS = ["shoot", "enemy_hit", "enemy_died", "player_hit", "defeated", "revived", "relay_online", "loot",
          "surge_hit", "slam", "dodge", "barrier_broken", "hazard_warning", "surge_warning", "mission_end"]


class Audio:
    def __init__(self, volume=0.8):
        self.sounds = {}
        self.volume = volume
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            for name in EVENTS:
                for ext in (".ogg", ".wav"):
                    p = ASSET_DIR / "audio" / (name + ext)
                    if p.exists():
                        self.sounds[name] = pygame.mixer.Sound(str(p))
        except pygame.error:
            self.sounds = {}

    @property
    def available(self):
        return bool(self.sounds)

    def set_volume(self, v):
        self.volume = v

    def play(self, name):
        s = self.sounds.get(name)
        if s:
            s.set_volume(self.volume)
            s.play()
