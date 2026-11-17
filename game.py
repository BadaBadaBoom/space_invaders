"""Game state, collisions, waves, scoring, and state transitions."""

from __future__ import annotations

import math
import random
import threading

import pygame

from assets import (
    load_avatar_tiles,
    load_font,
    make_pulp_background,
    make_tone,
    make_wail,
    make_wave_stinger,
)
from config import (
    ALIEN_BULLET_SPEED,
    ALIEN_H,
    ALIEN_W,
    BOSS_EVERY,
    BOSS_COLOR,
    BOSS_ENTRY_TIME,
    BOSS_FIRE_MAX,
    BOSS_FIRE_MIN,
    BOSS_H,
    BOSS_HP_BASE,
    BOSS_HP_STEP,
    BOSS_LIGHT,
    BOSS_RAGE_FIRE_SCALE,
    BOSS_RAGE_SWAY_SCALE,
    BOSS_SCORE_BASE,
    BOSS_SCORE_STEP,
    BOSS_SWAY,
    BOSS_SWAY_SPEED,
    BOSS_VOLLEY_SPEED,
    BOSS_W,
    BOSS_Y,
    COLS,
    COMBO_WINDOW,
    DASH_COOLDOWN,
    DASH_SPEED,
    DASH_TAP_WINDOW,
    DASH_TIME,
    DIVE_ACCEL,
    DIVE_FIRST_DELAY,
    DIVE_INTERVAL,
    DIVE_MAX_GROUP,
    DIVE_MAX_VY,
    DIVE_MIN_ALIVE,
    DIVE_SPEED_X,
    DIVE_START_VY,
    DIVE_TURN,
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
    GAMEOVER_ARTICLE_DELAY,
    GAP_X,
    GAP_Y,
    HEIGHT,
    HURT_FLASH_TIME,
    LANDING_Y,
    LEADERBOARD_ROWS,
    LEFT_WALL,
    MAX_PLAYER_BULLETS,
    MUZZLE_FLASH_TIME,
    PLAYER_BULLET_SPEED,
    PLAYER_COLOR,
    PLAYER_FIRE_COOLDOWN,
    PLAYER_H,
    PLAYER_SPEED,
    PLAYER_W,
    POPUP_LIFE,
    POWERUP_COLORS,
    POWERUP_DROP_CHANCE,
    POWERUP_KINDS,
    POWERUP_RAPID_SCALE,
    POWERUP_RAPID_TIME,
    POWERUP_SIZE,
    POWERUP_TRIPLE_TIME,
    POWERUP_WEIGHTS,
    RIGHT_WALL,
    ROW_COLORS,
    ROW_POINTS,
    ROWS,
    RECORD_BANNER_TIME,
    SHAKE_BOSS_RAGE,
    SHAKE_DRIFTER,
    SHAKE_LIFE_LOST,
    SHAKE_RECORD,
    SHAKE_UFO,
    SHIELD_BLINK_INTERVAL,
    SHIELD_BLINK_TIME,
    SHIELD_W,
    SHIELD_Y,
    SHIELDS,
    UFO_COLOR,
    UFO_FIRST_DELAY,
    UFO_H,
    UFO_LIGHT,
    UFO_POINTS,
    UFO_RESPAWN,
    UFO_SPEED_MAX,
    UFO_SPEED_MIN,
    UFO_W,
    UFO_Y,
    WAVE_INTRO_BOSS_TIME,
    WAVE_INTRO_TIME,
    WIDTH,
    clamp,
)
from deps import metal
from entities import (
    Alien,
    Boss,
    Bullet,
    Drifter,
    Player,
    PowerUp,
    Shield,
    Ufo,
)
from leaderboard import Leaderboard
from render import RenderMixin


class CoverPrefetcher:
    """Generate pulp-paperback covers on a worker thread, always one ahead.

    Covers are expensive (~250 ms each), so doing them on the main thread
    caused a visible stutter at every wave transition.  This prefetches them
    asynchronously using a dedicated RNG so the next wave's backdrop is
    usually already waiting when the transition happens.
    """

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.lock = threading.Lock()
        self.ready: pygame.Surface | None = None
        self.thread: threading.Thread | None = None
        self._start_next()

    def _start_next(self) -> None:
        """Launch a worker to render the next cover."""
        seed = self.rng.getrandbits(48)
        self.thread = threading.Thread(
            target=self._render, args=(seed,), daemon=True)
        self.thread.start()

    def _render(self, seed: int) -> None:
        """Render one cover and publish it under the lock."""
        try:
            surf = make_pulp_background(random.Random(seed))
        except Exception:  # noqa: BLE001 - a bad cover falls back to a gradient
            surf = make_pulp_background(random.Random(seed ^ 0xBADBEEF))
        with self.lock:
            self.ready = surf

    def take(self, block: bool = False,
             timeout: float | None = None) -> pygame.Surface | None:
        """Consume the ready cover, if any, and start the next one.

        Blocking waits for the current worker to finish; non-blocking simply
        returns whatever has landed since the last take.
        """
        if block and self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout)
        with self.lock:
            surf = self.ready
            self.ready = None
        if surf is not None:
            self._start_next()
        return surf


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
            "wave": make_wave_stinger(0.22),
            "clank": make_tone(330, 45, 0.10),
            "blast": make_tone(82, 320, 0.22),
            "power": make_tone(1046, 120, 0.14),
            "dash": make_tone(520, 55, 0.10),
            "dive": make_tone(1150, 90, 0.12),
            "wail": make_wail(1900, 620, 420, 0.24),
            "rage": make_wail(360, 110, 520, 0.26),
        }
        # Kill-chain chirps climb a little with every link in the chain.
        for tier in range(2, 9):
            self.sounds[f"combo{tier}"] = make_tone(
                440 + tier * 70, 42, 0.09)
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
        # Rendering caches.  Labels, invader sprites, composed backdrops, and
        # full-screen overlays are deterministic, so painting them once and
        # reusing the surfaces is much cheaper than rebuilding every frame.
        self._text_cache: dict[tuple, pygame.Surface] = {}
        self._alien_sprites: dict[tuple, pygame.Surface] = {}
        self._shade_cache: dict[int, pygame.Surface] = {}
        self._powerup_sprites: dict[str, pygame.Surface] = {}
        self._powerup_glows: dict[tuple[int, int, int], pygame.Surface] = {}
        self._help_icons: dict[str, pygame.Surface] = {}
        self._bullet_glow_surface: pygame.Surface | None = None
        self._bg_gradient: pygame.Surface | None = None
        self._bg_composites: dict[int, tuple[pygame.Surface, pygame.Surface]] = {}
        self._gameover_layer: pygame.Surface | None = None
        self._gameover_sig: tuple | None = None
        self._gameover_panel: pygame.Rect | None = None
        self._gameover_link: pygame.Rect | None = None
        self.hud_plate_rect: pygame.Rect | None = None
        self._scaled: pygame.Surface | None = None
        self.avatar_tiles = load_avatar_tiles()
        self.leaderboard = leaderboard if leaderboard is not None else Leaderboard()
        self.score_return_state = "title"
        self.score_scroll = 0
        # Two-step guard for erasing the board from the scores screen.
        self.clear_armed = False
        self.clear_hint_until = 0
        self.genre_bag: list[str] = []
        self.music_genre: str | None = None
        self.pulp_bg: pygame.Surface | None = None
        self._bg_prev: pygame.Surface | None = None
        self._bg_fade = 1.0
        self.cover_prefetcher: CoverPrefetcher | None = None
        self.stars = [
            (int(self.rng.uniform(0, WIDTH)), int(self.rng.uniform(0, HEIGHT)),
             self.rng.choice((1, 1, 1, 2)), self.rng.uniform(6, 26))
            for _ in range(90)
        ]
        self.invincible = False
        self.state = "title"  # title | playing | paused | gameover | scores | help
        self.help_return_state = "title"
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
        # Presentation-only feedback: screen shake and floating score numbers.
        self.shake_energy = 0.0
        self.shake_phase = 0.0
        self.popups: list[list] = []
        self.record_banner_time = 0.0
        self.record_banner_score = 0
        self.combo = 0
        self.combo_time = 0.0
        # Short flow beats: a wave card between rounds, a red hit vignette,
        # and the fade-in of the game-over screen.
        self.wave_intro_time = 0.0
        self.wave_intro_total = 0.0
        self.wave_intro_title = ""
        self.wave_intro_subtitle = ""
        self.wave_intro_boss = False
        self.wave_intro_bonus = 0
        self.hurt_flash = 0.0
        self.game_over_time = 0.0
        self.article_input_lock = 0.0
        # Music state mirrored from main for the pause screen.
        self.music_enabled = True
        self.music_muted = False
        self.music_volume_percent = 0
        # The mystery saucer, if one is crossing, and the countdown to the next.
        self.ufo: Ufo | None = None
        self.ufo_timer = self.rng.uniform(*UFO_FIRST_DELAY)
        # Capsules falling toward the ship.
        self.powerups: list[PowerUp] = []
        # Last tap per direction, for the double-tap dash.
        self.last_tap: dict[int, float] = {}
        # NASA story card for the game-over screen (set by main).
        self.story = None
        # Snapshot the board's best so this run can celebrate beating it once.
        self.record_to_beat = self.leaderboard.best
        self.record_beaten = False
        self.genre_bag = []
        self.music_genre = None
        self.next_music_genre = None
        # Covers are rendered on a worker thread.  spawn_wave() will block for
        # the first cover so pulp_bg is always valid; later waves use the
        # prefetched cover and lazily adopt it if it is not ready yet.
        self.cover_prefetcher = CoverPrefetcher(self.rng.getrandbits(64))
        self.cover_pending = False
        self.pulp_bg = None
        self._bg_prev = None
        self._bg_fade = 1.0
        self._bg_composites.clear()
        # A new run always gets a fresh game-over card.
        self._gameover_layer = None
        self._gameover_sig = None
        self._gameover_panel = None
        self._gameover_link = None
        self.spawn_wave()

    def spawn_wave(self) -> None:
        self.aliens: list[Alien] = []
        self.boss: Boss | None = None
        self.boss_phase = 0.0
        self.boss_flash = 0.0
        self.boss_volley = BOSS_FIRE_MAX
        self.boss_volley_index = 0
        self.boss_entry = 0.0
        self.boss_raged = False
        self.boss_ghost_hp = 0
        self.victory_timer = 0.0
        # Direct spawns (tests, resets) start hot; start()/next_wave() add the
        # intro card afterwards.
        self.wave_intro_time = 0.0
        self.wave_intro_bonus = 0
        self.combo = 0
        self.combo_time = 0.0
        if self.wave % BOSS_EVERY == 0:
            self.spawn_boss()
        else:
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
        self.dive_timer = self.rng.uniform(*DIVE_FIRST_DELAY)
        self.shields = self.make_shields()
        self.bunker_cells_total += sum(s.alive_cells() for s in self.shields)
        # Boss fights phase the bunkers out; ordinary waves keep them solid.
        self.shields_active = True
        self.shield_blink_left = 0.0
        self.shield_blink_wait = (self.rng.uniform(*SHIELD_BLINK_INTERVAL)
                                  if self.boss is not None else 0.0)
        self.fire_timer = max(0.45, 1.3 - 0.1 * (self.wave - 1))
        self.alien_anim = 0.0

        # New wave, new cover painting and a fresh genre of music. Keep one
        # genre composed ahead so the next track can be prepared in advance.
        self.music_genre = self.next_music_genre or self.choose_music_genre()
        self.next_music_genre = self.choose_music_genre()
        # Swap in the prefetched cover for this wave.  The first wave blocks
        # until a cover is ready; later waves take it if it has landed or mark
        # it pending so update_feedback adopts it lazily without ever pulling
        # in the *next* wave's cover early.
        if self.cover_prefetcher is not None:
            block = (self.wave == 1)
            new_bg = self.cover_prefetcher.take(block=block, timeout=2.0)
            if new_bg is not None:
                self.adopt_cover(new_bg)
                self.cover_pending = False
            else:
                self.cover_pending = True

    def spawn_boss(self) -> None:
        """Field the wave's boss: tougher and richer with every fifth wave."""
        tier = self.wave // BOSS_EVERY           # 1 on wave 5, 2 on wave 10
        hp = BOSS_HP_BASE + BOSS_HP_STEP * (tier - 1)
        self.boss = Boss(
            x=(WIDTH - BOSS_W) / 2,
            y=-BOSS_H,
            hp=hp,
            max_hp=hp,
            points=BOSS_SCORE_BASE + BOSS_SCORE_STEP * (tier - 1),
        )
        self.boss_entry = BOSS_ENTRY_TIME
        self.boss_raged = False
        self.boss_ghost_hp = hp
        self.fire_timer = BOSS_FIRE_MAX

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
        self.begin_wave_intro(cleared=False)

    def begin_wave_intro(self, cleared: bool = False) -> None:
        """Put a short card in front of the new wave and freeze the fight."""
        boss = self.wave % BOSS_EVERY == 0
        self.wave_intro_total = (WAVE_INTRO_BOSS_TIME if boss
                                 else WAVE_INTRO_TIME)
        self.wave_intro_time = self.wave_intro_total
        self.wave_intro_title = f"WAVE {self.wave}"
        self.wave_intro_boss = boss
        if boss:
            self.wave_intro_subtitle = "CAPITAL SHIP INBOUND"
        elif cleared:
            self.wave_intro_subtitle = "WAVE CLEAR   +100"
        else:
            self.wave_intro_subtitle = "DEFEND THE LINE"
        self.wave_intro_bonus = 100 if cleared else 0

    def alive_aliens(self) -> list[Alien]:
        return [a for a in self.aliens if a.alive]

    def formation_aliens(self) -> list[Alien]:
        return [a for a in self.aliens if a.alive and not a.diving]

    def formation_speed(self) -> float:
        alive = sum(1 for a in self.aliens if a.alive)
        frac = alive / (COLS * ROWS)
        return (32 + 150 * (1.0 - frac)) * (1.0 + 0.16 * (self.wave - 1))

    def update(self, dt: float, move: int = 0, fire: bool = False) -> None:
        """Advance one frame. `move` is -1/0/1, `fire` is edge-triggered."""
        if self.state != "playing":
            return
        if self.record_banner_time > 0:
            # Hold the fight while the record marquee rolls, so the
            # celebration can never get the player killed.
            return
        if self.wave_intro_time > 0:
            # The wave card is the player's breather between fights.
            return
        dt = min(dt, 1 / 30)  # keep physics sane after a window stall

        self.update_player(dt, move, fire)
        self.update_bullets(dt)
        self.update_aliens(dt)
        self.update_divers(dt)
        self.update_boss(dt)
        self.update_shields(dt)
        self.update_alien_fire(dt)
        self.update_drifters(dt)
        self.update_ufo(dt)
        self.update_powerups(dt)
        self.check_collisions()

        if self.victory_timer > 0:
            # Let the boss explosion play before the next wave rolls in.
            self.victory_timer = max(0.0, self.victory_timer - dt)
        elif not self.alive_aliens() and self.boss is None:
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
        p.rapid = max(0.0, p.rapid - dt)
        p.triple = max(0.0, p.triple - dt)
        p.dash_cooldown = max(0.0, p.dash_cooldown - dt)
        p.muzzle = max(0.0, p.muzzle - dt)

        if p.dash_time > 0:
            # The burst overrides held movement for its short duration.
            p.dash_time = max(0.0, p.dash_time - dt)
            p.x = clamp(p.x + p.dash_dir * DASH_SPEED * dt, LEFT_WALL,
                        RIGHT_WALL - PLAYER_W)
            p.move_dir = p.dash_dir
        elif move:
            p.x = clamp(p.x + move * PLAYER_SPEED * dt, LEFT_WALL,
                        RIGHT_WALL - PLAYER_W)
            p.move_dir = move
        else:
            p.move_dir = 0

        limit = MAX_PLAYER_BULLETS * (3 if p.triple > 0 else 1)
        if fire and p.cooldown <= 0 and len(self.player_bullets) < limit:
            p.cooldown = PLAYER_FIRE_COOLDOWN * (
                POWERUP_RAPID_SCALE if p.rapid > 0 else 1.0)
            spread = (-10, 0, 10) if p.triple > 0 else (0,)
            for offset in spread:
                self.player_bullets.append(Bullet(
                    x=p.center_x + offset - 2, y=p.y - 14,
                    vy=-PLAYER_BULLET_SPEED, from_player=True,
                ))
            self.shots_fired += len(spread)
            p.muzzle = MUZZLE_FLASH_TIME
            self.play("shoot")

    def dash(self, direction: int) -> bool:
        """Start a burst; False while cooling down or outside active play."""
        player = self.player
        if (self.state != "playing" or direction == 0
                or player.dash_cooldown > 0 or player.dash_time > 0):
            return False
        player.dash_time = DASH_TIME
        player.dash_cooldown = DASH_COOLDOWN
        player.dash_dir = direction
        self.spawn_sparks(player.x + PLAYER_W / 2, player.y + PLAYER_H / 2)
        self.play("dash")
        return True

    def tap(self, direction: int, now: float | None = None) -> bool:
        """Note a fresh tap; the second one inside the window starts a dash."""
        stamp = (pygame.time.get_ticks() / 1000.0 if now is None else now)
        previous = self.last_tap.get(direction, -1e9)
        self.last_tap[direction] = stamp
        if stamp - previous <= DASH_TAP_WINDOW:
            return self.dash(direction)
        return False

    def update_bullets(self, dt: float) -> None:
        for b in self.player_bullets + self.alien_bullets:
            b.update(dt)
        self.player_bullets = [
            b for b in self.player_bullets
            if FIELD_TOP <= b.y < HEIGHT and -40 <= b.x <= WIDTH + 40
        ]
        self.alien_bullets = [
            b for b in self.alien_bullets
            if b.y + b.height <= FLOOR_Y and -40 <= b.x <= WIDTH + 40
        ]

    def update_aliens(self, dt: float) -> None:
        alive = self.formation_aliens()
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

    def update_divers(self, dt: float) -> None:
        """Fly any dive-bombers, or count down to the next group."""
        divers = [a for a in self.aliens if a.alive and a.diving]
        if not divers:
            # Wait for the boss entrance to finish before summoning minions.
            if self.boss is not None and self.boss_entry > 0:
                return
            self.dive_timer -= dt
            if self.dive_timer <= 0:
                if self.boss is not None:
                    self.start_boss_dive()
                    self.dive_timer = self.rng.uniform(*DIVE_INTERVAL)
                elif len(self.formation_aliens()) > DIVE_MIN_ALIVE:
                    self.start_dive()
                    spread = max(0.55, 1.0 - 0.04 * (self.wave - 1))
                    self.dive_timer = self.rng.uniform(*DIVE_INTERVAL) * spread
            return

        player = self.player
        for alien in divers:
            desired = clamp((player.center_x - (alien.x + ALIEN_W / 2)) * 2.2,
                            -DIVE_SPEED_X, DIVE_SPEED_X)
            alien.vx += (desired - alien.vx) * min(1.0, dt * DIVE_TURN)
            alien.vy = min(DIVE_MAX_VY, alien.vy + DIVE_ACCEL * dt)
            alien.x = clamp(alien.x + alien.vx * dt, LEFT_WALL,
                            RIGHT_WALL - ALIEN_W)
            alien.y += alien.vy * dt
            self.spawn_dive_ember(alien)
            if alien.y > FLOOR_Y:
                # It missed and left the arena.
                alien.alive = False
                self.spawn_sparks(alien.x + ALIEN_W / 2, FLOOR_Y - 4)
                continue
            if alien.rect().colliderect(player.rect()):
                alien.alive = False
                self.spawn_debris(alien)
                if player.invulnerable <= 0 and player.dash_time <= 0:
                    self.player_hit()

    def spawn_dive_ember(self, alien: Alien) -> None:
        """A couple of sparks peeling off the dive-bomber's burning trail."""
        if self.rng.random() > 0.85:
            return
        for _ in range(2):
            self.debris.append([
                alien.x + ALIEN_W / 2 + self.rng.uniform(-4, 4),
                alien.y + ALIEN_H / 2 + self.rng.uniform(-4, 4),
                -alien.vx * 0.25 + self.rng.uniform(-30.0, 30.0),
                -alien.vy * 0.25 + self.rng.uniform(-30.0, 30.0),
                0.30, 0.30,
                self.rng.choice(((255, 210, 120), (255, 140, 60),
                                 (255, 90, 40))),
                self.rng.choice((2, 3)),
            ])

    def dive_group_size(self) -> int:
        """How many kamikazes launch together this wave, chosen uniformly.

        Wave 1 sends one; wave 2 has an equal chance of one or two, wave 3
        adds a third option, and so on up to DIVE_MAX_GROUP from wave 5 on.
        """
        upper = min(DIVE_MAX_GROUP, max(1, self.wave))
        return self.rng.randint(1, upper)

    def start_dive(self) -> None:
        """Peel a group of formation aliens out into a simultaneous dive."""
        candidates = self.formation_aliens()
        if not candidates:
            return
        group = min(self.dive_group_size(), len(candidates))
        for alien in self.rng.sample(candidates, group):
            alien.diving = True
            alien.vx = self.rng.choice((-1, 1)) * self.rng.uniform(40.0, 110.0)
            alien.vy = DIVE_START_VY
        self.play("dive")

    def start_boss_dive(self) -> None:
        """Summon one to five kamikazes at random points around the boss."""
        count = self.rng.randint(1, DIVE_MAX_GROUP)
        for _ in range(count):
            row = self.rng.randrange(ROWS)
            x = self.rng.uniform(LEFT_WALL + 8, RIGHT_WALL - ALIEN_W - 8)
            # Keep the portals below the hull so a summoned diver is visible
            # from the moment it appears instead of hiding behind the boss.
            y = self.rng.uniform(BOSS_Y + BOSS_H + 10, SHIELD_Y - 90)
            alien = Alien(
                col=self.rng.randrange(COLS),
                row=row,
                x=x,
                y=y,
                diving=True,
                vx=self.rng.choice((-1, 1)) * self.rng.uniform(40.0, 110.0),
                vy=DIVE_START_VY,
            )
            self.aliens.append(alien)
            cx, cy = x + ALIEN_W / 2, y + ALIEN_H / 2
            colour = ROW_COLORS[row % len(ROW_COLORS)]
            # A brief arrival ring and flash telegraph the portal.
            self.rings.append([cx, cy, 6.0, 0.34, colour])
            self.flashes.append([cx, cy, 0.12, 0.12, (255, 255, 255), 18.0])
        self.play("dive")

    def update_boss(self, dt: float) -> None:
        """Hover, sway and volley. The boss never joins a formation march."""
        boss = self.boss
        if boss is None:
            return
        if self.boss_ghost_hp > boss.hp:
            self.boss_ghost_hp = max(
                boss.hp, self.boss_ghost_hp - boss.max_hp * 0.8 * dt)
        self.boss_phase += dt
        sway_speed = BOSS_SWAY_SPEED * (
            BOSS_RAGE_SWAY_SCALE if self.boss_raged else 1.0)
        sway = math.sin(self.boss_phase * sway_speed) * BOSS_SWAY
        boss.x = clamp((WIDTH - BOSS_W) / 2 + sway,
                       LEFT_WALL + 6, RIGHT_WALL - BOSS_W - 6)
        self.boss_flash = max(0.0, self.boss_flash - dt)
        if self.boss_entry > 0:
            # Slide down from above the arena before the fight begins.
            self.boss_entry = max(0.0, self.boss_entry - dt)
            progress = 1.0 - self.boss_entry / BOSS_ENTRY_TIME
            ease = 1.0 - (1.0 - progress) ** 3
            boss.y = -BOSS_H + (BOSS_Y + BOSS_H) * ease
            if self.boss_entry == 0:
                boss.y = BOSS_Y
            return
        self.boss_volley -= dt
        if self.boss_volley <= 0:
            self.fire_boss_volley()
            interval = self.rng.uniform(BOSS_FIRE_MIN, BOSS_FIRE_MAX)
            if self.boss_raged:
                interval *= BOSS_RAGE_FIRE_SCALE
            self.boss_volley = interval

    def update_shields(self, dt: float) -> None:
        """Phase boss-fight bunkers out and back without repairing them."""
        if self.boss is None:
            self.shields_active = True
            self.shield_blink_left = 0.0
            return
        if self.boss_entry > 0:
            # Let the boss arrive behind full cover.
            return
        if self.shields_active:
            self.shield_blink_wait -= dt
            if self.shield_blink_wait <= 0:
                self.shields_active = False
                self.shield_blink_left = SHIELD_BLINK_TIME
        else:
            self.shield_blink_left -= dt
            if self.shield_blink_left <= 0:
                self.shields_active = True
                self.shield_blink_wait = self.rng.uniform(
                    *SHIELD_BLINK_INTERVAL)

    def fire_boss_volley(self) -> None:
        """Cycle a hull-wide fan, an aimed triple, and a scattered rain."""
        boss = self.boss
        if boss is None:
            return
        pattern = self.boss_volley_index % 3
        self.boss_volley_index += 1
        cx = boss.x + BOSS_W / 2
        bottom = boss.y + BOSS_H
        if pattern == 0:
            # Fan: one shot from each pod position across the hull.
            for i in range(5):
                x = boss.x + 16 + i * (BOSS_W - 32) / 4
                self.alien_bullets.append(Bullet(
                    x=x - 3, y=bottom, vy=ALIEN_BULLET_SPEED,
                    from_player=False))
        elif pattern == 1:
            # Aimed: a tight triple that converges on the ship.
            dx = self.player.center_x - cx
            dy = max(40.0, self.player.y - bottom)
            length = math.hypot(dx, dy)
            speed = BOSS_VOLLEY_SPEED
            vx = clamp(speed * dx / length, -180.0, 180.0)
            vy = max(80.0, speed * dy / length)
            for offset in (-14, 0, 14):
                self.alien_bullets.append(Bullet(
                    x=cx + offset - 3, y=bottom, vy=vy,
                    from_player=False, vx=vx))
        else:
            # Rain: scattered shots with mixed fall speeds.
            for _ in range(6):
                self.alien_bullets.append(Bullet(
                    x=self.rng.uniform(LEFT_WALL, RIGHT_WALL) - 3,
                    y=bottom,
                    vy=self.rng.uniform(ALIEN_BULLET_SPEED * 0.8,
                                        ALIEN_BULLET_SPEED * 1.35),
                    from_player=False))

    def damage_boss(self) -> None:
        boss = self.boss
        if boss is None:
            return
        boss.hp -= 1
        self.shots_hit += 1
        self.boss_flash = 0.09
        self.play("hit")
        self.spawn_sparks(
            boss.x + BOSS_W / 2
            + self.rng.uniform(-BOSS_W * 0.35, BOSS_W * 0.35),
            boss.y + BOSS_H * 0.7)
        if (not self.boss_raged
                and boss.hp * 2 <= boss.max_hp):
            self.trigger_boss_rage()
        if boss.hp <= 0:
            self.kill_boss()

    def trigger_boss_rage(self) -> None:
        """Crossing half health opens the boss's overdrive phase."""
        boss = self.boss
        if boss is None or self.boss_raged:
            return
        self.boss_raged = True
        self.add_shake(SHAKE_BOSS_RAGE)
        self.play("rage")
        cx, cy = boss.x + BOSS_W / 2, boss.y + BOSS_H / 2
        self.rings.append([cx, cy, 18.0, 0.5, (255, 110, 140)])
        self.flashes.append([cx, cy, 0.28, 0.28, (255, 190, 210), 42.0])
        for offset in (-BOSS_W * 0.32, 0.0, BOSS_W * 0.32):
            self.spawn_sparks(cx + offset, boss.y + BOSS_H * 0.6)
        self.spawn_popup(cx, boss.y - 20, "OVERDRIVE", (255, 120, 150))
        self.boss_volley = 0.25

    def kill_boss(self) -> None:
        boss = self.boss
        if boss is None:
            return
        self.boss = None
        self.boss_flash = 0.0
        self.alien_bullets.clear()
        # The boss's summoned kamikazes die with it, and the bunkers return
        # for the victory beat whether they were phased out or not.
        for alien in self.aliens:
            if alien.alive:
                alien.alive = False
                self.spawn_sparks(alien.x + ALIEN_W / 2,
                                  alien.y + ALIEN_H / 2)
        self.shields_active = True
        self.shield_blink_left = 0.0
        self.score += boss.points
        cx, cy = boss.x + BOSS_W / 2, boss.y + BOSS_H / 2
        self.spawn_popup(cx, boss.y, f"+{boss.points}", BOSS_LIGHT)
        palette = [BOSS_COLOR, BOSS_LIGHT, (255, 255, 255)]
        for offset in (-BOSS_W * 0.30, 0.0, BOSS_W * 0.30):
            self.explode(cx + offset, cy + self.rng.uniform(-10, 10), palette)
        self.play("boom")
        self.victory_timer = 1.6
        self.spawn_powerup(self.roll_powerup_kind(), cx, cy)
        self.maybe_celebrate_record()

    def update_alien_fire(self, dt: float) -> None:
        self.fire_timer -= dt
        if self.fire_timer > 0 or len(self.alien_bullets) >= 4:
            return
        self.fire_timer = max(0.28, self.rng.uniform(0.55, 1.15) - 0.05 * self.wave)

        # Only the front-most alien of a column can shoot.
        columns: dict[int, Alien] = {}
        for a in self.formation_aliens():
            current = columns.get(a.col)
            if current is None or a.y > current.y:
                columns[a.col] = a
        if not columns:
            return      # boss waves have no formation to shoot from
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
        # Wave 1 allows one badge, wave 2 two, wave 3 three, and so on; a boss
        # wave keeps just one so the fight stays readable.
        target = 1 if self.boss is not None else max(1, self.wave)
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

    def update_ufo(self, dt: float) -> None:
        """Count down to the next saucer, or fly the current one across."""
        ufo = self.ufo
        if ufo is None:
            self.ufo_timer -= dt
            if self.ufo_timer <= 0:
                self.spawn_ufo()
            return
        ufo.x += ufo.vx * dt
        if ufo.x + UFO_W < -8 or ufo.x > WIDTH + 8:
            # It got away: another one is due about UFO_RESPAWN from now.
            self.ufo = None
            self.ufo_timer = UFO_RESPAWN + self.rng.uniform(-3.0, 3.0)

    def spawn_ufo(self) -> None:
        direction = self.rng.choice((-1, 1))
        speed = self.rng.uniform(UFO_SPEED_MIN, UFO_SPEED_MAX)
        self.ufo = Ufo(
            x=-UFO_W if direction > 0 else WIDTH,
            y=UFO_Y,
            vx=speed * direction,
            points=self.rng.choice(UFO_POINTS),
        )

    def hit_ufo(self) -> None:
        """A player bullet brought the saucer down: pay the table and move on."""
        ufo = self.ufo
        if ufo is None:
            return
        self.ufo = None
        self.ufo_timer = UFO_RESPAWN + self.rng.uniform(-3.0, 3.0)
        self.shots_hit += 1
        self.score += ufo.points
        self.add_shake(SHAKE_UFO)
        combo = self.register_kill()
        label = f"+{ufo.points}" + (f"  ×{combo}" if combo > 1 else "")
        self.spawn_popup(ufo.x + UFO_W / 2, ufo.y, label, UFO_LIGHT)
        self.explode(ufo.x + UFO_W / 2, ufo.y + UFO_H / 2,
                     [UFO_COLOR, UFO_LIGHT, (255, 255, 255)], sound="wail")
        self.maybe_celebrate_record()

    def maybe_drop_powerup(self, x: float, y: float) -> None:
        """A small share of alien kills leaves a capsule behind."""
        if self.rng.random() >= POWERUP_DROP_CHANCE:
            return
        self.spawn_powerup(self.roll_powerup_kind(), x, y)

    def roll_powerup_kind(self) -> str:
        """Pick a capsule kind, leaving repair out while bunkers are whole."""
        kinds = list(POWERUP_KINDS)
        weights = list(POWERUP_WEIGHTS)
        if all(shield.alive_cells() >= shield.intact for shield in self.shields):
            weights = [weight if kind != "repair" else 0.0
                       for kind, weight in zip(kinds, weights)]
        return self.rng.choices(kinds, weights=weights, k=1)[0]

    def spawn_powerup(self, kind: str, x: float, y: float) -> None:
        self.powerups.append(PowerUp(
            kind=kind,
            x=clamp(x - POWERUP_SIZE / 2, LEFT_WALL,
                    RIGHT_WALL - POWERUP_SIZE),
            y=y,
        ))

    def update_powerups(self, dt: float) -> None:
        """Fall the capsules and collect the ones the ship touches."""
        keep = []
        player_rect = self.player.rect()
        for powerup in self.powerups:
            powerup.y += powerup.vy * dt
            if powerup.rect().colliderect(player_rect):
                self.apply_powerup(powerup)
                continue
            if powerup.y <= FLOOR_Y:
                keep.append(powerup)
        self.powerups = keep

    def apply_powerup(self, powerup: PowerUp) -> None:
        kind = powerup.kind
        colour = POWERUP_COLORS.get(kind, (255, 255, 255))
        if kind == "rapid":
            self.player.rapid = POWERUP_RAPID_TIME
            text = "RAPID FIRE"
        elif kind == "triple":
            self.player.triple = POWERUP_TRIPLE_TIME
            text = "TRIPLE SHOT"
        else:
            restored = sum(shield.repair() for shield in self.shields)
            # Count the rebuilt cells as deployed, so the run's bunker
            # percentage stays honest.
            self.bunker_cells_total += restored
            text = "BUNKERS REPAIRED" if restored else "BUNKERS INTACT"
        x, y = powerup.x + POWERUP_SIZE / 2, powerup.y
        self.play("power")
        self.spawn_popup(x, y - 5, text, colour)
        self.flashes.append([x, y + POWERUP_SIZE / 2, 0.18, 0.18,
                             colour, 22.0])

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
                combo = self.register_kill()
                label = f"+{d.value}" + (f"  ×{combo}" if combo > 1 else "")
                self.spawn_popup(d.x + d.size / 2, d.y, label,
                                 (d.palette or [(255, 255, 255)])[0])
            else:
                keep.append(b)
        self.player_bullets = keep

        # Enemy fire is swallowed, but the badge keeps floating.
        self.alien_bullets = [
            b for b in self.alien_bullets
            if not rect.colliderect(b.sweep_rect())
        ]

        # Aliens are solid to the badge: it ricochets off the group it hit
        # without harming them.  Union the touched boxes without collecting
        # them in a list first.
        rect = d.rect()
        group = None
        for a in self.aliens:
            if a.alive:
                box = a.rect()
                if rect.colliderect(box):
                    group = box if group is None else group.union(box)
        if group is not None:
            self._bounce_drifter(d, group)

        # Bunkers take a bite and deflect the badge.
        if self.shields_active:
            rect = d.rect()
            for s in self.shields:
                bounds = s.bounds()
                if bounds.colliderect(rect) and s.erase_rect(rect):
                    self._bounce_drifter(d, bounds)
                    rect = d.rect()

        # Hitting the player kills the player and the badge. Do this last:
        # player_hit() clears all bullets.
        if d.rect().colliderect(self.player.rect()):
            killed = True
            if (self.player.invulnerable <= 0
                    and self.player.dash_time <= 0):
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
        self.add_shake(SHAKE_DRIFTER)
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
                palette: list[tuple[int, int, int]],
                sound: str = "blast") -> None:
        self.play(sound)
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
        self.record_banner_time = RECORD_BANNER_TIME
        self.record_banner_score = self.score
        self.add_shake(SHAKE_RECORD)
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
        # Player bullets: bunkers first, then the saucer, then aliens.
        surviving = []
        for b in self.player_bullets:
            path = b.sweep_rect()
            if self.damage_shield(path, b.vy, by_player=True):
                continue
            shot_powerup = next(
                (p for p in self.powerups if path.colliderect(p.rect())),
                None)
            if shot_powerup is not None:
                self.powerups = [p for p in self.powerups
                                 if p is not shot_powerup]
                self.apply_powerup(shot_powerup)
                continue
            if (self.boss is not None and self.boss_entry <= 0
                    and path.colliderect(self.boss.rect())):
                self.damage_boss()
                continue
            if self.ufo is not None and path.colliderect(self.ufo.rect()):
                self.hit_ufo()
                continue
            hit = None
            # Prefer the topmost invader the shot touches, as the old sorted
            # scan did, without building and sorting a list for every bullet.
            for a in self.aliens:
                if a.alive and path.colliderect(a.rect()):
                    if hit is None or a.y < hit.y:
                        hit = a
            if hit is None:
                surviving.append(b)
            else:
                hit.alive = False
                self.shots_hit += 1
                points = ROW_POINTS[hit.row]
                self.score += points
                self.play("hit")
                self.spawn_debris(hit)
                combo = self.register_kill()
                label = f"+{points}" + (f"  ×{combo}" if combo > 1 else "")
                self.spawn_popup(hit.x + ALIEN_W / 2, hit.y,
                                 label,
                                 ROW_COLORS[hit.row % len(ROW_COLORS)])
                self.maybe_drop_powerup(hit.x + ALIEN_W / 2, hit.y)
        self.player_bullets = surviving

        # Alien bullets: bunkers first, then the player.
        player_rect = self.player.rect()
        remaining = []
        for b in self.alien_bullets:
            path = b.sweep_rect()
            if self.damage_shield(path, b.vy, by_player=False):
                continue
            if (self.player.invulnerable <= 0
                    and self.player.dash_time <= 0
                    and path.colliderect(player_rect)):
                self.play("boom")
                self.player_hit()
            else:
                remaining.append(b)
        self.alien_bullets = remaining

        # Aliens marching down through a bunker chew a hole in it.  The
        # shields' bounds stay fixed for the whole pass, so build them once
        # instead of recreating four Rects for every alien.  A phased-out
        # bunker is not there to be chewed.
        shield_bounds = ([(s, s.bounds()) for s in self.shields]
                         if self.shields_active else [])
        for a in self.aliens:
            if not a.alive:
                continue
            area = a.rect()
            for s, bounds in shield_bounds:
                if bounds.colliderect(area):
                    s.erase_rect(area)

        self.maybe_celebrate_record()

    def damage_shield(self, rect: pygame.Rect, vy: float,
                      by_player: bool = False) -> bool:
        if not self.shields_active:
            return False
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

    def register_kill(self) -> int:
        """Extend the kill chain and return its new length."""
        self.combo = (self.combo + 1 if self.combo_time > 0 else 1)
        self.combo_time = COMBO_WINDOW
        if self.combo >= 2:
            self.play(f"combo{min(8, self.combo)}")
        return self.combo

    def spawn_popup(self, x: float, y: float, text: str,
                    colour: tuple[int, int, int]) -> None:
        """A rising score number that fades out where points were earned."""
        self.popups.append([x, y, text, colour, POPUP_LIFE, POPUP_LIFE])

    def spawn_sparks(self, x: float, y: float) -> None:
        for _ in range(4):
            angle = self.rng.uniform(0, math.tau)
            speed = self.rng.uniform(30, 110)
            life = 0.25
            self.debris.append([x, y, math.cos(angle) * speed,
                                math.sin(angle) * speed, life, life,
                                (140, 255, 190), 2])

    def lowest_alien_y(self) -> float:
        lowest = 0.0
        for a in self.aliens:
            if a.alive and not a.diving and a.y > lowest:
                lowest = a.y
        return lowest

    def player_hit(self) -> None:
        if self.invincible:
            return
        # Blow up where the ship actually was before it respawns at centre.
        self.spawn_ship_burst(self.player.center_x, self.player.y + PLAYER_H / 2)
        self.combo = 0
        self.combo_time = 0.0
        self.lives -= 1
        self.add_shake(SHAKE_LIFE_LOST)
        self.alien_bullets.clear()
        self.player_bullets.clear()
        self.player.x = WIDTH / 2 - PLAYER_W / 2
        self.player.dash_time = 0.0
        self.player.invulnerable = 1.6
        if self.lives <= 0:
            self.game_over()

    def spawn_ship_burst(self, x: float, y: float) -> None:
        """A compact green-white explosion plus the red edge pulse."""
        self.hurt_flash = HURT_FLASH_TIME
        palette = (PLAYER_COLOR, (220, 255, 235), (255, 190, 120))
        for _ in range(18):
            angle = self.rng.uniform(0.0, math.tau)
            speed = self.rng.uniform(40.0, 230.0)
            life = self.rng.uniform(0.28, 0.65)
            self.debris.append([
                x, y, math.cos(angle) * speed, math.sin(angle) * speed,
                life, life, self.rng.choice(palette),
                self.rng.choice((2, 3, 3, 4)),
            ])
        self.rings.append([x, y, 7.0, 0.36, PLAYER_COLOR])
        self.flashes.append([x, y, 0.12, 0.12, (255, 255, 255), 26.0])
        self.flashes.append([x, y, 0.24, 0.24, PLAYER_COLOR, 18.0])

    def game_over(self) -> None:
        if self.state == "playing" and not self.invincible:
            self.state = "gameover"
            self.pending_record = True
            self.game_over_time = 0.0
            self.article_input_lock = GAMEOVER_ARTICLE_DELAY
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
        self.begin_wave_intro(cleared=True)

    def await_cover(self, timeout: float = 2.0) -> None:
        """Block until the prefetched cover for the current wave is ready.

        This is only meant for tests; during play the cover swaps in lazily
        via update_feedback so wave transitions never hitch.
        """
        if self.cover_prefetcher is None or not self.cover_pending:
            return
        surf = self.cover_prefetcher.take(block=True, timeout=timeout)
        if surf is not None:
            self.adopt_cover(surf)
            self.cover_pending = False

    def toggle_pause(self) -> None:
        if self.state == "playing":
            self.state = "paused"
        elif self.state == "paused":
            self.state = "playing"

    def toggle_help(self) -> None:
        """Show the controls/power-up card, or return to where it opened."""
        if self.state == "help":
            self.close_help()
        elif self.state in ("title", "playing", "paused", "gameover",
                            "scores"):
            self.help_return_state = self.state
            self.clear_armed = False
            self.state = "help"

    def toggle_invincible(self) -> bool:
        """Toggle the testing shield; it persists across restarts."""
        self.invincible = not self.invincible
        return self.invincible

    def close_help(self) -> None:
        if self.state == "help":
            self.state = self.help_return_state

    def show_scores(self) -> None:
        if self.state in ("title", "paused", "playing", "gameover"):
            self.score_return_state = self.state
            self.score_scroll = 0
            # Land the table on this run's row instead of always showing the
            # top, so a lower-ranked entry is actually visible when opened.
            if self.state == "gameover" and self.last_rank is not None:
                highest = max(0, len(self.leaderboard.entries)
                              - LEADERBOARD_ROWS)
                self.score_scroll = int(clamp(
                    self.last_rank - 1 - LEADERBOARD_ROWS // 2,
                    0, highest))
            self.clear_armed = False
            self.state = "scores"

    def close_scores(self) -> None:
        if self.state == "scores":
            self.clear_armed = False
            self.state = self.score_return_state

    def clear_scores(self) -> bool:
        """Erase the whole board. The first call arms, the second commits."""
        now = pygame.time.get_ticks()
        if self.clear_armed and now < self.clear_hint_until:
            self.clear_armed = False
            self.clear_hint_until = 0
            self.leaderboard.clear()
            self.last_rank = None
            self.score_scroll = 0
            return True
        self.clear_armed = True
        self.clear_hint_until = now + 4000
        return False

    def scroll_scores(self, delta: int) -> None:
        if self.state != "scores":
            return
        highest = max(0, len(self.leaderboard.entries) - LEADERBOARD_ROWS)
        self.score_scroll = int(clamp(self.score_scroll + delta, 0, highest))

    def play(self, name: str) -> None:
        sound = self.sounds.get(name)
        if sound:
            sound.play()

    def _bezel(self, size: tuple[int, int]) -> pygame.Surface:
        """A starfield panel that fills the letterbox around the 4:3 canvas."""
        if getattr(self, "_bezel_key", None) == size:
            return self._bezel_surface
        sw, sh = size
        surf = pygame.Surface(size)
        top, bottom = (6, 8, 20), (20, 13, 36)
        for y in range(0, sh, 6):
            t = y / max(1, sh - 1)
            colour = tuple(int(top[i] + (bottom[i] - top[i]) * t)
                           for i in range(3))
            surf.fill(colour, (0, y, sw, 6))
        # A local RNG keeps the backdrop out of the gameplay seed.
        rng = random.Random(sw * 7919 + sh * 104729)
        for _ in range(max(80, sw * sh // 14000)):
            x, y = rng.randrange(sw), rng.randrange(sh)
            value = rng.randint(28, 82)
            surf.fill((value, value, min(255, value + 24)), (x, y, 1, 1))
        self._bezel_surface = surf
        self._bezel_key = size
        return surf

    def present(self, screen: pygame.Surface) -> None:
        """Blit the fixed 800x600 canvas onto any window/fullscreen size."""
        dx, dy = self.shake_offset()
        sw, sh = screen.get_size()
        if (sw, sh) == (WIDTH, HEIGHT):
            if dx or dy:
                screen.fill((0, 0, 0))
            screen.blit(self.canvas, (dx, dy))
            return
        scale = min(sw / WIDTH, sh / HEIGHT)
        w = max(1, int(WIDTH * scale))
        h = max(1, int(HEIGHT * scale))
        ox = (sw - w) // 2
        oy = (sh - h) // 2
        if ox or oy:
            screen.blit(self._bezel((sw, sh)), (0, 0))
        else:
            screen.fill((0, 0, 0))
        # Reuse the scaled canvas between frames: smoothscale allocates and
        # converts a full surface otherwise, every single frame.
        if self._scaled is None or self._scaled.get_size() != (w, h):
            self._scaled = pygame.Surface((w, h))
        pygame.transform.smoothscale(self.canvas, (w, h), self._scaled)
        screen.blit(self._scaled, (ox + dx, oy + dy))

    def update_effects(self, dt: float) -> None:
        if self.combo_time > 0:
            self.combo_time = max(0.0, self.combo_time - dt)
            if self.combo_time == 0:
                self.combo = 0
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
