"""Tunable constants, colours, and file paths for Space Invaders."""

from __future__ import annotations

import os
from pathlib import Path

WIDTH, HEIGHT = 800, 600
FPS = 60
FIELD_TOP = 64
CRT_DEFAULT = "medium"       # "off" | "low" | "medium" | "high"
CRT_INTENSITY = 1.0          # 0.0 = off, 1.0 = full preset strength
HUD_CRT_HEIGHT = 64          # top HUD strip is capped at medium while playing

BG_TOP = (8, 10, 26)
BG_BOTTOM = (18, 12, 34)
PLAYER_COLOR = (120, 255, 180)
PLAYER_BULLET_COLOR = (240, 255, 200)
ALIEN_BULLET_COLOR = (255, 120, 140)
UI_COLOR = (200, 210, 255)
UI_DIM = (110, 115, 160)
UI_RECORD = (255, 224, 140)   # the live BEST line under the top-left corner
OVERLAY_DIM = 190             # dark wash behind title, pause and help cards
SCORES_DIM = 220              # slightly heavier wash behind the leaderboard

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
FORMATION_BASE_SPEED = 32.0     # px/s at full strength on wave 1
FORMATION_SPEED_RAMP = 0.16     # speed gained per wave
FORMATION_THINNING_SPEED = 150.0  # extra px/s as the fleet thins

PLAYER_BULLET_SPEED = 620.0
ALIEN_BULLET_SPEED = 250.0
PLAYER_FIRE_COOLDOWN = 0.22
MAX_PLAYER_BULLETS = 3

# Dash: double-tap a direction for a short burst that ignores held movement.
DASH_TAP_WINDOW = 0.28       # seconds between taps that counts as a double-tap
DASH_SPEED = 900.0           # px/s during the burst
DASH_TIME = 0.14             # seconds of burst (900 x 0.14 = 126 px)
DASH_COOLDOWN = 1.2

# Screen shake: peak displacement in canvas pixels per trigger.  Overlapping
# shakes add together, up to SHAKE_MAX, and fade with SHAKE_DECAY (seconds).
SHAKE_DRIFTER = 6.0          # you shot a floating avatar
SHAKE_UFO = 8.0              # you brought down the mystery saucer
SHAKE_LIFE_LOST = 9.0        # the ship was hit
SHAKE_RECORD = 16.0         # half the fleet exploded: new high score
SHAKE_BANNER = 6.0           # held for as long as the record marquee rolls
SHAKE_BOSS_RAGE = 11.0       # the boss crosses into overdrive
SHAKE_MAX = 20.0
SHAKE_DECAY = 0.16

# Celebratory marquee when a run passes the board's best. Play is frozen
# while it is on screen.
RECORD_BANNER_TIME = 3.0
RECORD_BANNER_SCROLL = 190.0     # px/s of horizontal marquee travel

# Flow beats: a short wave card freezes play between waves, while the
# game-over shade and the red hurt vignette fade in/out instead of popping.
WAVE_INTRO_TIME = 1.05           # regular wave card, seconds
WAVE_INTRO_BOSS_TIME = 1.35      # boss waves get a longer warning
GAMEOVER_FADE = 0.45             # seconds for the game-over overlay to fade in
GAMEOVER_ARTICLE_DELAY = 0.5     # seconds before ←/→ browse NASA stories
HURT_FLASH_TIME = 0.45           # red edge vignette after losing a life

# Feel: ship exhaust/muzzle feedback, kill chains, and backdrop crossfades.
MUZZLE_FLASH_TIME = 0.07
COMBO_WINDOW = 1.35             # seconds between kills that keeps a chain alive
COVER_FADE_TIME = 0.55          # crossfade from the old cover to the new one

# Music: loop length multiplier.  Smaller values compose faster and use less
# memory, which makes the next-wave prefetch more reliable.  1.0 = full length.
MUSIC_SHORTEN = 0.75
# Music automatically ducks outside active play, then swells back on resume.
MUSIC_DUCK_FADE = 0.22           # seconds to reach a new duck level
MUSIC_DUCK_PAUSED = 0.35
MUSIC_DUCK_SCORES = 0.45
MUSIC_DUCK_GAMEOVER = 0.0

# Floating "+points" numbers: how long they live and how fast they rise.
POPUP_LIFE = 0.9
POPUP_RISE = 34.0

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
# Boss fights phase the bunkers out so the player has to dodge uncovered.
SHIELD_BLINK_INTERVAL = (2.2, 3.2)   # seconds between phase-outs
SHIELD_BLINK_TIME = 0.8              # seconds the bunkers stay gone

# Floating avatar hazards (one sprite sheet, six badges).
AVATAR_SHEET = Path(os.environ.get(
    "SPACE_INVADERS_AVATARS", Path.home() / "avatars" / "image_79efc5be.jpeg"))
DRIFTER_SIZE = 39            # a little larger than an alien (34 x 24)
DRIFTER_SPEED_MIN, DRIFTER_SPEED_MAX = 70.0, 125.0
DRIFTER_SPAWN_DELAY = 2.2
DRIFTER_RESPAWN = 4.5
DRIFTER_LIFE = 10.0           # seconds before a badge fades out and pops
DRIFTER_POINTS = 100          # the most it pays, for a hit at spawn
DRIFTER_POINTS_MIN = 10       # the least, just before it fades away
# The badge limit is the wave number: 1 on wave 1, 2 on wave 2, and so on.

# Mystery UFO: a saucer that crosses the top of the arena on a timer.
UFO_Y = FIELD_TOP + 3
UFO_W, UFO_H = 46, 18
UFO_SPEED_MIN, UFO_SPEED_MAX = 70.0, 105.0
UFO_FIRST_DELAY = (10.0, 22.0)   # seconds before the first one of a run
UFO_RESPAWN = 25.0               # seconds between appearances
UFO_POINTS = (50, 100, 150, 300)
UFO_COLOR = (214, 228, 255)
UFO_LIGHT = (255, 150, 80)

# Power-up capsules dropped by destroyed aliens and caught with the ship.
POWERUP_DROP_CHANCE = 0.07
POWERUP_FALL_SPEED = 95.0
POWERUP_SIZE = 18
POWERUP_RAPID_SCALE = 0.4     # fire cooldown multiplier while rapid is on
POWERUP_RAPID_TIME = 8.0
POWERUP_TRIPLE_TIME = 10.0
POWERUP_KINDS = ("rapid", "triple", "repair")
POWERUP_WEIGHTS = (40, 35, 25)
POWERUP_COLORS = {
    "rapid": (255, 205, 90),
    "triple": (120, 220, 255),
    "repair": (150, 255, 195),
}
POWERUP_LABELS = {"rapid": "R", "triple": "T", "repair": "B"}

# Dive-bombers: every so often one formation alien peels off to kamikaze.
DIVE_FIRST_DELAY = (4.0, 7.5)
DIVE_INTERVAL = (5.0, 8.5)
DIVE_MIN_ALIVE = 8          # don't dive when the wave is nearly cleared
DIVE_MAX_GROUP = 5          # wave 5+ can send this many kamikazes at once
DIVE_SPEED_X = 220.0
DIVE_START_VY = 110.0
DIVE_MAX_VY = 330.0
DIVE_ACCEL = 240.0
DIVE_TURN = 2.5             # how quickly a dive turns toward the ship

# Boss wave: every fifth wave a single wide machine replaces the formation.
BOSS_EVERY = 5
BOSS_W, BOSS_H = 132, 58
BOSS_Y = FORMATION_TOP + 12
BOSS_ENTRY_TIME = 1.0        # seconds for the hull to slide down into place
BOSS_SWAY = 46.0            # pixels either side of centre while it hovers
BOSS_SWAY_SPEED = 0.55      # radians per second
BOSS_HP_BASE = 30
BOSS_HP_STEP = 12
BOSS_SCORE_BASE = 1000
BOSS_SCORE_STEP = 250
BOSS_FIRE_MIN, BOSS_FIRE_MAX = 1.4, 2.2
BOSS_RAGE_FIRE_SCALE = 0.72  # volley interval multiplier below half health
BOSS_RAGE_SWAY_SCALE = 1.35  # sway speed multiplier below half health
BOSS_VOLLEY_SPEED = 250.0
BOSS_COLOR = (238, 120, 190)
BOSS_DARK = (58, 26, 62)
BOSS_LIGHT = (255, 210, 120)

# NASA story card on the game-over screen.
NEWS_URL = "https://www.nasa.gov/news/recently-published/"
NEWS_TIMEOUT = 8.0
STORY_IMAGE_W, STORY_IMAGE_H = 320, 180

# Persistent high-score table.
LEADERBOARD_SIZE = 100
LEADERBOARD_ROWS = 15        # visible rows on the scores screen
SCORES_FILE = Path(os.environ.get(
    "SPACE_INVADERS_SCORES",
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    / "space_invaders" / "leaderboard.json",
)).expanduser()


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
