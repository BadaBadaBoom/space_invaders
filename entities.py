"""Player, aliens, bullets, bunkers, floating avatar hazards, and the UFO."""

from __future__ import annotations

import random
from dataclasses import dataclass

import pygame

from config import (
    ALIEN_H,
    ALIEN_W,
    BOSS_H,
    BOSS_W,
    DRIFTER_LIFE,
    DRIFTER_POINTS,
    DRIFTER_POINTS_MIN,
    PLAYER_H,
    PLAYER_W,
    PLAYER_Y,
    POWERUP_FALL_SPEED,
    POWERUP_SIZE,
    SHIELD_BOTTOM_COLOR,
    SHIELD_CELL,
    SHIELD_COLS,
    SHIELD_ROWS,
    SHIELD_TOP_COLOR,
    UFO_H,
    UFO_W,
)


@dataclass
class Bullet:
    x: float
    y: float
    vy: float
    from_player: bool
    vx: float = 0.0
    prev_x: float = 0.0
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
        left = min(self.x, self.prev_x)
        top = min(self.y, self.prev_y)
        width = int(abs(self.x - self.prev_x)) + self.width + 1
        height = int(abs(self.y - self.prev_y)) + self.height + 1
        return pygame.Rect(int(left), int(top), width, height)

    def update(self, dt: float) -> None:
        self.prev_x = self.x
        self.prev_y = self.y
        self.x += self.vx * dt
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
    rapid: float = 0.0       # seconds of rapid fire left
    triple: float = 0.0      # seconds of triple shot left
    dash_time: float = 0.0   # seconds left in the current dash burst
    dash_cooldown: float = 0.0
    dash_dir: int = 0

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
    age: float = 0.0

    @property
    def size(self) -> int:
        return self.image.get_width()

    @property
    def fade(self) -> float:
        """Brightness from 1.0 at spawn linearly down to 0.0 at end of life."""
        return max(0.0, min(1.0, 1.0 - self.age / DRIFTER_LIFE))

    @property
    def value(self) -> int:
        """Points a bullet kill pays right now, falling with `fade`."""
        return round(DRIFTER_POINTS_MIN
                     + (DRIFTER_POINTS - DRIFTER_POINTS_MIN) * self.fade)

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), self.size, self.size)


@dataclass
class Ufo:
    """The mystery saucer that crosses the top of the arena."""

    x: float
    y: float
    vx: float
    points: int

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), UFO_W, UFO_H)


@dataclass
class PowerUp:
    """A capsule dropped by a dead alien; catch it with the ship."""

    kind: str
    x: float
    y: float
    vy: float = POWERUP_FALL_SPEED

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y),
                           POWERUP_SIZE, POWERUP_SIZE)


@dataclass
class Boss:
    """The wide machine that replaces the formation every fifth wave."""

    x: float
    y: float
    hp: int
    max_hp: int
    points: int

    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x), int(self.y), BOSS_W, BOSS_H)


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
        self.intact = self.alive_cells()   # cells in a pristine bunker

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

    def repair(self) -> int:
        """Rebuild the bunker; return how many cells were restored."""
        before = self.alive_cells()
        self.cells = [bytearray(b"\x01" * self.cols) for _ in range(self.rows)]
        self.carve_shape()
        return self.alive_cells() - before

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
