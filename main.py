#!/usr/bin/env python3
"""Space Invaders — arcade game with a live heavy-metal soundtrack.

Controls
    Left / Right  or  A / D   move
    Space                     fire
    P                         pause
    M                         mute music
    L                         high-score leaderboard
    F11  /  Alt+Enter         fullscreen (the view scales to any size)
    Enter                     start / restart (composes a new song)

Requires: pygame-ce (or pygame)  ->  pip install pygame-ce
          numpy (optional, for the music)  ->  pip install numpy
"""

from __future__ import annotations

import argparse
import colorsys
import json
import math
import os
import random
import sys
import threading
from array import array
from dataclasses import dataclass
from pathlib import Path

try:
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
except ModuleNotFoundError:
    # If pygame isn't in whatever interpreter was used, hand off to the
    # project's own virtualenv instead of dying with a traceback.
    _venv_python = Path(__file__).resolve().parent / ".venv" / "bin" / "python"
    if (_venv_python.exists()
            and os.environ.get("SPACE_INVADERS_BOOTSTRAPPED") != "1"
            and os.path.realpath(sys.executable) != os.path.realpath(_venv_python)):
        os.environ["SPACE_INVADERS_BOOTSTRAPPED"] = "1"
        os.execv(str(_venv_python), [str(_venv_python), *sys.argv])
    raise SystemExit(
        "pygame is not installed for this Python.\n"
        "Run with the project venv:  .venv/bin/python main.py\n"
        "or install it:              python -m pip install pygame-ce"
    )

try:
    import music as metal
except Exception:  # numpy missing, or some other synth problem
    metal = None

try:
    import covers
except ImportError:  # numpy missing; the game falls back to a gradient
    covers = None

try:
    import numpy as np
except ImportError:  # hazards and music still degrade gracefully
    np = None

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

WIDTH, HEIGHT = 800, 600
FPS = 60
FIELD_TOP = 64

BG_TOP = (8, 10, 26)
BG_BOTTOM = (18, 12, 34)
PLAYER_COLOR = (120, 255, 180)
PLAYER_BULLET_COLOR = (240, 255, 200)
ALIEN_BULLET_COLOR = (255, 120, 140)
UI_COLOR = (200, 210, 255)
UI_DIM = (110, 115, 160)

LEFT_WALL = 40
RIGHT_WALL = WIDTH - 40
FLOOR_Y = HEIGHT - 28       # drawn floor line at the bottom of the arena
PLAYER_W, PLAYER_H = 46, 18
PLAYER_SPEED = 360.0
PLAYER_Y = FLOOR_Y - 44     # player sits just above the floor, inside the arena
LANDING_Y = PLAYER_Y - 10   # aliens crossing this line end the run

ALIEN_W, ALIEN_H = 34, 24
COLS, ROWS = 8, 4
GAP_X, GAP_Y = 18, 16
FORMATION_TOP = 84
FORMATION_LEFT = (WIDTH - (COLS * ALIEN_W + (COLS - 1) * GAP_X)) // 2
DROP_DISTANCE = 22

PLAYER_BULLET_SPEED = 620.0
ALIEN_BULLET_SPEED = 250.0
PLAYER_FIRE_COOLDOWN = 0.22
MAX_PLAYER_BULLETS = 3

ROW_COLORS = [
    (255, 105, 180),  # front row
    (255, 200, 90),
    (120, 220, 255),
    (170, 150, 255),  # back row
]
ROW_POINTS = [30, 20, 15, 10]

# Destructible bunkers, built from a grid of small cells so they can erode.
SHIELDS = 4
SHIELD_COLS, SHIELD_ROWS, SHIELD_CELL = 22, 16, 3
SHIELD_W = SHIELD_COLS * SHIELD_CELL
SHIELD_H = SHIELD_ROWS * SHIELD_CELL
SHIELD_Y = FLOOR_Y - 148
SHIELD_TOP_COLOR = (150, 255, 195)
SHIELD_BOTTOM_COLOR = (55, 150, 115)

# Floating avatar hazards (one sprite sheet, six badges).
AVATAR_SHEET = Path(os.environ.get(
    "SPACE_INVADERS_AVATARS", Path.home() / "avatars" / "image_79efc5be.jpeg"))
DRIFTER_SIZE = 46            # a little larger than an alien (34 x 24)
DRIFTER_SPEED_MIN, DRIFTER_SPEED_MAX = 70.0, 125.0
DRIFTER_SPAWN_DELAY = 2.2
DRIFTER_RESPAWN = 4.5
DRIFTER_POINTS = 50
# The badge limit is the wave number: 1 on wave 1, 2 on wave 2, and so on.

# Persistent high-score table.
LEADERBOARD_SIZE = 100
LEADERBOARD_ROWS = 15        # visible rows on the scores screen
SCORES_FILE = Path(os.environ.get(
    "SPACE_INVADERS_SCORES",
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "space_invaders" / "leaderboard.json",
)).expanduser()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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


# --------------------------------------------------------------------------- #
# Procedural 1960s sci-fi paperback covers
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

@dataclass
class Bullet:
    x: float
    y: float
    vy: float
    from_player: bool
    prev_y: float = -1.0

    @property
    def width(self) -> int:
        return 4 if self.from_player else 6

    @property
    def height(self) -> int:
        return 14 if self.from_player else 16

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), self.width, self.height)

    def sweep_rect(self) -> pygame.Rect:
        """Rect covering the whole path since the last frame (no tunnelling)."""
        if self.prev_y < 0:
            return self.rect()
        top = min(self.y, self.prev_y)
        bottom = max(self.y, self.prev_y)
        return pygame.Rect(int(self.x), int(top), self.width,
                           int(bottom - top) + self.height)

    def update(self, dt: float) -> None:
        self.prev_y = self.y
        self.y += self.vy * dt


@dataclass
class Alien:
    col: int
    row: int
    x: float
    y: float
    alive: bool = True

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), ALIEN_W, ALIEN_H)


@dataclass
class Player:
    x: float
    y: float = PLAYER_Y
    cooldown: float = 0.0
    invulnerable: float = 0.0

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), PLAYER_W, PLAYER_H)

    @property
    def center_x(self) -> float:
        return self.x + PLAYER_W / 2


@dataclass
class Drifter:
    """A floating avatar badge that destroys whatever it touches."""

    image: pygame.Surface
    palette: list[tuple[int, int, int]]
    x: float
    y: float
    vx: float
    vy: float

    @property
    def size(self) -> int:
        return self.image.get_width()

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), self.size, self.size)


class Shield:
    """A bunker: a grid of small cells that bullets chip away at."""

    def __init__(self, x: int, y: int, seed: int = 0) -> None:
        self.x, self.y = x, y
        self.cell = SHIELD_CELL
        self.cols, self.rows = SHIELD_COLS, SHIELD_ROWS
        self.rng = random.Random(seed)
        self.cells = [bytearray(b"\x01" * self.cols) for _ in range(self.rows)]
        self._surf: pygame.Surface | None = None
        self.carve_shape()

    def carve_shape(self) -> None:
        """Rounded top corners and the classic arch cut out of the bottom."""
        for r in range(self.rows):
            for c in range(self.cols):
                top_inset = max(0, 3 - r)
                if c < top_inset or c >= self.cols - top_inset:
                    self.cells[r][c] = 0
                if r >= self.rows - 5:
                    depth = r - (self.rows - 5)
                    half_width = 2.0 + 0.8 * depth
                    if abs(c - (self.cols - 1) / 2) < half_width:
                        self.cells[r][c] = 0
        self._surf = None

    # -- geometry ---------------------------------------------------------- #

    @property
    def width(self) -> int:
        return self.cols * self.cell

    @property
    def height(self) -> int:
        return self.rows * self.cell

    def bounds(self) -> pygame.Rect:
        return pygame.Rect(self.x, self.y, self.width, self.height)

    def _cells_in(self, rect: pygame.Rect):
        local = rect.move(-self.x, -self.y)
        if (local.right <= 0 or local.left >= self.width
                or local.bottom <= 0 or local.top >= self.height):
            return
        c0 = max(0, local.left // self.cell)
        c1 = min(self.cols - 1, (local.right - 1) // self.cell)
        r0 = max(0, local.top // self.cell)
        r1 = min(self.rows - 1, (local.bottom - 1) // self.cell)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                yield r, c

    # -- damage ------------------------------------------------------------ #

    def hit_cell(self, rect: pygame.Rect, vy: float) -> tuple[int, int] | None:
        """First live cell the rect touches, scanning along the bullet's path."""
        hits = [(r, c) for r, c in self._cells_in(rect) if self.cells[r][c]]
        if not hits:
            return None
        hits.sort()
        return hits[0] if vy >= 0 else hits[-1]

    def damage(self, row: int, col: int, radius: float = 2.2) -> int:
        """Blast a crater; return how many cells were actually destroyed."""
        destroyed = 0
        reach = int(radius) + 1
        for r in range(max(0, row - reach), min(self.rows, row + reach + 1)):
            for c in range(max(0, col - reach), min(self.cols, col + reach + 1)):
                dr, dc = r - row, c - col
                dist2 = dc * dc + dr * dr * 0.8
                if dist2 <= radius * radius:
                    if self.cells[r][c]:
                        self.cells[r][c] = 0
                        destroyed += 1
                elif (dist2 <= (radius + 1) ** 2
                      and self.rng.random() < 0.35
                      and self.cells[r][c]):
                    self.cells[r][c] = 0  # jagged, uneven crater edge
                    destroyed += 1
        self._surf = None
        return destroyed

    def erase_rect(self, rect: pygame.Rect) -> bool:
        """Wipe out every cell under `rect` (aliens marching through a bunker)."""
        erased = False
        for r, c in self._cells_in(rect):
            if self.cells[r][c]:
                self.cells[r][c] = 0
                erased = True
        if erased:
            self._surf = None
        return erased

    def alive_cells(self) -> int:
        return sum(sum(row) for row in self.cells)

    # -- rendering --------------------------------------------------------- #

    def _row_color(self, r: int) -> tuple[int, int, int]:
        t = r / max(1, self.rows - 1)
        return tuple(int(a + (b - a) * t)
                     for a, b in zip(SHIELD_TOP_COLOR, SHIELD_BOTTOM_COLOR))

    def surface(self) -> pygame.Surface:
        if self._surf is None:
            surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            for r in range(self.rows):
                color = self._row_color(r)
                for c in range(self.cols):
                    if self.cells[r][c]:
                        pygame.draw.rect(surf, color,
                                         (c * self.cell, r * self.cell,
                                          self.cell, self.cell))
            self._surf = surf
        return self._surf

    def draw(self, surface: pygame.Surface) -> None:
        surface.blit(self.surface(), (self.x, self.y))


# --------------------------------------------------------------------------- #
# High-score table
# --------------------------------------------------------------------------- #

def _score_order(entry: dict[str, float]) -> tuple:
    return (-entry["score"], -entry["wave"], -entry["accuracy"],
            -entry["avatars"])


class Leaderboard:
    """The best 100 runs, persisted as JSON between sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else SCORES_FILE
        self.entries = self.load()

    @staticmethod
    def clean_entry(raw: object) -> dict[str, float] | None:
        if not isinstance(raw, dict):
            return None
        if "name" in raw:
            # Discard records from an abandoned named-board format.
            return None
        try:
            entry = {
                "score": max(0, int(raw["score"])),
                "wave": max(1, int(raw["wave"])),
                "avatars": max(0, int(raw["avatars"])),
                "bunker": float(raw["bunker"]),
                "accuracy": float(raw["accuracy"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(entry["bunker"])
                and math.isfinite(entry["accuracy"])):
            return None
        entry["bunker"] = round(clamp(entry["bunker"], 0.0, 100.0), 2)
        entry["accuracy"] = round(clamp(entry["accuracy"], 0.0, 100.0), 2)
        return entry

    def load(self) -> list[dict[str, float]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(raw, dict):
            raw = raw.get("scores", [])
        if not isinstance(raw, list):
            return []
        entries = [self.clean_entry(item) for item in raw]
        entries = [entry for entry in entries if entry is not None]
        entries.sort(key=_score_order)
        return entries[:LEADERBOARD_SIZE]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(json.dumps(self.entries, indent=2),
                            encoding="utf-8")
            os.replace(temp, self.path)
        except OSError:
            # A read-only home directory shouldn't take the game down.
            pass

    def add(self, entry: dict[str, float]) -> int | None:
        """Insert a finished run; return its 1-based rank, or None."""
        cleaned = self.clean_entry(entry)
        if cleaned is None:
            return None
        self.entries.append(cleaned)
        self.entries.sort(key=_score_order)
        del self.entries[LEADERBOARD_SIZE:]
        self.save()
        for rank, saved in enumerate(self.entries, start=1):
            if saved is cleaned:
                return rank
        return None


# --------------------------------------------------------------------------- #
# Game
# --------------------------------------------------------------------------- #

class Game:
    def __init__(self, seed: int | None = None,
                 leaderboard: Leaderboard | None = None) -> None:
        self.rng = random.Random(seed)
        self.font_big = load_font(54, bold=True)
        self.font_mid = load_font(28)
        self.font_small = load_font(18)
        self.font_tiny = load_font(15)
        self.sounds = {
            "shoot": make_tone(880, 70, 0.12),
            "hit": make_tone(220, 90, 0.16),
            "boom": make_tone(120, 260, 0.20),
            "wave": make_tone(660, 140, 0.14),
            "clank": make_tone(330, 45, 0.10),
            "blast": make_tone(82, 320, 0.22),
        }
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        self.avatar_tiles = load_avatar_tiles()
        self.leaderboard = leaderboard if leaderboard is not None else Leaderboard()
        self.score_return_state = "title"
        self.score_scroll = 0
        self.genre_bag: list[str] = []
        self.music_genre: str | None = None
        self.pulp_bg: pygame.Surface | None = None
        self.stars = [
            (self.rng.uniform(0, WIDTH), self.rng.uniform(0, HEIGHT),
             self.rng.choice((1, 1, 1, 2)), self.rng.uniform(6, 26))
            for _ in range(90)
        ]
        self.state = "title"  # title | playing | paused | gameover
        self.reset()

    # -- setup ------------------------------------------------------------- #

    def reset(self) -> None:
        self.player = Player(x=WIDTH / 2 - PLAYER_W / 2)
        self.player_bullets: list[Bullet] = []
        self.alien_bullets: list[Bullet] = []
        self.score = 0
        self.lives = 3
        self.wave = 1
        self.direction = 1
        self.fire_timer = 1.2
        self.alien_anim = 0.0
        # Per-run statistics for the high-score table.
        self.shots_fired = 0
        self.shots_hit = 0
        self.avatars_killed = 0
        self.bunker_cells_shot = 0   # bunker cells wrecked by your bullets
        self.bunker_cells_total = 0  # cells deployed across all waves this run
        self.last_rank: int | None = None
        self.pending_record = False
        self.genre_bag = []
        self.music_genre = None
        self.spawn_wave()

    def spawn_wave(self) -> None:
        self.aliens: list[Alien] = []
        for row in range(ROWS):
            for col in range(COLS):
                self.aliens.append(Alien(
                    col=col,
                    row=row,
                    x=FORMATION_LEFT + col * (ALIEN_W + GAP_X),
                    y=FORMATION_TOP + row * (ALIEN_H + GAP_Y),
                ))
        self.direction = 1
        self.player_bullets.clear()
        self.alien_bullets.clear()
        self.debris: list[list[float]] = []
        self.rings: list[list[float]] = []
        self.flashes: list[list[float]] = []
        self.drifters: list[Drifter] = []
        self.drifter_timer = DRIFTER_SPAWN_DELAY
        self.shields = self.make_shields()
        self.bunker_cells_total += sum(s.alive_cells() for s in self.shields)
        self.fire_timer = max(0.45, 1.3 - 0.1 * (self.wave - 1))
        self.alien_anim = 0.0

        # New wave, new cover painting and a fresh genre of music.
        self.music_genre = self.choose_music_genre()
        self.pulp_bg = make_pulp_background(
            random.Random(self.rng.getrandbits(48)))

    def choose_music_genre(self) -> str | None:
        """Cycle through the genre bag so no two waves share a style."""
        if metal is None:
            return None
        if not self.genre_bag:
            self.genre_bag = list(metal.GENRES)
            self.rng.shuffle(self.genre_bag)
            if (len(self.genre_bag) > 1
                    and self.genre_bag[-1] == self.music_genre):
                self.genre_bag[0], self.genre_bag[-1] = (
                    self.genre_bag[-1], self.genre_bag[0])
        return self.genre_bag.pop()

    def make_shields(self) -> list[Shield]:
        span = RIGHT_WALL - LEFT_WALL
        gap = (span - SHIELDS * SHIELD_W) / (SHIELDS + 1)
        return [
            Shield(int(LEFT_WALL + gap + i * (SHIELD_W + gap)), SHIELD_Y, seed=i + self.wave)
            for i in range(SHIELDS)
        ]

    def start(self) -> None:
        self.reset()
        self.state = "playing"

    # -- queries ----------------------------------------------------------- #

    def alive_aliens(self) -> list[Alien]:
        return [a for a in self.aliens if a.alive]

    def formation_speed(self) -> float:
        alive = self.alive_aliens()
        frac = len(alive) / (COLS * ROWS)
        return (32 + 150 * (1.0 - frac)) * (1.0 + 0.16 * (self.wave - 1))

    # -- main update ------------------------------------------------------- #

    def update(self, dt: float, move: int = 0, fire: bool = False) -> None:
        """Advance one frame. `move` is -1/0/1, `fire` is edge-triggered."""
        if self.state != "playing":
            return
        dt = min(dt, 1 / 30)  # keep physics sane after a window stall

        self.update_player(dt, move, fire)
        self.update_bullets(dt)
        self.update_aliens(dt)
        self.update_alien_fire(dt)
        self.update_drifters(dt)
        self.check_collisions()

        if not self.alive_aliens():
            self.next_wave()
        elif self.lowest_alien_y() + ALIEN_H >= LANDING_Y:
            self.game_over()

        # Record only after every collision this frame has been resolved, so
        # the badge that lands the killing blow still counts toward the run.
        if self.state == "gameover":
            self.record_score()

    def update_player(self, dt: float, move: int, fire: bool) -> None:
        p = self.player
        p.invulnerable = max(0.0, p.invulnerable - dt)
        p.cooldown = max(0.0, p.cooldown - dt)

        if move:
            p.x = clamp(p.x + move * PLAYER_SPEED * dt, LEFT_WALL,
                        RIGHT_WALL - PLAYER_W)

        if fire and p.cooldown <= 0 and len(self.player_bullets) < MAX_PLAYER_BULLETS:
            p.cooldown = PLAYER_FIRE_COOLDOWN
            self.player_bullets.append(Bullet(
                x=p.center_x - 2, y=p.y - 14,
                vy=-PLAYER_BULLET_SPEED, from_player=True,
            ))
            self.shots_fired += 1
            self.play("shoot")

    def update_bullets(self, dt: float) -> None:
        for b in self.player_bullets + self.alien_bullets:
            b.update(dt)
        self.player_bullets = [
            b for b in self.player_bullets if FIELD_TOP <= b.y < HEIGHT
        ]
        self.alien_bullets = [
            b for b in self.alien_bullets if b.y + b.height <= FLOOR_Y
        ]

    def update_aliens(self, dt: float) -> None:
        alive = self.alive_aliens()
        if not alive:
            return
        step = self.direction * self.formation_speed() * dt
        min_x = min(a.x for a in alive)
        max_x = max(a.x + ALIEN_W for a in alive)

        if (step > 0 and max_x + step > RIGHT_WALL) or (step < 0 and min_x + step < LEFT_WALL):
            for a in alive:
                a.y += DROP_DISTANCE
            self.direction *= -1
        else:
            for a in alive:
                a.x += step

        # Marching animation: faster as the formation thins out.
        self.alien_anim += dt * (2.0 + 6.0 * (1.0 - len(alive) / (COLS * ROWS)))

    def update_alien_fire(self, dt: float) -> None:
        self.fire_timer -= dt
        if self.fire_timer > 0 or len(self.alien_bullets) >= 4:
            return
        self.fire_timer = max(0.28, self.rng.uniform(0.55, 1.15) - 0.05 * self.wave)

        # Only the front-most alien of a column can shoot.
        columns: dict[int, Alien] = {}
        for a in self.alive_aliens():
            current = columns.get(a.col)
            if current is None or a.y > current.y:
                columns[a.col] = a
        shooter = self.rng.choice(list(columns.values()))
        self.alien_bullets.append(Bullet(
            x=shooter.x + ALIEN_W / 2 - 3,
            y=shooter.y + ALIEN_H,
            vy=ALIEN_BULLET_SPEED,
            from_player=False,
        ))

    def update_drifters(self, dt: float) -> None:
        if not self.avatar_tiles:
            return
        self.drifter_timer = max(0.0, self.drifter_timer - dt)
        # Wave 1 allows one badge, wave 2 two, wave 3 three, and so on.
        target = max(1, self.wave)
        if len(self.drifters) < target and self.drifter_timer <= 0:
            self.spawn_drifter()
            self.drifter_timer = DRIFTER_RESPAWN

        for d in list(self.drifters):
            size = d.size
            d.x += d.vx * dt
            d.y += d.vy * dt

            # Bounce off the arena edges and keep going.
            if d.x < LEFT_WALL:
                d.x = LEFT_WALL
                d.vx = abs(d.vx)
            elif d.x + size > RIGHT_WALL:
                d.x = RIGHT_WALL - size
                d.vx = -abs(d.vx)
            if d.y < FIELD_TOP:
                d.y = FIELD_TOP
                d.vy = abs(d.vy)
            elif d.y + size > FLOOR_Y:
                d.y = FLOOR_Y - size
                d.vy = -abs(d.vy)

            self.check_drifter_collisions(d)

    def spawn_drifter(self) -> None:
        image, palette = self.rng.choice(self.avatar_tiles)
        size = image.get_width()
        # Keep the spawn band below the formation and above the bunkers, so a
        # hazard never materialises inside something it would instantly eat.
        top = FIELD_TOP + 130
        bottom = max(top, SHIELD_Y - size - 24)

        def blocked(x: float, y: float) -> bool:
            rect = pygame.Rect(int(x), int(y), size, size)
            if rect.colliderect(self.player.rect()):
                return True
            if any(rect.colliderect(s.bounds()) for s in self.shields):
                return True
            return any(rect.colliderect(a.rect()) for a in self.alive_aliens())

        x = y = 0.0
        for _ in range(16):
            x = self.rng.uniform(LEFT_WALL + 8, RIGHT_WALL - size - 8)
            y = self.rng.uniform(top, bottom)
            if not blocked(x, y):
                break

        speed = self.rng.uniform(DRIFTER_SPEED_MIN, DRIFTER_SPEED_MAX)
        angle = self.rng.uniform(math.pi * 0.15, math.pi * 0.85)
        vx = speed * math.cos(angle) * self.rng.choice((-1, 1))
        vy = speed * math.sin(angle) * self.rng.choice((-1, 1))
        self.drifters.append(Drifter(image, palette, x, y, vx, vy))

    def check_drifter_collisions(self, d: Drifter) -> None:
        """Damage is mutual, but only your bullets and your ship kill a badge.

        Only a player bullet (for points) or a collision with the player can
        take a badge out. Alien fire is swallowed, aliens deflect it unharmed,
        and bunkers lose a bite as the badge ricochets off them.
        """
        rect = d.rect()
        killed = False

        # Your shots destroy it (and pay out).
        keep = []
        for b in self.player_bullets:
            if rect.colliderect(b.sweep_rect()):
                killed = True
                self.shots_hit += 1
                self.score += DRIFTER_POINTS
            else:
                keep.append(b)
        self.player_bullets = keep

        # Enemy fire is swallowed, but the badge keeps floating.
        self.alien_bullets = [
            b for b in self.alien_bullets
            if not rect.colliderect(b.sweep_rect())
        ]

        # Aliens are solid to the badge: it ricochets off the group it hit
        # without harming them.
        rect = d.rect()
        touched = [a for a in self.alive_aliens() if rect.colliderect(a.rect())]
        if touched:
            group = touched[0].rect()
            for a in touched[1:]:
                group = group.union(a.rect())
            self._bounce_drifter(d, group)

        # Bunkers take a bite and deflect the badge.
        rect = d.rect()
        for s in self.shields:
            if s.bounds().colliderect(rect) and s.erase_rect(rect):
                self._bounce_drifter(d, s.bounds())
                rect = d.rect()

        # Hitting the player kills the player and the badge. Do this last:
        # player_hit() clears all bullets.
        if d.rect().colliderect(self.player.rect()):
            killed = True
            if self.player.invulnerable <= 0:
                self.player_hit()

        if killed:
            self.destroy_drifter(d)

    def _bounce_drifter(self, d: Drifter, obstacle: pygame.Rect) -> None:
        """Ricochet a badge off `obstacle`, reflecting on the shallower axis."""
        rect = d.rect()
        overlap_x = min(rect.right - obstacle.left, obstacle.right - rect.left)
        overlap_y = min(rect.bottom - obstacle.top, obstacle.bottom - rect.top)
        if overlap_x < overlap_y:
            if rect.centerx < obstacle.centerx:
                d.x = obstacle.left - d.size
                d.vx = -abs(d.vx)
            else:
                d.x = obstacle.right
                d.vx = abs(d.vx)
        else:
            if rect.centery < obstacle.centery:
                d.y = obstacle.top - d.size
                d.vy = -abs(d.vy)
            else:
                d.y = obstacle.bottom
                d.vy = abs(d.vy)
        # Never let a ricochet shove the badge through the arena walls.
        d.x = clamp(d.x, LEFT_WALL, RIGHT_WALL - d.size)
        d.y = clamp(d.y, FIELD_TOP, FLOOR_Y - d.size)

    def destroy_drifter(self, d: Drifter) -> None:
        try:
            self.drifters.remove(d)
        except ValueError:
            pass
        self.avatars_killed += 1
        self.explode(d.x + d.size / 2, d.y + d.size / 2, d.palette)
        self.drifter_timer = DRIFTER_RESPAWN

    def explode(self, x: float, y: float,
                palette: list[tuple[int, int, int]]) -> None:
        self.play("blast")
        for _ in range(36):
            angle = self.rng.uniform(0.0, math.tau)
            speed = self.rng.uniform(50.0, 330.0)
            life = self.rng.uniform(0.35, 0.85)
            colour = self.rng.choice(palette + [(255, 255, 255)])
            self.debris.append([x, y, math.cos(angle) * speed,
                                math.sin(angle) * speed, life, life,
                                colour, self.rng.choice((2, 3, 3, 4, 5))])
        for _ in range(2):
            colour = self.rng.choice(palette)
            self.rings.append([x, y, 6.0, 0.34, colour])
        self.flashes.append([x, y, 0.10, 0.10, (255, 255, 255), 30.0])
        self.flashes.append([x, y, 0.22, 0.22,
                             self.rng.choice(palette), 22.0])

    def check_collisions(self) -> None:
        # Player bullets: bunkers first, then aliens (highest one wins).
        surviving = []
        for b in self.player_bullets:
            path = b.sweep_rect()
            if self.damage_shield(path, b.vy, by_player=True):
                continue
            hit = None
            for a in sorted(self.alive_aliens(), key=lambda a: a.y):
                if path.colliderect(a.rect()):
                    hit = a
                    break
            if hit is None:
                surviving.append(b)
            else:
                hit.alive = False
                self.shots_hit += 1
                self.score += ROW_POINTS[hit.row]
                self.play("hit")
                self.spawn_debris(hit)
        self.player_bullets = surviving

        # Alien bullets: bunkers first, then the player.
        player_rect = self.player.rect()
        remaining = []
        for b in self.alien_bullets:
            path = b.sweep_rect()
            if self.damage_shield(path, b.vy, by_player=False):
                continue
            if self.player.invulnerable <= 0 and path.colliderect(player_rect):
                self.play("boom")
                self.player_hit()
            else:
                remaining.append(b)
        self.alien_bullets = remaining

        # Aliens marching down through a bunker chew a hole in it.
        for a in self.alive_aliens():
            area = a.rect()
            for s in self.shields:
                if s.bounds().colliderect(area):
                    s.erase_rect(area)

    def damage_shield(self, rect: pygame.Rect, vy: float,
                      by_player: bool = False) -> bool:
        for s in self.shields:
            cell = s.hit_cell(rect, vy)
            if cell is not None:
                destroyed = s.damage(*cell)
                if by_player:
                    self.bunker_cells_shot += destroyed
                self.play("clank")
                self.spawn_sparks(s.x + cell[1] * s.cell + s.cell / 2,
                                  s.y + cell[0] * s.cell + s.cell / 2)
                return True
        return False

    def spawn_debris(self, alien: Alien) -> None:
        cx, cy = alien.x + ALIEN_W / 2, alien.y + ALIEN_H / 2
        for _ in range(8):
            angle = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(60, 220)
            life = 0.4
            self.debris.append([cx, cy, math.cos(angle) * speed,
                                math.sin(angle) * speed, life, life,
                                (255, 230, 160), 3])

    def spawn_sparks(self, x: float, y: float) -> None:
        for _ in range(4):
            angle = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(30, 110)
            life = 0.25
            self.debris.append([x, y, math.cos(angle) * speed,
                                math.sin(angle) * speed, life, life,
                                (140, 255, 190), 2])

    def lowest_alien_y(self) -> float:
        alive = self.alive_aliens()
        return max((a.y for a in alive), default=0.0)

    def player_hit(self) -> None:
        self.lives -= 1
        self.alien_bullets.clear()
        self.player_bullets.clear()
        self.player.x = WIDTH / 2 - PLAYER_W / 2
        self.player.invulnerable = 1.6
        if self.lives <= 0:
            self.game_over()

    def game_over(self) -> None:
        if self.state == "playing":
            self.state = "gameover"
            self.pending_record = True
            self.player_bullets.clear()
            self.alien_bullets.clear()
            self.play("boom")

    def run_stats(self) -> dict[str, float]:
        """Totals that go on the high-score table for the current run."""
        bunker = (100.0 * self.bunker_cells_shot / self.bunker_cells_total
                  if self.bunker_cells_total else 0.0)
        accuracy = (100.0 * self.shots_hit / self.shots_fired
                    if self.shots_fired else 0.0)
        return {
            "bunker": round(clamp(bunker, 0.0, 100.0), 2),
            "accuracy": round(clamp(accuracy, 0.0, 100.0), 2),
            "avatars": self.avatars_killed,
        }

    def score_entry(self) -> dict[str, float]:
        stats = self.run_stats()
        return {
            "score": self.score,
            "wave": self.wave,
            "avatars": stats["avatars"],
            "bunker": stats["bunker"],
            "accuracy": stats["accuracy"],
        }

    def record_score(self) -> None:
        """Save this run to the leaderboard exactly once."""
        if not self.pending_record:
            return
        self.pending_record = False
        self.last_rank = self.leaderboard.add(self.score_entry())

    def next_wave(self) -> None:
        self.wave += 1
        self.score += 100
        self.play("wave")
        self.spawn_wave()

    def toggle_pause(self) -> None:
        if self.state == "playing":
            self.state = "paused"
        elif self.state == "paused":
            self.state = "playing"

    def show_scores(self) -> None:
        if self.state in ("title", "paused", "playing", "gameover"):
            self.score_return_state = self.state
            self.score_scroll = 0
            self.state = "scores"

    def close_scores(self) -> None:
        if self.state == "scores":
            self.state = self.score_return_state

    def scroll_scores(self, delta: int) -> None:
        if self.state != "scores":
            return
        highest = max(0, len(self.leaderboard.entries) - LEADERBOARD_ROWS)
        self.score_scroll = int(clamp(self.score_scroll + delta, 0, highest))

    def play(self, name: str) -> None:
        sound = self.sounds.get(name)
        if sound:
            sound.play()

    # -- rendering --------------------------------------------------------- #

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_background(surface)
        self.draw_walls(surface)
        if self.state not in ("title", "scores"):
            self.draw_aliens(surface)
            self.draw_shields(surface)
            self.draw_drifters(surface)
            self.draw_bullets(surface)
            self.draw_player(surface)
            self.draw_debris(surface)
            self.draw_hud(surface)
        self.draw_overlay(surface)

    def present(self, screen: pygame.Surface) -> None:
        """Blit the fixed 800x600 canvas onto any window/fullscreen size."""
        sw, sh = screen.get_size()
        if (sw, sh) == (WIDTH, HEIGHT):
            screen.blit(self.canvas, (0, 0))
            return
        scale = min(sw / WIDTH, sh / HEIGHT)
        w = max(1, int(WIDTH * scale))
        h = max(1, int(HEIGHT * scale))
        screen.fill((0, 0, 0))
        screen.blit(pygame.transform.smoothscale(self.canvas, (w, h)),
                    ((sw - w) // 2, (sh - h) // 2))

    def draw_background(self, surface: pygame.Surface) -> None:
        for y in range(0, HEIGHT, 6):
            t = y / HEIGHT
            color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
            pygame.draw.rect(surface, color, (0, y, WIDTH, 6))
        if self.pulp_bg is not None:
            surface.blit(self.pulp_bg, (0, 0))
        for x, y, size, speed in self.stars:
            twinkle = 90 + int(80 * (0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 900 + speed)))
            pygame.draw.rect(surface, (twinkle, twinkle, min(255, twinkle + 40)),
                             (int(x), int(y), size, size))

    def draw_walls(self, surface: pygame.Surface) -> None:
        for x in (LEFT_WALL, RIGHT_WALL):
            pygame.draw.line(surface, (45, 55, 95), (x, FIELD_TOP), (x, FLOOR_Y), 2)
        pygame.draw.line(surface, (45, 55, 95), (LEFT_WALL, FLOOR_Y),
                         (RIGHT_WALL, FLOOR_Y), 2)

    def draw_aliens(self, surface: pygame.Surface) -> None:
        frame = int(self.alien_anim) % 2
        for a in self.aliens:
            if not a.alive:
                continue
            color = ROW_COLORS[a.row % len(ROW_COLORS)]
            x, y = int(a.x), int(a.y)
            self.draw_alien_sprite(surface, x, y, color, frame)

    def draw_alien_sprite(self, surface: pygame.Surface, x: int, y: int,
                          color: tuple[int, int, int], frame: int) -> None:
        w, h = ALIEN_W, ALIEN_H
        body = pygame.Rect(x + 4, y + 2, w - 8, h - 10)
        pygame.draw.rect(surface, color, body, border_radius=4)
        # antennae / head bumps
        pygame.draw.rect(surface, color, (x + 2, y, 6, 6), border_radius=2)
        pygame.draw.rect(surface, color, (x + w - 8, y, 6, 6), border_radius=2)
        # eyes
        pygame.draw.rect(surface, (20, 20, 35), (x + 10, y + 8, 4, 4))
        pygame.draw.rect(surface, (20, 20, 35), (x + w - 14, y + 8, 4, 4))
        # legs alternate between two frames
        if frame == 0:
            pygame.draw.rect(surface, color, (x, y + h - 7, 7, 6))
            pygame.draw.rect(surface, color, (x + w - 7, y + h - 7, 7, 6))
        else:
            pygame.draw.rect(surface, color, (x + 6, y + h - 7, 7, 7))
            pygame.draw.rect(surface, color, (x + w - 13, y + h - 7, 7, 7))

    def draw_shields(self, surface: pygame.Surface) -> None:
        for s in self.shields:
            s.draw(surface)

    def draw_drifters(self, surface: pygame.Surface) -> None:
        for d in self.drifters:
            surface.blit(d.image, (int(d.x), int(d.y)))

    def draw_bullets(self, surface: pygame.Surface) -> None:
        for b in self.player_bullets:
            r = b.rect()
            pygame.draw.rect(surface, PLAYER_BULLET_COLOR, r, border_radius=2)
            glow = pygame.Surface((r.width + 8, r.height + 8), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*PLAYER_BULLET_COLOR, 60), glow.get_rect(), border_radius=4)
            surface.blit(glow, (r.x - 4, r.y - 4))
        for b in self.alien_bullets:
            r = b.rect()
            pygame.draw.rect(surface, ALIEN_BULLET_COLOR, r, border_radius=3)

    def draw_player(self, surface: pygame.Surface) -> None:
        p = self.player
        if p.invulnerable > 0 and int(p.invulnerable * 12) % 2 == 0:
            return
        x, y = int(p.x), int(p.y)
        pygame.draw.rect(surface, PLAYER_COLOR, (x + 16, y, 14, 6), border_radius=2)
        pygame.draw.rect(surface, PLAYER_COLOR, (x + 4, y + 6, PLAYER_W - 8, 6))
        pygame.draw.rect(surface, PLAYER_COLOR, (x, y + 12, PLAYER_W, 6), border_radius=3)
        pygame.draw.rect(surface, (10, 30, 22), (x + 20, y + 2, 6, 4))

    def draw_debris(self, surface: pygame.Surface) -> None:
        for flash in self.flashes:
            fade = max(0.0, min(1.0, flash[2] / flash[3]))
            glow = fade ** 0.6
            colour = (int(flash[4][0] * glow), int(flash[4][1] * glow),
                      int(flash[4][2] * glow))
            radius = int(flash[5] * fade)
            if radius > 0:
                pygame.draw.circle(surface, colour,
                                   (int(flash[0]), int(flash[1])), radius)
        for d in self.debris:
            fade = max(0.0, min(1.0, d[4] / d[5]))
            colour = (int(d[6][0] * fade), int(d[6][1] * fade),
                      int(d[6][2] * fade))
            size = int(d[7])
            pygame.draw.rect(surface, colour, (int(d[0]), int(d[1]), size, size))
        for ring in self.rings:
            fade = max(0.0, min(1.0, ring[3] / 0.34))
            colour = (int(ring[4][0] * fade), int(ring[4][1] * fade),
                      int(ring[4][2] * fade))
            pygame.draw.circle(surface, colour,
                               (int(ring[0]), int(ring[1])), int(ring[2]), 2)

    def draw_hud(self, surface: pygame.Surface) -> None:
        score = self.font_small.render(f"SCORE {self.score:05d}", True, UI_COLOR)
        wave = self.font_small.render(f"WAVE {self.wave}", True, UI_DIM)
        surface.blit(score, (LEFT_WALL, 24))
        surface.blit(wave, (WIDTH // 2 - wave.get_width() // 2, 24))
        if self.music_genre:
            label = self.font_small.render(
                f"({self.music_genre})", True, (80, 88, 130))
            surface.blit(label, (WIDTH // 2 - label.get_width() // 2, 44))

        # lives as tiny ships, right-aligned
        for i in range(max(0, self.lives)):
            x = RIGHT_WALL - 26 * (i + 1)
            pygame.draw.rect(surface, PLAYER_COLOR, (x, 28, 20, 4), border_radius=2)
            pygame.draw.rect(surface, PLAYER_COLOR, (x + 4, 24, 12, 4), border_radius=2)

    def draw_leaderboard(self, surface: pygame.Surface) -> None:
        """Scrollable top-100 table of run scores and shooting stats."""
        title = self.font_big.render("HIGH SCORES", True, (255, 240, 190))
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 16))
        caption = self.font_tiny.render(
            "BUNKER % = BUNKER CELLS WRECKED BY YOUR OWN BULLETS",
            True, UI_DIM)
        surface.blit(caption, (WIDTH // 2 - caption.get_width() // 2, 84))

        columns = (
            ("RANK", 90),
            ("SCORE", 210),
            ("WAVE", 280),
            ("AVATARS", 390),
            ("BUNKER", 530),
            ("ACCURACY", 690),
        )
        for label, right in columns:
            text = self.font_tiny.render(label, True, (255, 220, 120))
            surface.blit(text, (right - text.get_width(), 112))
        pygame.draw.line(surface, (90, 96, 140), (44, 132), (756, 132), 1)

        entries = self.leaderboard.entries
        if not entries:
            empty = self.font_mid.render("NO SCORES YET", True, UI_DIM)
            hint = self.font_small.render(
                "Finish a run to claim a spot.", True, UI_DIM)
            surface.blit(empty, (WIDTH // 2 - empty.get_width() // 2, 260))
            surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 306))
        else:
            start = self.score_scroll
            visible = entries[start:start + LEADERBOARD_ROWS]
            rank_colors = {1: (255, 225, 120), 2: (220, 225, 240),
                           3: (230, 170, 120)}
            for offset, entry in enumerate(visible):
                rank = start + offset + 1
                y = 148 + offset * 25
                highlighted = (self.score_return_state == "gameover"
                               and rank == self.last_rank)
                if highlighted:
                    surface.fill((45, 42, 34), (44, y - 2, 712, 22))
                colour = rank_colors.get(rank, UI_COLOR)
                if highlighted:
                    colour = (255, 230, 140)
                values = (
                    (f"{rank}", 90),
                    (f"{int(entry['score'])}", 210),
                    (f"{int(entry['wave'])}", 280),
                    (f"{int(entry['avatars'])}", 390),
                    (f"{entry['bunker']:.1f}%", 530),
                    (f"{entry['accuracy']:.1f}%", 690),
                )
                for value, right in values:
                    text = self.font_small.render(value, True, colour)
                    surface.blit(text, (right - text.get_width(), y))

            end = start + len(visible)
            footer = self.font_tiny.render(
                f"SHOWING {start + 1}-{end} OF {len(entries)}", True, UI_DIM)
            surface.blit(footer, (WIDTH // 2 - footer.get_width() // 2, 540))

        hint = self.font_tiny.render(
            "UP / DOWN  SCROLL      L / ESC  BACK", True, UI_DIM)
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 566))

    def draw_overlay(self, surface: pygame.Surface) -> None:
        if self.state == "playing":
            return
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((6, 8, 20, 220 if self.state == "scores" else 190))
        surface.blit(shade, (0, 0))

        if self.state == "scores":
            self.draw_leaderboard(surface)
        elif self.state == "title":
            title = self.font_big.render("SPACE INVADERS", True, (255, 255, 255))
            surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 170))

            rows = [
                ("MOVE", "ARROWS  or  A / D"),
                ("FIRE", "SPACE"),
                ("PAUSE", "P"),
                ("SCORES", "L  leaderboard"),
                ("FULLSCREEN", "F11"),
                ("MUSIC", "M  mute"),
                ("QUIT", "ESC"),
            ]
            key_x = WIDTH // 2 - 190
            desc_x = WIDTH // 2 - 30
            for i, (key, desc) in enumerate(rows):
                y = 274 + i * 28
                surface.blit(self.font_small.render(key, True, (255, 220, 120)), (key_x, y))
                surface.blit(self.font_small.render(desc, True, UI_COLOR), (desc_x, y))

            pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 350)
            start_color = tuple(int(150 + 105 * pulse) for _ in range(3))
            start = self.font_mid.render("PRESS ENTER TO START", True, start_color)
            # Below the painted cover title, above the floor line.
            surface.blit(start, (WIDTH // 2 - start.get_width() // 2, 524))
        elif self.state == "paused":
            title = self.font_big.render("PAUSED", True, UI_COLOR)
            hint = self.font_small.render("press P to resume", True, UI_DIM)
            surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 250))
            surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 320))
        elif self.state == "gameover":
            stats = self.run_stats()
            title = self.font_big.render("GAME OVER", True, (255, 110, 130))
            score = self.font_mid.render(
                f"Score {self.score}   Wave {self.wave}", True, UI_COLOR)
            line = self.font_small.render(
                f"AVATARS KILLED {stats['avatars']}    "
                f"BUNKERS SHOT {stats['bunker']:.1f}%    "
                f"ACCURACY {stats['accuracy']:.1f}%", True, UI_COLOR)
            if self.last_rank is not None:
                rank = self.font_mid.render(
                    f"NEW HIGH SCORE  #{self.last_rank}", True,
                    (255, 225, 120))
            else:
                rank = self.font_small.render(
                    "DID NOT MAKE THE TOP 100", True, UI_DIM)
            hint = self.font_small.render(
                "press ENTER to play again", True, (255, 220, 120))
            scores_hint = self.font_small.render(
                "press L for high scores", True, UI_DIM)
            surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 138))
            surface.blit(score, (WIDTH // 2 - score.get_width() // 2, 220))
            surface.blit(line, (WIDTH // 2 - line.get_width() // 2, 270))
            surface.blit(rank, (WIDTH // 2 - rank.get_width() // 2, 304))
            surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 374))
            surface.blit(scores_hint,
                         (WIDTH // 2 - scores_hint.get_width() // 2, 404))

    def update_effects(self, dt: float) -> None:
        for d in self.debris:
            d[0] += d[2] * dt
            d[1] += d[3] * dt
            d[4] -= dt
        self.debris = [d for d in self.debris if d[4] > 0]
        for ring in self.rings:
            ring[2] += 220.0 * dt
            ring[3] -= dt
        self.rings = [r for r in self.rings if r[3] > 0]
        for flash in self.flashes:
            flash[2] -= dt
        self.flashes = [f for f in self.flashes if f[2] > 0]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def read_input() -> tuple[int, bool]:
    keys = pygame.key.get_pressed()
    move = int(keys[pygame.K_RIGHT] or keys[pygame.K_d]) - int(keys[pygame.K_LEFT] or keys[pygame.K_a])
    return move, keys[pygame.K_SPACE]


class MusicPlayer:
    """Composes tracks on a worker thread and loops them, crossfaded."""

    def __init__(self, enabled: bool = True, volume: float = 0.32) -> None:
        self.volume = max(0.0, min(1.0, volume))
        self.muted = False
        self.enabled = bool(enabled and metal is not None
                           and pygame.mixer.get_init())
        self.thread: threading.Thread | None = None
        self.pending: bytes | None = None
        self.lock = threading.Lock()
        self.want_new = False
        self.want_genre: str | None = None
        self.genre: str | None = None
        self.current: pygame.mixer.Sound | None = None
        self.channels: list[pygame.mixer.Channel] = []
        self.active = 0
        if self.enabled:
            pygame.mixer.set_num_channels(16)
            self.channels = [pygame.mixer.Channel(14), pygame.mixer.Channel(15)]

    def request(self, genre: str | None = None) -> None:
        """Compose a brand-new song; it fades in as soon as it is rendered."""
        if not self.enabled:
            return
        if self.thread and self.thread.is_alive():
            self.want_new = True
            self.want_genre = genre
        else:
            self._start(genre)

    def _start(self, genre: str | None = None) -> None:
        self.want_new = False
        if genre is None and metal is not None:
            genre = random.choice(metal.GENRES)
        self.genre = genre
        seed = random.randrange(1 << 30)
        self.thread = threading.Thread(target=self._compose, args=(seed, genre),
                                       daemon=True)
        self.thread.start()

    def _compose(self, seed: int, genre: str | None) -> None:
        try:
            data: bytes | None = metal.compose(seed, genre=genre)
        except Exception:
            data = None
        with self.lock:
            self.pending = data

    def update(self) -> None:
        if not self.enabled:
            return
        if self.want_new and not (self.thread and self.thread.is_alive()):
            self._start(self.want_genre)
        with self.lock:
            data, self.pending = self.pending, None
        if not data:
            return
        try:
            sound = pygame.mixer.Sound(buffer=data)
        except Exception:
            return
        new_volume = 0.0 if self.muted else self.volume
        old = self.channels[self.active]
        new = self.channels[1 - self.active]
        old.fadeout(600)
        new.set_volume(new_volume)
        new.play(sound, loops=-1, fade_ms=600)
        self.active = 1 - self.active
        self.current = sound

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        for ch in self.channels:
            ch.set_volume(0.0 if self.muted else self.volume)
        return self.muted


def main() -> int:
    parser = argparse.ArgumentParser(description="Space Invaders")
    parser.add_argument("--selftest", action="store_true",
                        help="run a headless simulation and exit (no window)")
    parser.add_argument("--duration", type=float, default=90.0,
                        help="seconds of gameplay to simulate in --selftest")
    parser.add_argument("--no-music", action="store_true",
                        help="start with the soundtrack disabled")
    parser.add_argument("--music-volume", type=float, default=0.32,
                        help="music volume, 0.0 - 1.0 (default 0.32)")
    parser.add_argument("--export-music", metavar="FILE",
                        help="render one track to a .wav file and exit")
    parser.add_argument("--export-genre", metavar="GENRE",
                        choices=(metal.GENRES if metal is not None else None),
                        help="genre for --export-music (default: random)")
    args = parser.parse_args()

    if args.selftest:
        return selftest(args.duration)

    if args.export_music:
        if metal is None:
            print("--export-music needs numpy: pip install numpy")
            return 1
        genre = args.export_genre or metal.pick_genre()
        path = metal.compose_wav(None, args.export_music, genre=genre)
        print(f"wrote {path} ({genre})")
        return 0

    pygame.mixer.pre_init(44100, -16, 2, 512)
    pygame.init()
    pygame.display.set_caption("Space Invaders")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    clock = pygame.time.Clock()

    game = Game()
    music_player = MusicPlayer(enabled=not args.no_music,
                              volume=args.music_volume)
    if not args.no_music and not music_player.enabled:
        print("music disabled (needs numpy: pip install numpy)")

    fire_was_down = False
    fullscreen = False
    running = True

    def toggle_fullscreen() -> None:
        nonlocal screen, fullscreen
        fullscreen = not fullscreen
        if fullscreen:
            screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
        pygame.mouse.set_visible(not fullscreen)

    # The title screen gets a track while the game is being set up; every
    # new game and every new wave composes another one.
    music_player.request()
    last_wave = game.wave

    while running:
        dt = clock.tick(FPS) / 1000.0
        music_player.update()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                size = (max(event.w, 320), max(event.h, 240))
                screen = pygame.display.set_mode(size, pygame.RESIZABLE)
            elif event.type == pygame.KEYDOWN:
                if game.state == "scores":
                    if event.key in (pygame.K_ESCAPE, pygame.K_l,
                                     pygame.K_RETURN):
                        game.close_scores()
                    elif event.key in (pygame.K_UP, pygame.K_w):
                        game.scroll_scores(-1)
                    elif event.key in (pygame.K_DOWN, pygame.K_s):
                        game.scroll_scores(1)
                    elif event.key == pygame.K_PAGEUP:
                        game.scroll_scores(-LEADERBOARD_ROWS)
                    elif event.key == pygame.K_PAGEDOWN:
                        game.scroll_scores(LEADERBOARD_ROWS)
                    elif event.key == pygame.K_HOME:
                        game.scroll_scores(-LEADERBOARD_SIZE)
                    elif event.key == pygame.K_END:
                        game.scroll_scores(LEADERBOARD_SIZE)
                    continue
                if event.key == pygame.K_ESCAPE:
                    if fullscreen:
                        toggle_fullscreen()
                    else:
                        running = False
                elif event.key == pygame.K_F11 or (
                        event.key == pygame.K_RETURN and event.mod & pygame.KMOD_ALT):
                    toggle_fullscreen()
                elif event.key == pygame.K_l:
                    game.show_scores()
                elif event.key == pygame.K_RETURN and game.state in ("title", "gameover"):
                    game.start()
                    music_player.request(game.music_genre)
                    last_wave = game.wave
                elif event.key == pygame.K_p:
                    game.toggle_pause()
                elif event.key == pygame.K_m:
                    music_player.toggle_mute()

        move, fire_down = read_input()
        fire = fire_down and not fire_was_down  # only listen for fresh presses
        fire_was_down = fire_down

        if game.state == "playing":
            game.update(dt, move, fire)
            game.update_effects(dt)
            if game.wave != last_wave:
                last_wave = game.wave
                music_player.request(game.music_genre)

        game.draw(game.canvas)
        if music_player.muted and game.state not in ("title", "scores"):
            muted = game.font_small.render("MUSIC OFF", True, UI_DIM)
            game.canvas.blit(muted, (RIGHT_WALL - muted.get_width(), 44))
        game.present(screen)
        pygame.display.flip()

    pygame.quit()
    return 0


def selftest(seconds: float) -> int:
    """Headless smoke test: play with pseudo-random input and assert invariants."""
    import os
    import tempfile

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    tempdir = tempfile.TemporaryDirectory(prefix="space_invaders_selftest_")
    scores = Leaderboard(Path(tempdir.name) / "leaderboard.json")
    game = Game(seed=1234, leaderboard=scores)
    game.start()

    check_shields(scores)
    check_drifters(scores)
    check_leaderboard()
    check_stats()
    check_scaling(game)
    check_backgrounds(scores)
    check_music()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))

    dt = 1 / 60
    frames = int(seconds / dt)
    rng = random.Random(7)
    max_aliens_seen = 0
    waves_seen = 1
    hits = 0
    move = 0
    eroded_seen = False

    for frame in range(frames):
        if frame % 25 == 0:
            move = rng.choice((-1, 0, 0, 1))
        fire = frame % 3 == 0
        if game.state == "gameover":
            game.start()
        game.update(dt, move, fire)
        game.update_effects(dt)
        game.draw(game.canvas)
        game.present(screen)
        eroded_seen = eroded_seen or any(
            s.alive_cells() < s.cols * s.rows for s in game.shields)
        max_aliens_seen = max(max_aliens_seen, len(game.alive_aliens()))
        waves_seen = max(waves_seen, game.wave)
        hits = max(hits, game.score)
        for b in game.player_bullets + game.alien_bullets:
            r = b.rect()
            assert -50 <= r.x <= WIDTH + 50, f"bullet escaped horizontally: {r}"
            assert -100 <= r.y <= HEIGHT + 100, f"bullet escaped vertically: {r}"
        for a in game.alive_aliens():
            r = a.rect()
            assert LEFT_WALL - DROP_DISTANCE <= r.x <= RIGHT_WALL, f"alien out of bounds: {r}"
            assert 0 <= r.y <= FLOOR_Y + ALIEN_H, f"alien below floor without game over: {r}"
        assert 0 <= game.shots_hit <= game.shots_fired
        assert 0 <= game.bunker_cells_shot <= game.bunker_cells_total
        stats = game.run_stats()
        assert 0.0 <= stats["bunker"] <= 100.0
        assert 0.0 <= stats["accuracy"] <= 100.0

    print(f"selftest ok: {frames} frames, max aliens {max_aliens_seen}, "
          f"waves {waves_seen}, score {hits}, state {game.state}, "
          f"shields eroded: {eroded_seen}")
    tempdir.cleanup()
    pygame.quit()
    return 0


def check_shields(leaderboard: Leaderboard | None = None) -> None:
    """Direct checks: bunkers exist, stop bullets, and erode gradually."""
    game = Game(seed=5, leaderboard=leaderboard)
    game.start()
    assert len(game.shields) == SHIELDS

    shield = game.shields[1]
    full = shield.alive_cells()
    assert 0 < full < SHIELD_COLS * SHIELD_ROWS, "shield shape not carved"
    probe = Shield(0, 0, seed=8)
    before = probe.alive_cells()
    lost = probe.damage(6, 11)
    assert lost == before - probe.alive_cells() > 0, "damage count is wrong"
    cx = shield.x + shield.width / 2

    # A falling enemy bullet is absorbed by the bunker and chips it.
    game.alien_bullets.append(Bullet(x=cx - 3, y=shield.y - 20,
                                     vy=ALIEN_BULLET_SPEED, from_player=False))
    for _ in range(12):
        game.update(1 / 60)
    assert not game.alien_bullets, "enemy bullet passed through the bunker"
    assert shield.alive_cells() < full, "bunker did not erode"

    # Hits in the same spot tunnel a hole instead of dissolving the whole thing.
    game.player.invulnerable = 99
    for _ in range(10):
        game.alien_bullets.append(Bullet(x=cx - 3, y=shield.y - 2,
                                         vy=ALIEN_BULLET_SPEED, from_player=False))
        game.update(1 / 60)
    assert 0 < shield.alive_cells() < full, "bunker eroded too much or not at all"

    # Player shots chip bunkers too (classic behaviour). Aim at an intact
    # column so the earlier tunnel doesn't swallow the shot.
    before = shield.alive_cells()
    game.player_bullets.append(Bullet(x=cx - 20, y=shield.y + shield.height - 2,
                                      vy=-PLAYER_BULLET_SPEED, from_player=True))
    for _ in range(8):
        game.update(1 / 60)
    assert shield.alive_cells() < before, "player shots did not chip the bunker"

    # Aliens marching through a bunker destroy the cells they touch.
    bunker = game.shields[2]
    before = bunker.alive_cells()
    alien = game.alive_aliens()[0]
    alien.x = bunker.x + 4
    alien.y = bunker.y + 4
    game.update(1 / 60)
    assert bunker.alive_cells() < before, "aliens did not crush the bunker"


def check_drifters(leaderboard: Leaderboard | None = None) -> None:
    """Badges bounce, only your bullets/ship kill them, and one per wave."""
    probe = Game(seed=5, leaderboard=leaderboard)
    if not probe.avatar_tiles:
        print(f"drifters: {AVATAR_SHEET} not found, skipping hazard checks")
        return
    assert len(probe.avatar_tiles) == 6, "expected six avatars on the sheet"
    image, palette = probe.avatar_tiles[0]
    assert image.get_width() > ALIEN_W and image.get_height() > ALIEN_H
    assert palette, "avatar palette came out empty"

    def fresh() -> Game:
        game = Game(seed=5, leaderboard=leaderboard)
        game.start()
        return game

    # Bounces off the arena edges.
    game = fresh()
    drifter = Drifter(image, palette, LEFT_WALL + 1, 300, -100, 40)
    game.drifters = [drifter]
    game.update_drifters(0.05)
    assert drifter.vx > 0 and drifter.x >= LEFT_WALL
    drifter = Drifter(image, palette, 400, FLOOR_Y - 10, 50, 100)
    game.drifters = [drifter]
    game.update_drifters(0.05)
    assert drifter.vy < 0 and drifter.y + drifter.size <= FLOOR_Y

    # A player bullet destroys it, pays points, and makes palette-coloured FX.
    game = fresh()
    game.score = 0
    game.drifters = [Drifter(image, palette, 400, 300, 0, 0)]
    game.player_bullets.append(Bullet(410, 310, -PLAYER_BULLET_SPEED, True))
    game.update_drifters(1 / 60)
    assert not game.drifters and game.score == DRIFTER_POINTS
    assert game.debris and game.rings and game.flashes

    # Enemy fire is swallowed but does NOT pop the badge.
    game = fresh()
    game.drifters = [Drifter(image, palette, 400, 300, 0, 0)]
    game.alien_bullets.append(Bullet(408, 310, ALIEN_BULLET_SPEED, False))
    game.update_drifters(1 / 60)
    assert game.drifters and not game.alien_bullets

    # Aliens are solid but unharmed: the badge bounces off and survives.
    game = fresh()
    target = game.aliens[0]
    for a in game.aliens:
        if a is not target:
            a.alive = False
    game.drifters = [Drifter(image, palette, target.x - DRIFTER_SIZE + 4,
                             target.y, 80, 0)]
    game.update_drifters(1 / 60)
    assert game.drifters and target.alive
    assert game.drifters[0].vx < 0, "badge did not bounce off the alien"

    # It eats a hole in a bunker and ricochets off it.
    game = fresh()
    bunker = game.shields[1]
    cells = bunker.alive_cells()
    game.drifters = [Drifter(image, palette, bunker.x + 10,
                             bunker.y - DRIFTER_SIZE + 4, 0, 80)]
    game.update_drifters(1 / 60)
    assert game.drifters and bunker.alive_cells() < cells
    assert game.drifters[0].vy < 0, "badge did not bounce off the bunker"

    # It kills the player too.
    game = fresh()
    game.player.invulnerable = 0
    lives = game.lives
    game.drifters = [Drifter(image, palette, game.player.x + 5,
                             game.player.y - 10, 0, 0)]
    game.update_drifters(1 / 60)
    assert not game.drifters and game.lives == lives - 1

    # And one spawns on its own shortly after a wave starts...
    game = fresh()
    game.update_drifters(DRIFTER_SPAWN_DELAY + 0.1)
    assert len(game.drifters) == 1

    # ...but never more than the wave number: 1, 2, 3, ...
    for wave, expected in ((1, 1), (2, 2), (3, 3), (7, 7)):
        game = fresh()
        game.wave = wave
        game.drifters = []
        game.drifter_timer = 0.0
        peak = 0
        for _ in range(60 * 30):
            game.update_drifters(1 / 60)
            game.drifter_timer = 0.0  # try to force a spawn every frame
            peak = max(peak, len(game.drifters))
        assert peak == expected, f"wave {wave}: peak {peak}, expected {expected}"


def check_leaderboard() -> None:
    """The table keeps the best 100, sorts correctly, and survives reloads."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "leaderboard.json"
        board = Leaderboard(path)
        assert board.entries == [], "new leaderboard should be empty"

        for i in range(LEADERBOARD_SIZE + 12):
            board.add({
                "score": (i * 137) % 100000,
                "wave": 1 + i % 9,
                "avatars": i % 4,
                "bunker": (i * 1.7) % 100,
                "accuracy": (i * 3.1) % 100,
            })
        assert len(board.entries) == LEADERBOARD_SIZE, (
            f"kept {len(board.entries)} entries, expected {LEADERBOARD_SIZE}")
        assert board.entries == sorted(board.entries, key=_score_order), (
            "leaderboard is not sorted")
        assert Leaderboard(path).entries == board.entries, (
            "leaderboard did not survive a reload")

        rank = board.add({"score": 10 ** 6, "wave": 7, "avatars": 9,
                          "bunker": 42.5, "accuracy": 88.8})
        assert rank == 1, f"top score ranked {rank}"
        assert len(board.entries) == LEADERBOARD_SIZE

        # Higher waves win score ties, then better accuracy.
        ties = Leaderboard(Path(tmp) / "ties.json")
        ties.add({"score": 70, "wave": 2, "avatars": 0,
                  "bunker": 0, "accuracy": 10})
        ties.add({"score": 70, "wave": 5, "avatars": 0,
                  "bunker": 0, "accuracy": 10})
        ties.add({"score": 70, "wave": 5, "avatars": 0,
                  "bunker": 0, "accuracy": 80})
        assert [e["wave"] for e in ties.entries] == [5, 5, 2]
        assert ties.entries[0]["accuracy"] == 80

        # A corrupt or partial file is ignored instead of crashing the game.
        path.write_text("{not json", encoding="utf-8")
        assert Leaderboard(path).entries == []
        path.write_text(json.dumps([
            {"score": "nope"},
            {"name": "Runner_12345", "score": 99999, "wave": 3,
             "avatars": 1, "bunker": 1.0, "accuracy": 1.0},
            {"score": 10, "wave": "4", "avatars": 2,
             "bunker": 12.5, "accuracy": 33.3},
        ]), encoding="utf-8")
        loaded = Leaderboard(path).entries
        assert len(loaded) == 1 and loaded[0]["wave"] == 4


def check_stats() -> None:
    """Hit accuracy and bunker destruction track exactly the requested rules."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        board = Leaderboard(Path(tmp) / "stats.json")
        game = Game(seed=12, leaderboard=board)
        game.start()
        assert game.shots_fired == 0 and game.shots_hit == 0
        assert game.avatars_killed == 0

        # A player bullet that kills an alien counts as a hit.
        target = game.alive_aliens()[0]
        game.player_bullets = [Bullet(target.x + 4, target.y + 4,
                                      -PLAYER_BULLET_SPEED, True)]
        game.shots_fired = 1
        game.check_collisions()
        assert not target.alive, "test bullet missed its alien"
        assert game.shots_hit == 1

        # A player bullet stopped by a bunker is a miss, not a hit.
        shield = game.shields[0]
        game.player_bullets = [Bullet(shield.x + shield.width // 2,
                                      shield.y - 4,
                                      -PLAYER_BULLET_SPEED, True)]
        game.shots_fired += 1
        game.check_collisions()
        assert game.shots_hit == 1, "bunker hit was counted as a target hit"
        assert game.run_stats()["accuracy"] == 50.0

        # Bunker destruction only counts cells wrecked by player bullets.
        before = game.bunker_cells_shot
        cell_row, cell_col = next(
            (r, c) for r in range(shield.rows) for c in range(shield.cols)
            if shield.cells[r][c])
        game.damage_shield(pygame.Rect(shield.x + cell_col * shield.cell,
                                       shield.y + cell_row * shield.cell,
                                       shield.cell, shield.cell),
                           -1, by_player=True)
        assert game.bunker_cells_shot > before
        stats = game.run_stats()
        assert 0.0 < stats["bunker"] <= 100.0

        # Every badge death is counted.
        if game.avatar_tiles:
            image, palette = game.avatar_tiles[0]
            badge = Drifter(image, palette, 300, 300, 0, 0)
            game.drifters = [badge]
            game.destroy_drifter(badge)
            assert game.avatars_killed == 1

        # The finished run is saved once, with the same numbers.
        game.game_over()
        game.record_score()
        assert len(board.entries) == 1
        saved = board.entries[0]
        assert saved["avatars"] == game.avatars_killed
        assert saved["accuracy"] == game.run_stats()["accuracy"]
        assert saved["bunker"] == game.run_stats()["bunker"]
        assert game.last_rank == 1
        game.record_score()
        assert len(board.entries) == 1, "run was recorded twice"

        # A game that ends during update records itself exactly once, and a
        # restart wipes the run statistics.
        auto_board = Leaderboard(Path(tmp) / "auto.json")
        auto = Game(seed=13, leaderboard=auto_board)
        auto.start()
        auto.score = 321
        auto.wave = 4
        auto.alive_aliens()[0].y = LANDING_Y
        auto.update(1 / 60)
        assert auto.state == "gameover"
        assert len(auto_board.entries) == 1, "automatic recording failed"
        assert auto_board.entries[0]["score"] == 321
        assert auto.last_rank == 1
        auto.start()
        assert (auto.shots_fired, auto.shots_hit, auto.avatars_killed) == (
            0, 0, 0)

        # Scores screen opens from any state, renders, scrolls and returns.
        view = Game(seed=2, leaderboard=auto_board)
        view.show_scores()
        assert view.state == "scores"
        view.draw(view.canvas)          # empty table must render
        view.scroll_scores(1)
        view.close_scores()
        assert view.state == "title"
        view.start()
        view.show_scores()
        view.scroll_scores(3)
        view.draw(view.canvas)          # populated table must render
        view.close_scores()
        assert view.state == "playing"


def check_music() -> None:
    """The soundtrack must be audible, deterministic per seed, and varied."""
    if metal is None:
        print("music: numpy unavailable, skipping synth checks")
        return

    short = 0.2
    first = metal.compose(seed=42, shorten=short)
    again = metal.compose(seed=42, shorten=short)
    other = metal.compose(seed=43, shorten=short)

    assert first == again, "same seed produced different music"
    assert first != other, "different seeds produced identical music"

    samples = array("h")
    samples.frombytes(first)
    assert len(samples) > 44100, "track is too short"
    assert len(samples) % 2 == 0, "stereo buffer has a half frame"
    peak = max(abs(min(samples)), abs(max(samples)))
    assert peak > 3000, f"track is silent (peak {peak})"

    # The new mix bus is stereo, so the two channels must not be identical.
    left = samples[0::2]
    right = samples[1::2]
    assert left != right, "track is dual-mono, expected stereo"
    stereo = np.frombuffer(first, dtype=np.int16).astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(stereo * stereo)))
    assert 0.02 < rms < 0.45, f"unexpected mastering level (rms {rms:.3f})"
    assert float(np.max(np.abs(stereo))) < 0.99, "track is clipping"

    # Every genre renders, is audible, and sounds different from the rest.
    tracks = {}
    for genre in metal.GENRES:
        data = metal.compose(seed=7, shorten=0.12, genre=genre)
        tracks[genre] = data
        samples = array("h")
        samples.frombytes(data)
        assert len(samples) > 22050, f"{genre} track is too short"
        peak = max(abs(min(samples)), abs(max(samples)))
        assert peak > 3000, f"{genre} track is silent (peak {peak})"
    assert len(set(tracks.values())) == len(tracks), "genres sound identical"

    for previous in metal.GENRES:
        for _ in range(12):
            assert metal.pick_genre(previous, random.Random(3)) != previous


def check_backgrounds(leaderboard: Leaderboard | None = None) -> None:
    """Each wave gets a different, dim pulp-paperback space painting."""
    first = make_pulp_background(random.Random(10))
    same = make_pulp_background(random.Random(10))
    other = make_pulp_background(random.Random(11))
    assert first.get_size() == (WIDTH, HEIGHT)
    assert (pygame.image.tobytes(first, "RGB")
            == pygame.image.tobytes(same, "RGB"))
    assert (pygame.image.tobytes(first, "RGB")
            != pygame.image.tobytes(other, "RGB"))
    alpha = first.get_alpha()
    assert alpha is not None and 0 < alpha < 160, f"backdrop alpha {alpha}"

    game = Game(seed=77, leaderboard=leaderboard)
    before_art = pygame.image.tobytes(game.pulp_bg, "RGB")
    before_genre = game.music_genre
    game.next_wave()
    assert pygame.image.tobytes(game.pulp_bg, "RGB") != before_art, (
        "backdrop did not change with the wave")
    if metal is not None:
        assert game.music_genre != before_genre, "wave reused the same genre"

    # The bag must use every genre before any of them comes back around.
    game = Game(seed=1, leaderboard=leaderboard)
    seen = [game.music_genre]
    for _ in range(len(metal.GENRES) - 1 if metal else 0):
        game.next_wave()
        seen.append(game.music_genre)
    if metal is not None:
        assert len(set(seen)) == len(metal.GENRES), (
            f"genre bag repeated early: {seen}")


def check_scaling(game: Game) -> None:
    """The canvas must letterbox into arbitrary window/fullscreen sizes."""
    for size in ((1920, 1080), (1280, 1024), (800, 600), (640, 480), (2560, 1440)):
        screen = pygame.display.set_mode(size)
        game.draw(game.canvas)
        game.present(screen)
        assert screen.get_size() == size
    pygame.display.set_mode((WIDTH, HEIGHT))


if __name__ == "__main__":
    raise SystemExit(main())
