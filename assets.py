"""Fonts, avatar tiles, procedural cover delegation, and tone blips."""

from __future__ import annotations

import math
import random
from array import array
from pathlib import Path

import pygame

from config import AVATAR_SHEET, DRIFTER_SIZE, HEIGHT, WIDTH
from deps import covers, np


def load_font(size: int, bold: bool = False) -> pygame.font.Font:
    """Prefer a monospace system font, fall back to pygame's built-in font."""
    try:
        return pygame.font.SysFont("dejavusansmono,monospace", size, bold=bold)
    except Exception:
        return pygame.font.Font(None, size)


def _bands(mask, minimum: int = 40) -> list[tuple[int, int]]:
    """Contiguous runs of True at least `minimum` long (skips hairline rules)."""
    runs: list[tuple[int, int]] = []
    start = None
    for i, on in enumerate(mask):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= minimum:
                runs.append((start, i))
            start = None
    if start is not None and len(mask) - start >= minimum:
        runs.append((start, len(mask)))
    return runs


def _palette_from_tile(tile: pygame.Surface, limit: int = 6) -> list[tuple[int, int, int]]:
    """Pick the tile's most common vivid colours, for matching explosions."""
    fallback = [(120, 230, 255), (255, 120, 230), (255, 220, 90)]
    if np is None:
        return fallback
    try:
        rgb = pygame.surfarray.pixels3d(tile).astype(np.int16).reshape(-1, 3)
        alpha = pygame.surfarray.array_alpha(tile).reshape(-1)
    except Exception:
        return fallback
    vivid = rgb[alpha > 180]
    if len(vivid) == 0:
        return fallback
    hi = vivid.max(axis=1)
    lo = vivid.min(axis=1)
    picked = vivid[(hi >= 110) & (hi - lo >= 45)]
    if len(picked) < 32:
        picked = vivid
    quantised = (picked // 32).astype(np.int32)
    codes = quantised[:, 0] * 64 + quantised[:, 1] * 8 + quantised[:, 2]
    values, counts = np.unique(codes, return_counts=True)
    order = np.argsort(counts)[::-1][:limit]
    palette = []
    for index in order:
        code = int(values[index])
        palette.append((
            min(255, (code // 64) * 32 + 16),
            min(255, ((code // 8) % 8) * 32 + 16),
            min(255, (code % 8) * 32 + 16),
        ))
    while len(palette) < 3:
        palette.append(fallback[len(palette)])
    return palette


def load_avatar_tiles(path: Path = AVATAR_SHEET,
                      size: int = DRIFTER_SIZE) -> list[tuple[pygame.Surface, list]]:
    """Slice the 3x2 avatar sheet into six round, alpha-cut sprite tiles."""
    try:
        sheet = pygame.image.load(str(path))
    except (pygame.error, FileNotFoundError, OSError):
        return []

    width, height = sheet.get_size()
    if np is not None:
        rgb = pygame.surfarray.array3d(sheet).astype(np.int16)  # (w, h, 3)
        content = rgb.sum(axis=2) < 720
        xs = _bands(content.sum(axis=1) > 8)
        ys = _bands(content.sum(axis=0) > 8)
        boxes = [(x0, y0, x1 - x0, y1 - y0)
                 for (y0, y1) in ys for (x0, x1) in xs]
    else:
        boxes = []
        for row in range(2):
            for col in range(3):
                boxes.append((col * width // 3, row * height // 2,
                              width // 3, height // 2))

    tiles: list[tuple[pygame.Surface, list]] = []
    for (x0, y0, w, h) in boxes:
        tile = pygame.Surface((w, h), pygame.SRCALPHA)
        tile.blit(sheet, (0, 0), pygame.Rect(x0, y0, w, h))
        if np is not None:
            # Knock out the flat white sheet background (and its grey JPEG
            # fringe) only outside the badge circle, so white details inside
            # the artwork (the robot, eyes, highlights) survive intact.
            arr = pygame.surfarray.pixels3d(tile)
            alpha = pygame.surfarray.pixels_alpha(tile)
            w, h = arr.shape[0], arr.shape[1]
            yy, xx = np.ogrid[:w, :h]
            cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
            radius = min(w, h) / 2.0 * 0.94
            outside = ((xx - cx) ** 2 + (yy - cy) ** 2) > radius * radius
            high = arr.max(axis=2)
            low = arr.min(axis=2)
            background = outside & (high > 185) & ((high - low) < 45)
            alpha[background] = 0
            del arr, alpha
        else:
            tile.set_colorkey((255, 255, 255))
        palette = _palette_from_tile(tile)
        scaled = pygame.transform.smoothscale(tile, (size, size))
        tiles.append((scaled, palette))
    return tiles


def make_pulp_background(rng: random.Random) -> pygame.Surface:
    """Paint a fresh paperback cover, dimmed for use behind the game."""
    if covers is not None:
        return covers.make_cover(rng, WIDTH, HEIGHT)

    # Minimal fallback if numpy/covers is unavailable.
    art = pygame.Surface((WIDTH, HEIGHT))
    top, bottom = (10, 12, 30), (34, 20, 42)
    for y in range(0, HEIGHT, 4):
        t = y / (HEIGHT - 1)
        colour = tuple(int(top[i] + (bottom[i] - top[i]) * t ** 1.25)
                       for i in range(3))
        art.fill(colour, (0, y, WIDTH, 4))
    for _ in range(180):
        value = rng.randint(90, 255)
        art.fill((value, value, min(255, value + 16)),
                 (rng.randrange(WIDTH), rng.randrange(HEIGHT), 1, 1))
    art.set_alpha(70)
    return art


def make_tone(frequency: float, duration_ms: int, volume: float = 0.18,
              sample_rate: int = 44100) -> pygame.mixer.Sound | None:
    """Build a short square-wave blip without needing numpy or asset files.

    The mixer runs in stereo, so each mono sample is written to both channels;
    otherwise the single-channel buffer would play back at double speed.
    """
    try:
        init = pygame.mixer.get_init()
        if not init:
            return None
        channels = init[2]
        rate = init[0] or sample_rate
        frames = int(rate * duration_ms / 1000)
        amplitude = int(32767 * volume)
        buf = array("h")
        for i in range(frames):
            # Fade the tail slightly so blips don't click.
            decay = 1.0 - (i / max(frames, 1)) * 0.6
            value = int(amplitude * decay)
            if math.sin(2 * math.pi * frequency * i / rate) < 0:
                value = -value
            for _ in range(channels):
                buf.append(value)
        return pygame.mixer.Sound(buffer=buf.tobytes())
    except Exception:
        return None
