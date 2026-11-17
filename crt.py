"""Standalone CRT post-process prototype for the Space Invaders canvas.

Pure pygame: no numpy, no shaders, no display required.  Apply it to the
finished 800x600 canvas (in place or into another surface) and then let the
existing `present()` scaling handle the window size.  That keeps the cost
fixed at 800x600 no matter how large the window is.

    crt = CrtOverlay((800, 600), preset="medium")
    crt.apply_inplace(game.canvas, t=seconds)
    game.present(screen)

Presets: "off", "low", "medium", "high".  Rebuild with set_size() when the
canvas size changes; switch presets with set_preset() and scale the active
preset with set_intensity() (0.0-1.0).
"""

from __future__ import annotations

import math
import random

import pygame

PRESETS: dict[str, dict[str, float]] = {
    # scan: scanline darkening (0-255); grille: RGB triad strength 0-1;
    # vignette: edge darkening 0-1; bloom: additive halo alpha;
    # grain: max additive noise; band: additive refresh-band strength;
    # trail: previous-frame ghost alpha.
    "off": {
        "scan": 0, "grille": 0.0, "vignette": 0.0,
        "bloom": 0, "grain": 0, "band": 0, "trail": 0,
    },
    "low": {
        "scan": 20, "grille": 0.30, "vignette": 0.45,
        "bloom": 0, "grain": 0, "band": 0, "trail": 0,
    },
    "medium": {
        "scan": 34, "grille": 0.50, "vignette": 0.70,
        "bloom": 22, "grain": 0, "band": 7, "trail": 0,
    },
    "high": {
        "scan": 50, "grille": 0.75, "vignette": 0.95,
        "bloom": 34, "grain": 8, "band": 10, "trail": 30,
    },
}


class CrtOverlay:
    def __init__(self, size: tuple[int, int], preset: str = "medium",
                 intensity: float = 1.0, seed: int = 7) -> None:
        self.size = (max(1, int(size[0])), max(1, int(size[1])))
        self.seed = seed
        self.intensity = max(0.0, min(1.0, float(intensity)))
        self._out: pygame.Surface | None = None
        self._prev: pygame.Surface | None = None
        self._snap: pygame.Surface | None = None
        self._bloom_small: pygame.Surface | None = None
        self._bloom: pygame.Surface | None = None
        self._tint: pygame.Surface | None = None
        self._band: pygame.Surface | None = None
        self._noise: pygame.Surface | None = None
        self.set_preset(preset)

    # ------------------------------------------------------------------ #
    # Setup (all expensive work happens here)
    # ------------------------------------------------------------------ #

    def set_preset(self, preset: str) -> None:
        if preset not in PRESETS:
            raise ValueError(f"unknown CRT preset: {preset}")
        self.preset = preset
        self._preset_cfg = dict(PRESETS[preset])
        self._prev = None
        self._snap = None
        self._build()

    def set_intensity(self, intensity: float) -> None:
        """Scale the active preset's effect strength (0.0-1.0)."""
        self.intensity = max(0.0, min(1.0, float(intensity)))
        self._prev = None
        self._snap = None
        self._build()

    def set_size(self, size: tuple[int, int]) -> None:
        self.size = (max(1, int(size[0])), max(1, int(size[1])))
        self._out = None
        self._prev = None
        self._snap = None
        self._bloom_small = None
        self._bloom = None
        self._build()

    def _build(self) -> None:
        w, h = self.size
        self.cfg = {
            key: value * self.intensity
            for key, value in self._preset_cfg.items()
        }
        cfg = self.cfg

        # One multiply surface for scanlines + aperture grille + vignette.
        # Sequential darkening is multiplicative, so a single BLEND_RGB_MULT
        # pass is equivalent to three alpha passes and a third of the cost.
        self._tint = None
        if cfg["scan"] or cfg["grille"] or cfg["vignette"]:
            tint = pygame.Surface((w, h))
            tint.fill((255, 255, 255))

            if cfg["scan"] > 0:
                period = min(4, max(2, h // 300))
                value = int(255 - cfg["scan"])
                for y in range(0, h, period):
                    pygame.draw.line(tint, (value, value, value),
                                     (0, y), (w - 1, y))

            if cfg["grille"] > 0:
                strength = cfg["grille"]
                grille = pygame.Surface((w, h))
                grille.fill((255, 255, 255))

                def tint_channel(base: tuple[int, int, int]) -> tuple[int, int, int]:
                    return tuple(int(255 - (255 - v) * strength) for v in base)

                red = tint_channel((255, 232, 232))
                green = tint_channel((232, 255, 232))
                blue = tint_channel((232, 232, 255))
                for x in range(0, w, 3):
                    pygame.draw.line(grille, red, (x, 0), (x, h - 1))
                    if x + 1 < w:
                        pygame.draw.line(grille, green, (x + 1, 0), (x + 1, h - 1))
                    if x + 2 < w:
                        pygame.draw.line(grille, blue, (x + 2, 0), (x + 2, h - 1))
                tint.blit(grille, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

            if cfg["vignette"] > 0:
                vw, vh = 96, 72
                small = pygame.Surface((vw, vh))
                small.fill((255, 255, 255))
                strength = cfg["vignette"]
                for y in range(vh):
                    ny = (y + 0.5) / vh * 2.0 - 1.0
                    for x in range(vw):
                        nx = (x + 0.5) / vw * 2.0 - 1.0
                        d = math.sqrt(nx * nx * 0.95 + ny * ny * 1.15)
                        edge = min(1.0, max(0.0, (d - 0.55) / 0.60))
                        value = int(255 * (1.0 - edge ** 1.6 * strength))
                        small.set_at((x, y), (value, value, value))
                tint.blit(pygame.transform.smoothscale(small, self.size),
                          (0, 0), special_flags=pygame.BLEND_RGB_MULT)

            self._tint = tint

        # Rolling refresh band: a short additive gradient, cheap to blit.
        self._band = None
        if cfg["band"] > 0:
            bh = max(48, h // 6)
            band = pygame.Surface((w, bh))
            band.fill((0, 0, 0))
            for y in range(bh):
                t = 1.0 - abs((y + 0.5) - bh / 2.0) / (bh / 2.0)
                value = int(cfg["band"] * t * t)
                if value:
                    pygame.draw.line(band, (value, value, value),
                                     (0, y), (w - 1, y))
            self._band = band

        # Grain: one small additive tile, tiled with a moving offset.
        self._noise = None
        if cfg["grain"] > 0:
            tile = 96
            rng = random.Random(self.seed)
            noise = pygame.Surface((tile, tile))
            noise.fill((0, 0, 0))
            for y in range(tile):
                for x in range(tile):
                    value = rng.randrange(0, int(cfg["grain"]) + 1)
                    if value:
                        noise.set_at((x, y), (value, value, value))
            self._noise = noise

    # ------------------------------------------------------------------ #
    # Per-frame
    # ------------------------------------------------------------------ #

    def apply_inplace(self, surface: pygame.Surface, t: float = 0.0) -> None:
        """Apply the effect to *surface* without an extra full-frame blit."""
        self._apply(surface, surface, t)

    def apply(self, src: pygame.Surface, dst: pygame.Surface | None = None,
              t: float = 0.0) -> pygame.Surface:
        """Return a processed copy of *src* (the copy is reused each frame)."""
        if dst is None:
            if self._out is None or self._out.get_size() != src.get_size():
                self._out = pygame.Surface(src.get_size())
            dst = self._out
        self._apply(src, dst, t)
        return dst

    def _apply(self, src: pygame.Surface, out: pygame.Surface,
               t: float) -> None:
        if src.get_size() != self.size:
            self.set_size(src.get_size())
        cfg = self.cfg
        inplace = out is src

        if not inplace:
            out.blit(src, (0, 0))
        if not any(cfg.values()):
            return

        snapshot = src
        if cfg["trail"]:
            if inplace:
                if self._snap is None:
                    self._snap = pygame.Surface(self.size)
                self._snap.blit(src, (0, 0))
                snapshot = self._snap
            if self._prev is not None:
                self._prev.set_alpha(int(cfg["trail"]))
                out.blit(self._prev, (0, 0))

        if cfg["bloom"]:
            w, h = self.size
            small_size = (max(1, w // 6), max(1, h // 6))
            if (self._bloom_small is None
                    or self._bloom_small.get_size() != small_size):
                self._bloom_small = pygame.Surface(small_size)
            pygame.transform.smoothscale(src, small_size, self._bloom_small)
            if self._bloom is None or self._bloom.get_size() != self.size:
                self._bloom = pygame.Surface(self.size)
            pygame.transform.smoothscale(self._bloom_small, self.size,
                                         self._bloom)
            self._bloom.set_alpha(int(cfg["bloom"]))
            out.blit(self._bloom, (0, 0), special_flags=pygame.BLEND_ADD)

        if self._tint is not None:
            out.blit(self._tint, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

        if self._band is not None:
            bh = self._band.get_height()
            y = int((t * 260.0) % (self.size[1] + bh)) - bh
            out.blit(self._band, (0, y), special_flags=pygame.BLEND_ADD)

        if self._noise is not None:
            tile = self._noise.get_width()
            ox = int(t * 37.0) % tile
            oy = int(t * 53.0) % tile
            for yy in range(-oy, self.size[1], tile):
                for xx in range(-ox, self.size[0], tile):
                    out.blit(self._noise, (xx, yy),
                             special_flags=pygame.BLEND_ADD)

        if cfg["trail"]:
            if self._prev is None:
                self._prev = pygame.Surface(self.size)
            self._prev.blit(snapshot, (0, 0))

    def apply_patch(self, patch: pygame.Surface,
                    offset: tuple[int, int], t: float = 0.0) -> None:
        """Apply this overlay's tint/band/bloom to a patch in place.

        *offset* maps the patch back onto the full canvas so scanlines,
        grille, vignette and the rolling band keep their normal coordinates.
        This is the cheap region pass used to cap the HUD at medium; it does
        not implement grain or phosphor trails.
        """
        if not any(self.cfg.values()):
            return
        w, h = patch.get_size()
        ox, oy = offset
        if self._tint is not None:
            patch.blit(self._tint, (0, 0), (ox, oy, w, h),
                       special_flags=pygame.BLEND_RGB_MULT)
        if self._band is not None:
            bh = self._band.get_height()
            y = int((t * 260.0) % (self.size[1] + bh)) - bh
            top, bottom = max(oy, y), min(oy + h, y + bh)
            if bottom > top:
                patch.blit(self._band, (0, top - oy),
                           (0, top - y, w, bottom - top),
                           special_flags=pygame.BLEND_ADD)
        if self.cfg["bloom"]:
            small = pygame.transform.smoothscale(
                patch, (max(1, w // 6), max(1, h // 6)))
            halo = pygame.transform.smoothscale(small, (w, h))
            halo.set_alpha(int(self.cfg["bloom"]))
            patch.blit(halo, (0, 0), special_flags=pygame.BLEND_ADD)
