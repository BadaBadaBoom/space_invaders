"""Game state, collisions, waves, scoring, and state transitions."""

from __future__ import annotations

import math
import random

import pygame

from assets import (
    load_avatar_tiles,
    load_font,
    make_pulp_background,
    make_tone,
)
from config import (
    ALIEN_BULLET_SPEED,
    ALIEN_H,
    ALIEN_W,
    COLS,
    DRIFTER_LIFE,
    DRIFTER_RESPAWN,
    DRIFTER_SPAWN_DELAY,
    DRIFTER_SPEED_MAX,
    DRIFTER_SPEED_MIN,
    DROP_DISTANCE,
    FIELD_TOP,
    FLOOR_Y,
    FORMATION_LEFT,
    FORMATION_TOP,
    GAP_X,
    GAP_Y,
    HEIGHT,
    LANDING_Y,
    LEADERBOARD_ROWS,
    LEFT_WALL,
    MAX_PLAYER_BULLETS,
    PLAYER_BULLET_SPEED,
    PLAYER_FIRE_COOLDOWN,
    PLAYER_SPEED,
    PLAYER_W,
    RIGHT_WALL,
    ROW_COLORS,
    ROW_POINTS,
    ROWS,
    SHIELD_W,
    SHIELD_Y,
    SHIELDS,
    WIDTH,
    clamp,
)
from deps import metal
from entities import Alien, Bullet, Drifter, Player, Shield
from leaderboard import Leaderboard
from render import RenderMixin


class Game(RenderMixin):
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
        # Pre-render the beat-the-record boom once per Game instance, never
        # on the victory frame. Without numpy (metal is None), without the
        # synth hook, or without an initialised mixer we simply go without.
        if (metal is not None and hasattr(metal, "explosion")
                and pygame.mixer.get_init()):
            try:
                boom = pygame.mixer.Sound(buffer=metal.explosion())
                boom.set_volume(0.85)
            except Exception:  # noqa: BLE001 - synth failure: keep going
                boom = None
            if boom is not None:
                self.sounds["record"] = boom
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
        # NASA story card for the game-over screen (set by main).
        self.story = None
        # Snapshot the board's best so this run can celebrate beating it once.
        self.record_to_beat = self.leaderboard.best
        self.record_beaten = False
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

    def alive_aliens(self) -> list[Alien]:
        return [a for a in self.aliens if a.alive]

    def formation_speed(self) -> float:
        alive = self.alive_aliens()
        frac = len(alive) / (COLS * ROWS)
        return (32 + 150 * (1.0 - frac)) * (1.0 + 0.16 * (self.wave - 1))

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
            d.age += dt
            if d.age >= DRIFTER_LIFE:
                self.expire_drifter(d)
                continue
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
                self.score += d.value
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
        # The caller pays the points at d.value (the badge's age-based value)
        # in check_drifter_collisions just before calling us, so this is the
        # first chance to celebrate.
        self.maybe_celebrate_record()
        try:
            self.drifters.remove(d)
        except ValueError:
            pass
        self.avatars_killed += 1
        self.explode(d.x + d.size / 2, d.y + d.size / 2, d.palette)
        self.drifter_timer = DRIFTER_RESPAWN

    def expire_drifter(self, d: Drifter) -> None:
        """A badge that lived its full life pops harmlessly, paying nothing."""
        try:
            self.drifters.remove(d)
        except ValueError:
            pass
        self.play("clank")
        x, y = d.x + d.size / 2, d.y + d.size / 2
        for _ in range(10):
            angle = self.rng.uniform(0.0, math.tau)
            speed = self.rng.uniform(30.0, 130.0)
            life = self.rng.uniform(0.2, 0.5)
            colour = self.rng.choice(d.palette)
            self.debris.append([x, y, math.cos(angle) * speed,
                                math.sin(angle) * speed, life, life,
                                colour, self.rng.choice((2, 3))])
        self.rings.append([x, y, 6.0, 0.34, self.rng.choice(d.palette)])
        self.flashes.append([x, y, 0.16, 0.16,
                             self.rng.choice(d.palette), 16.0])
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

    def maybe_celebrate_record(self) -> None:
        """One-time fireworks when player-earned points pass the board's best.

        Called only after alien kills and badge payouts, never from the wave
        bonus. Half the surviving formation (floor division, so at least one
        alien stays when two or more remain) pops in its row colour. These
        kills award no score and no shot statistics, and the record boom
        plays once for the whole celebration. An empty board never triggers.
        """
        if (self.record_to_beat <= 0 or self.record_beaten
                or self.score <= self.record_to_beat):
            return
        self.record_beaten = True
        self.play("record")
        alive = self.alive_aliens()
        for a in self.rng.sample(alive, len(alive) // 2):
            a.alive = False
            cx, cy = a.x + ALIEN_W / 2, a.y + ALIEN_H / 2
            palette = [ROW_COLORS[a.row]]
            for _ in range(16):
                angle = self.rng.uniform(0.0, math.tau)
                speed = self.rng.uniform(50.0, 330.0)
                life = self.rng.uniform(0.35, 0.85)
                colour = self.rng.choice(palette + [(255, 255, 255)])
                self.debris.append([cx, cy, math.cos(angle) * speed,
                                    math.sin(angle) * speed, life, life,
                                    colour, self.rng.choice((2, 3, 3, 4, 5))])
            for _ in range(2):
                self.rings.append([cx, cy, 6.0, 0.34,
                                   self.rng.choice(palette)])
            self.flashes.append([cx, cy, 0.10, 0.10, (255, 255, 255), 30.0])
            self.flashes.append([cx, cy, 0.22, 0.22,
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

        self.maybe_celebrate_record()

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
