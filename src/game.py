"""Application shell: window, fixed logical resolution with letterboxed scaling, scene stack, settings."""
import os

import pygame

from src.audio.audio import Audio
from src.settings import FPS, LOGICAL_H, LOGICAL_W, RESOLUTIONS, TITLE
from src.systems.save import SaveData


class Game:
    def __init__(self, save=None):
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.save = save or SaveData()
        self.clock = pygame.time.Clock()
        self.logical = pygame.Surface((LOGICAL_W, LOGICAL_H))
        self.window = None
        self.audio = Audio(self.save.settings["volume"])
        self.scene = None
        self.running = True
        self.apply_display()

    def apply_display(self):
        s = self.save.settings
        w, h = RESOLUTIONS[s["resolution"]]
        flags = pygame.RESIZABLE
        if s["fullscreen"]:
            flags = pygame.FULLSCREEN
            self.window = pygame.display.set_mode((0, 0), flags)
        else:
            self.window = pygame.display.set_mode((w, h), flags)

    def change(self, scene):
        self.scene = scene
        pygame.mouse.set_visible(True)

    def present(self):
        ww, wh = self.window.get_size()
        k = min(ww / LOGICAL_W, wh / LOGICAL_H)
        size = (int(LOGICAL_W * k), int(LOGICAL_H * k))
        self.window.fill((0, 0, 0))
        img = self.logical if size == (LOGICAL_W, LOGICAL_H) else pygame.transform.smoothscale(self.logical, size)
        self.window.blit(img, ((ww - size[0]) // 2, (wh - size[1]) // 2))
        pygame.display.flip()

    def run(self, max_frames=None):
        frames = 0
        while self.running and self.scene is not None:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.1)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self.running = False
                elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                    self.save.settings["fullscreen"] = not self.save.settings["fullscreen"]
                    self.apply_display()
                    self.save.save()
                else:
                    self.scene.handle_event(ev)
            if not self.running:
                break
            self.scene.update(dt)
            self.scene.draw(self.logical)
            self.present()
            frames += 1
            if max_frames and frames >= max_frames:
                break
        self.save.save()
        pygame.quit()
