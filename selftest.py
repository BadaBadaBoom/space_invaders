"""Headless smoke tests and invariant checks."""

from __future__ import annotations

import json
import random
from array import array
from pathlib import Path

import pygame

from assets import make_pulp_background
from config import (
    ALIEN_BULLET_SPEED,
    ALIEN_H,
    ALIEN_W,
    AVATAR_SHEET,
    BOSS_HP_BASE,
    BOSS_SCORE_BASE,
    BOSS_W,
    BOSS_Y,
    COLS,
    DASH_COOLDOWN,
    DASH_SPEED,
    DASH_TAP_WINDOW,
    DASH_TIME,
    DRIFTER_LIFE,
    DRIFTER_POINTS,
    DRIFTER_POINTS_MIN,
    DRIFTER_RESPAWN,
    DRIFTER_SIZE,
    DRIFTER_SPAWN_DELAY,
    DROP_DISTANCE,
    FLOOR_Y,
    HEIGHT,
    LANDING_Y,
    LEADERBOARD_SIZE,
    LEFT_WALL,
    PLAYER_BULLET_SPEED,
    PLAYER_FIRE_COOLDOWN,
    PLAYER_W,
    POWERUP_RAPID_SCALE,
    POWERUP_RAPID_TIME,
    POWERUP_SIZE,
    POWERUP_TRIPLE_TIME,
    RIGHT_WALL,
    ROW_POINTS,
    ROWS,
    RECORD_BANNER_TIME,
    SHIELD_COLS,
    SHIELD_ROWS,
    SHIELDS,
    SHAKE_DRIFTER,
    SHAKE_LIFE_LOST,
    SHAKE_MAX,
    SHAKE_RECORD,
    SHAKE_UFO,
    UFO_FIRST_DELAY,
    UFO_POINTS,
    UFO_RESPAWN,
    UFO_SPEED_MIN,
    UFO_Y,
    WIDTH,
)
from deps import metal, np
from entities import Bullet, Drifter, PowerUp, Shield, Ufo
from game import Game
from leaderboard import Leaderboard, _score_order
from render import alien_look


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
    check_ufo()
    check_powerups()
    check_boss()
    check_dash()
    check_feedback()
    check_leaderboard()
    check_clear_scores()
    check_record_celebration()
    check_news()
    check_stats()
    check_scaling(game)
    check_crt()
    check_backgrounds(scores)
    check_cover_scenes()
    check_music()
    check_music_player()
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
        game.update_feedback(dt)
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
        dx, dy = game.shake_offset()
        assert abs(dx) <= SHAKE_MAX and abs(dy) <= SHAKE_MAX
        assert all(p[4] > 0 for p in game.popups)
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

    # The younger the badge, the more a bullet kill pays.
    assert Drifter(image, palette, 0, 0, 0, 0).value == DRIFTER_POINTS
    aged = Drifter(image, palette, 0, 0, 0, 0)
    aged.age = DRIFTER_LIFE / 2
    assert aged.fade == 0.5
    assert aged.value == round(
        DRIFTER_POINTS_MIN + (DRIFTER_POINTS - DRIFTER_POINTS_MIN) * 0.5)
    aged.age = DRIFTER_LIFE
    assert aged.fade == 0.0 and aged.value == DRIFTER_POINTS_MIN

    game = fresh()
    game.score = 0
    late = Drifter(image, palette, 400, 300, 0, 0)
    late.age = DRIFTER_LIFE * 0.9
    game.drifters = [late]
    game.player_bullets.append(Bullet(410, 310, -PLAYER_BULLET_SPEED, True))
    game.update_drifters(1 / 60)
    assert not game.drifters
    assert DRIFTER_POINTS_MIN <= game.score < DRIFTER_POINTS

    # At the end of its life it pops harmlessly: no score, no kill credit.
    game = fresh()
    old = Drifter(image, palette, 400, 300, 0, 0)
    old.age = DRIFTER_LIFE - 0.01
    game.drifters = [old]
    debris_before = len(game.debris)
    game.update_drifters(0.02)
    assert not game.drifters, "expired badge stayed in the arena"
    assert game.score == 0 and game.avatars_killed == 0
    assert len(game.debris) > debris_before and game.rings and game.flashes
    assert game.drifter_timer == DRIFTER_RESPAWN

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


def check_ufo() -> None:
    """The saucer appears on a timer, crosses, and pays from its table."""
    game = Game(seed=31)
    game.start()
    assert game.ufo is None, "a fresh run starts with no saucer"
    assert 0 < game.ufo_timer <= UFO_FIRST_DELAY[1]

    assert "wail" in game.sounds, "no saucer death cry"
    if pygame.mixer.get_init():
        assert game.sounds["wail"] is not None, "wail failed to synthesize"

    game.ufo_timer = 0.01
    game.update_ufo(0.02)
    ufo = game.ufo
    assert ufo is not None, "saucer never appeared"
    assert ufo.y == UFO_Y
    assert abs(ufo.vx) >= UFO_SPEED_MIN
    assert ufo.points in UFO_POINTS
    assert ufo.x < 0 or ufo.x >= WIDTH - 1, "saucer did not start off-screen"

    # It leaves the far side and another is scheduled.
    game.update_ufo(30.0)
    assert game.ufo is None, "saucer never left the arena"
    assert 0 < game.ufo_timer <= UFO_RESPAWN + 3.0

    # A player bullet brings it down for its listed points.
    game.ufo = Ufo(WIDTH / 2, UFO_Y, 80.0, 300)
    game.score = 0
    game.shots_hit = 0
    game.popups = []
    game.shake_energy = 0.0
    played: list[str] = []
    game.play = played.append
    game.player_bullets = [Bullet(WIDTH / 2 + 10, UFO_Y + 6,
                                  -PLAYER_BULLET_SPEED, True)]
    debris_before = len(game.debris)
    game.check_collisions()
    assert game.ufo is None, "bullet did not down the saucer"
    assert game.score == 300
    assert game.shots_hit == 1
    assert len(game.debris) > debris_before, "no explosion debris"
    assert game.popups and game.popups[-1][2] == "+300"
    assert 0 < game.ufo_timer <= UFO_RESPAWN + 3.0
    assert game.shake_energy == SHAKE_UFO, "saucer kill did not shake"
    assert "wail" in played, "saucer died with the generic blast"
    del game.play

    # Alien fire passes it by: only your bullets count.
    game.ufo = Ufo(WIDTH / 2, UFO_Y, 0.0, 50)
    game.alien_bullets = [Bullet(WIDTH / 2 + 10, UFO_Y + 6,
                                 ALIEN_BULLET_SPEED, False)]
    game.check_collisions()
    assert game.ufo is not None, "enemy fire downed the saucer"


def check_powerups() -> None:
    """Capsules drop occasionally, fall, and hand over their boost on catch."""
    game = Game(seed=41)
    game.start()
    assert game.powerups == []

    # Drops are occasional: some kills leave one, most do not, and repair
    # never drops while every bunker is whole.
    game.rng.seed(7)
    drops = 0
    for _ in range(600):
        before = len(game.powerups)
        game.maybe_drop_powerup(WIDTH / 2, 200)
        drops += len(game.powerups) - before
    assert 0 < drops < 600, f"{drops} drops in 600 kills"
    assert all(p.kind != "repair" for p in game.powerups), (
        "repair capsule dropped with the bunkers intact")

    # Catching a capsule applies it; missing one drops off the floor.
    game.powerups = []
    game.player.x = WIDTH / 2 - PLAYER_W / 2
    game.player.rapid = 0.0
    game.spawn_powerup("rapid", game.player.center_x, game.player.y)
    game.update_powerups(1 / 60)
    assert game.powerups == [], "capsule was not collected"
    assert game.player.rapid == POWERUP_RAPID_TIME

    game.powerups = [PowerUp("triple", 400, FLOOR_Y - POWERUP_SIZE - 1)]
    game.update_powerups(0.5)
    assert game.powerups == [], "capsule outlived the floor"

    # Shooting a capsule also collects it, and consumes the bullet.
    game.player.triple = 0.0
    game.powerups = [PowerUp("triple", 400, 300)]
    game.player_bullets = [Bullet(405, 305, -PLAYER_BULLET_SPEED, True)]
    game.check_collisions()
    assert game.powerups == [], "shot capsule survived"
    assert game.player_bullets == [], "shot capsule did not eat the bullet"
    assert game.player.triple == POWERUP_TRIPLE_TIME

    # Rapid fire shortens the cooldown.
    game.player.rapid = 5.0
    game.player.triple = 0.0
    game.player.cooldown = 0.0
    game.player_bullets.clear()
    game.update_player(0, 0, True)
    assert game.player.cooldown == PLAYER_FIRE_COOLDOWN * POWERUP_RAPID_SCALE

    # Triple shot fires three parallel bullets and counts every one as a shot.
    game.player.rapid = 0.0
    game.player.triple = 5.0
    game.player.cooldown = 0.0
    game.player_bullets.clear()
    game.shots_fired = 0
    game.update_player(0, 0, True)
    xs = sorted(bullet.x for bullet in game.player_bullets)
    assert len(xs) == 3, f"triple shot fired {len(xs)} bullets"
    assert xs[1] - xs[0] == 10 and xs[2] - xs[1] == 10
    assert game.shots_fired == 3

    # Timers run down on their own.
    game.update_player(1.0, 0, False)
    assert 3.9 < game.player.triple < 4.1

    # Repair rebuilds a wrecked bunker and counts the cells as deployed.
    game.shields = game.make_shields()
    game.bunker_cells_total = sum(s.alive_cells() for s in game.shields)
    bunker = game.shields[0]
    for row in range(2, 8):
        for col in range(4, 12):
            bunker.damage(row, col, radius=0.0)
    assert bunker.alive_cells() < bunker.intact, "test bunker survived damage"
    deployed = game.bunker_cells_total
    game.apply_powerup(PowerUp("repair", 100, 100))
    assert bunker.alive_cells() == bunker.intact, "bunker was not repaired"
    assert game.bunker_cells_total > deployed


def check_boss() -> None:
    """Every fifth wave fields one wide boss instead of a formation."""
    game = Game(seed=51)
    game.start()
    assert game.wave == 1 and game.boss is None
    assert len(game.alive_aliens()) == COLS * ROWS

    # Wave 5 replaces the 32 aliens with a single machine.
    game.wave = 5
    game.spawn_wave()
    boss = game.boss
    assert boss is not None, "wave 5 did not spawn a boss"
    assert game.alive_aliens() == [], "boss wave kept the formation"
    assert boss.max_hp == BOSS_HP_BASE
    assert boss.points == BOSS_SCORE_BASE
    assert boss.y == BOSS_Y

    # Later bosses are tougher and worth more; ordinary waves recovered.
    game.wave = 10
    game.spawn_wave()
    assert game.boss is not None and game.boss.max_hp > boss.max_hp
    assert game.boss.points > boss.points
    game.wave = 6
    game.spawn_wave()
    assert game.boss is None and len(game.alive_aliens()) == COLS * ROWS

    # It hovers inside the arena and never marches like the formation.
    game.wave = 5
    game.spawn_wave()
    boss = game.boss
    xs = []
    for _ in range(240):
        game.update_boss(1 / 60)
        xs.append(boss.x)
    assert max(xs) - min(xs) > 10, "boss never swayed"
    assert min(xs) >= LEFT_WALL and max(xs) + BOSS_W <= RIGHT_WALL
    assert boss.y == BOSS_Y, "boss drifted vertically"

    # Volleys cycle a fan, an aimed triple and a rain of shots.
    game.boss_volley_index = 0
    game.alien_bullets.clear()
    game.player.x = LEFT_WALL + 4
    game.fire_boss_volley()
    assert len(game.alien_bullets) == 5, "fan volley lost shots"
    game.alien_bullets.clear()
    game.fire_boss_volley()
    aimed = list(game.alien_bullets)
    assert len(aimed) == 3, "aimed volley lost shots"
    assert all(bullet.vx < 0 for bullet in aimed), (
        "aimed volley did not lean toward a ship on the left")
    game.alien_bullets.clear()
    game.fire_boss_volley()
    assert len(game.alien_bullets) == 6, "rain volley lost shots"

    # Damage ticks down, then the kill pays out and clears the screen.
    game.alien_bullets = [Bullet(100, 300, 200, False)]
    boss = game.boss
    game.score = 0
    game.shots_hit = 0
    start_hp = boss.hp
    game.damage_boss()
    assert boss.hp == start_hp - 1 and game.shots_hit == 1
    assert game.boss_flash > 0, "hit did not flash the boss"
    boss.hp = 1
    game.damage_boss()
    assert game.boss is None, "boss survived its last hit"
    assert game.score == boss.points
    assert game.alien_bullets == [], "boss bullets survived the kill"
    assert game.victory_timer > 0, "no pause for the explosion"
    assert game.powerups, "boss kill dropped no capsule"

    # After the victory pause the next wave rolls in.
    game.player.invulnerable = 999.0
    for _ in range(120):
        game.update(1 / 60)
        if game.wave == 6:
            break
    assert game.wave == 6, "wave did not advance after the boss died"
    assert game.boss is None and game.alive_aliens()
    assert game.powerups, "the reward capsule died with the wave change"


def check_dash() -> None:
    """A double-tap bursts the ship, clamps at the walls and cools down."""
    game = Game(seed=61)
    game.start()
    player = game.player
    assert player.dash_cooldown == 0.0

    assert not game.tap(1, 100.0), "a single tap dashed"
    assert game.tap(1, 100.0 + DASH_TAP_WINDOW / 2), "double tap did not dash"
    assert player.dash_time > 0 and player.dash_cooldown > 0
    assert player.dash_dir == 1
    game.draw(game.canvas)      # the shield must paint without raising

    # The burst wins over held movement.
    start_x = player.x
    game.update_player(1 / 60, -1, False)
    assert player.x > start_x + DASH_SPEED / 120, "dash did not move the ship"

    # It clamps at the wall instead of overshooting.
    player.x = RIGHT_WALL - PLAYER_W - 2
    player.dash_time = DASH_TIME
    player.dash_dir = 1
    game.update_player(0.5, 0, False)
    assert player.x == RIGHT_WALL - PLAYER_W

    # Cooling down blocks another burst; it comes back afterwards.
    player.dash_cooldown = DASH_COOLDOWN
    assert not game.dash(-1), "dashed while cooling down"
    player.dash_cooldown = 0.0
    assert game.dash(-1), "dash never came back"

    # Taps further apart than the window are not a double-tap.
    player.dash_cooldown = 0.0
    player.dash_time = 0.0
    assert not game.tap(-1, 200.0)
    assert not game.tap(-1, 200.0 + DASH_TAP_WINDOW + 0.01)

    # The burst is invulnerable: bullets pass through it.
    player.dash_time = DASH_TIME
    player.dash_dir = 1
    player.invulnerable = 0.0
    lives = game.lives
    game.alien_bullets = [Bullet(player.center_x, player.y,
                                 ALIEN_BULLET_SPEED, False)]
    game.check_collisions()
    assert game.lives == lives, "dashed through a bullet and died"
    assert game.alien_bullets, "the dash swallowed the bullet"

    # Dashing through a badge destroys it without costing a life.
    badge = Drifter(pygame.Surface((DRIFTER_SIZE, DRIFTER_SIZE)),
                    [(255, 0, 0)], player.x, player.y, 0, 0)
    game.drifters = [badge]
    player.dash_time = DASH_TIME
    game.check_drifter_collisions(badge)
    assert game.drifters == [], "badge survived a dash-through"
    assert game.lives == lives, "dash-through killed the ship"

    # Once the burst ends, contact hurts again.
    player.dash_time = 0.0
    game.alien_bullets = [Bullet(player.center_x, player.y,
                                 ALIEN_BULLET_SPEED, False)]
    game.check_collisions()
    assert game.lives == lives - 1, "i-frames outlived the dash"

    # And it is only available during active play.
    game.state = "paused"
    assert not game.dash(1)
    game.state = "playing"


def check_feedback() -> None:
    """Shake fires on all three triggers and settles; points pop and rise."""
    game = Game(seed=21)
    game.start()
    assert game.shake_energy == 0.0, "a fresh run must not shake"
    assert game.shake_offset() == (0, 0), "a fresh run must not be offset"

    # Losing a life jolts the screen; the offset stays bounded by SHAKE_MAX.
    game.lives = 3
    game.player_hit()
    assert game.shake_energy == SHAKE_LIFE_LOST
    dx, dy = game.shake_offset()
    assert abs(dx) <= SHAKE_MAX and abs(dy) <= SHAKE_MAX
    for _ in range(120):
        game.update_feedback(1 / 60)
    assert game.shake_energy == 0.0, "shake never settled"
    assert game.shake_offset() == (0, 0)

    # Shooting a badge shakes, but less than losing a life or beating the board.
    assert SHAKE_DRIFTER < SHAKE_UFO < SHAKE_LIFE_LOST < SHAKE_RECORD
    game.shake_energy = 0.0
    badge = Drifter(pygame.Surface((DRIFTER_SIZE, DRIFTER_SIZE)),
                    [(255, 60, 90)], 400, 300, 0, 0)
    game.drifters = [badge]
    game.destroy_drifter(badge)
    assert game.shake_energy == SHAKE_DRIFTER
    assert game.shake_offset() != (0, 0), "badge kill does not move the view"

    # The record blast is the big one, and stacked hits are capped.
    game.shake_energy = 0.0
    game.record_to_beat = 1
    game.record_beaten = False
    game.score = 2
    game.maybe_celebrate_record()
    assert game.shake_energy == SHAKE_RECORD
    game.add_shake(SHAKE_RECORD * 10)
    assert game.shake_energy == SHAKE_MAX, "shake stacked past the cap"

    # A kill spawns a rising, fading number and it is cleaned up.
    game = Game(seed=21)
    game.start()
    game.popups = []
    game.score = 0
    target = game.aliens[0]
    game.player_bullets.append(
        Bullet(target.x + ALIEN_W / 2, target.y + ALIEN_H / 2,
               -PLAYER_BULLET_SPEED, True))
    game.check_collisions()
    assert not target.alive, "test bullet missed the alien"
    assert len(game.popups) == 1, "kill did not pop up a score"
    popup = game.popups[0]
    assert popup[2] == f"+{ROW_POINTS[0]}"
    top = popup[1]
    game.update_feedback(1 / 60)
    assert popup[1] < top, "score popup did not rise"
    game.update_feedback(popup[4] + 0.01)
    assert not game.popups, "score popup never expired"

    # Every wave gets its own fleet silhouette, never repeating a feature on
    # the next wave, and the same wave always looks the same.
    looks = [alien_look(wave) for wave in range(1, 10)]
    assert alien_look(3) == alien_look(3), "wave look is not deterministic"
    for before, after in zip(looks, looks[1:]):
        assert before.antenna != after.antenna, "headgear repeated next wave"
        assert before.eyes != after.eyes, "eyes repeated next wave"
        assert before.legs != after.legs, "legs repeated next wave"


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
        for entry in board.entries:
            name = entry["name"]
            assert (isinstance(name, str) and name and name.isupper()
                    and " " not in name and len(name) <= 12), f"bad name {name!r}"
        assert len({entry["name"] for entry in board.entries}) == LEADERBOARD_SIZE, (
            "handles should be unique while the name pool lasts")
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
        # Bad rows drop out, a stored handle is sanitised, and an old
        # nameless row is given one that is written back for next time.
        assert len(loaded) == 2, f"loaded {len(loaded)} rows"
        assert loaded[0]["score"] == 99999
        assert loaded[0]["name"] == "RUNNER12345"
        assert loaded[1]["name"] and " " not in str(loaded[1]["name"])
        assert Leaderboard(path).entries == loaded, (
            "generated handle did not persist")

        # Erasing the board empties it in memory and on disk.
        assert board.clear() == LEADERBOARD_SIZE
        assert board.entries == [] and board.best == 0
        assert Leaderboard(path).entries == []
        assert board.clear() == 0, "clearing an empty board should be a no-op"


def check_clear_scores() -> None:
    """Delete arms the erase, a second press commits, a timeout cancels."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="space_invaders_clear_") as tmp:
        board = Leaderboard(Path(tmp) / "board.json")
        board.add({"score": 10, "wave": 1, "avatars": 0,
                   "bunker": 0.0, "accuracy": 0.0})
        game = Game(seed=2, leaderboard=board)
        game.show_scores()

        assert not game.clear_scores(), "first press must only arm"
        assert game.clear_armed and len(board.entries) == 1
        assert game.clear_scores(), "second press did not erase"
        assert not game.clear_armed and board.entries == []
        assert Leaderboard(board.path).entries == [], "erase was not persisted"

        # Past the confirmation window the next press only re-arms.
        board.add({"score": 5, "wave": 1, "avatars": 0,
                   "bunker": 0.0, "accuracy": 0.0})
        game.clear_scores()
        game.clear_hint_until = pygame.time.get_ticks() - 1
        assert not game.clear_scores(), "expired confirmation still erased"
        assert len(board.entries) == 1

        # Leaving the screen cancels a pending erase.
        game.close_scores()
        assert not game.clear_armed


def check_record_celebration() -> None:
    """The board's best is shown live and beaten with one celebration."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="space_invaders_record_") as tmp:
        board = Leaderboard(Path(tmp) / "board.json")
        assert board.best == 0, "empty board should report no best score"

        # An empty board has no record to beat, so nothing may trigger.
        empty = Game(seed=3, leaderboard=board)
        empty.start()
        assert empty.record_to_beat == 0
        empty.score = 500
        empty.maybe_celebrate_record()
        assert not empty.record_beaten
        assert len(empty.alive_aliens()) == 32, "empty board celebrated"

        board.add({"score": 500, "wave": 4, "avatars": 2,
                   "bunker": 20.0, "accuracy": 50.0})
        assert board.best == 500

        game = Game(seed=11, leaderboard=board)
        game.start()
        assert game.story is None
        game.story = object()
        game.start()
        assert game.story is None, "a new run must clear the previous story"
        assert game.record_to_beat == 500 and not game.record_beaten
        if metal is not None and pygame.mixer.get_init():
            assert "record" in game.sounds, "record boom was not pre-rendered"

        before = len(game.alive_aliens())
        debris_before = len(game.debris)
        game.score = 500
        game.maybe_celebrate_record()
        assert not game.record_beaten, "celebrated on a tie"
        assert len(game.alive_aliens()) == before
        assert game.record_banner_time == 0.0, "tie raised the marquee"

        game.score = 501
        game.maybe_celebrate_record()
        popped = before - len(game.alive_aliens())
        assert game.record_beaten, "record was not celebrated"
        assert popped == before // 2, f"expected half the formation, got {popped}"
        assert len(game.debris) > debris_before, "no explosion debris"
        assert game.score == 501, "celebration awarded points"
        assert game.record_banner_time == RECORD_BANNER_TIME, (
            "no marquee for the new record")
        assert game.record_banner_score == 501, "marquee shows the wrong score"
        game.draw(game.canvas)          # the marquee must paint without raising
        game.update_feedback(RECORD_BANNER_TIME + 0.01)
        assert game.record_banner_time == 0.0, "marquee never expired"

        remaining = len(game.alive_aliens())
        game.maybe_celebrate_record()
        assert len(game.alive_aliens()) == remaining, "celebration repeated"

        # Two survivors: floor division pops one and leaves the wave intact.
        edge = Game(seed=11, leaderboard=board)
        edge.start()
        for alien in edge.alive_aliens()[2:]:
            alien.alive = False
        edge.score = 501
        edge.maybe_celebrate_record()
        assert len(edge.alive_aliens()) == 1, "celebration cleared the wave"


def check_news() -> None:
    """NASA cards parse in page order, follow Next, and advance one round."""
    from news import (
        Listing,
        NewsFeed,
        Story,
        _is_junk,
        page_url,
        parse_listing,
        read_block_attrs,
        summary_from_article,
    )

    page = """
    <main>
      <div class="hds-content-items hds-content-items-list"
           data-post-type="post,nasa-blog" data-post-id="383829"
           data-max-num-pages="4066" data-per-page="25"
           data-current-page="1">
      <div class="hds-content-item">
        <a href="https://www.nasa.gov/story-a/" class="hds-content-item-heading">
          <div class="hds-a11y-heading-22">First &amp; Story</div>
        </a>
        <div class="hds-content-item-readtime label margin-bottom-1">3 min read</div>
        <p class="margin-top-0 margin-bottom-1">A real summary &hellip;</p>
        <div class="display-flex flex-align-center label color-carbon-60">
          <span>Blog</span>
        </div>
        <img src="https://www.nasa.gov/a.jpg?w=300">
      </div>
      <div class="hds-content-item">
        <a href="https://science.nasa.gov/apod/" class="hds-content-item-heading">
          <div class="hds-a11y-heading-22">APOD: Sample</div>
        </a>
        <p class="margin-top-0 margin-bottom-1">APOD Science APOD Today&rsquo;s
          APOD Archive Submissions Index Search Calendar</p>
        <img src="https://assets.science.nasa.gov/b.jpg">
      </div>
      </div>
      <nav class="hds-pagination">
        <a class="next page-numbers" href="#" aria-label="Goto Next Page"
           data-page-number="2">Next</a>
      </nav>
    </main>
    """
    listing = parse_listing(page)
    assert listing.page == 1 and listing.next_page == 2
    assert len(listing.stories) == 2
    first = listing.stories[0]
    assert first.title == "First & Story", first.title
    assert first.summary.startswith("A real summary")
    assert first.image_url.endswith("?w=600"), first.image_url
    assert first.kind == "Blog", first.kind
    assert first.read_time == "3 min read", first.read_time
    assert listing.stories[1].image_url.endswith("?w=600")

    attrs = read_block_attrs(page)
    assert attrs["post-id"] == "383829"
    url = page_url("https://www.nasa.gov/wp-json/nasa-hds/v1/content-lists",
                   attrs, 2)
    assert "pageClicked=2" in url and "postId=383829" in url

    assert _is_junk("APOD Science APOD Today's APOD Archive Submissions "
                    "Index Search Calendar", "APOD")
    assert not _is_junk("Ice near the summit has shrunk to patches.",
                        "The Last Ice on Puncak Jaya")
    assert summary_from_article(
        '<meta property="og:description" '
        'content="A proper NASA summary of the mission and its goals.">'
    ).startswith("A proper NASA summary")
    assert summary_from_article(
        "<p>Explanation: How do stars form? Webb took this detailed image "
        "of a stellar nursery.</p>"
    ).startswith("How do stars form?")

    # One round consumes one story; crossing the last story loads the page
    # the Next button points at.
    a = Story("A", "summary", "link", "")
    b = Story("B", "summary", "link", "")
    feed = NewsFeed()
    feed.stories = [a, b]
    feed.next_page = 2
    feed._loaded = {0: a, 1: b}
    feed.begin_round()
    assert feed.current is a
    assert feed.take() is a
    feed.advance()
    assert feed.index == 1

    feed._next_listing = Listing(2, [Story("C", "summary", "link", "")], 3)
    feed.begin_round()
    assert feed.take() is b
    feed.advance()
    assert feed.page == 2 and feed.index == 0
    assert feed.stories[0].title == "C"

    # The last page of the archive has no Next link: it holds, never wraps.
    end = NewsFeed()
    end.stories = [a]
    end._loaded = {0: a}
    end.begin_round()
    assert end.take() is a
    end.advance()
    assert end.index == 0 and end.stories[0] is a


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
        assert saved["name"] and " " not in str(saved["name"])
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


def check_cover_scenes() -> None:
    """Every composition paints cleanly, and the robot invasion is wired up."""
    from covers import SCENES, _gradient, _palette

    names = [name for name, _paint, _weight in SCENES]
    assert len(set(names)) == len(names), "duplicate scene name"
    assert len(names) >= 6, f"only {len(names)} compositions"
    assert "robots" in names, "robot invasion scene is missing"
    for name, paint, weight in SCENES:
        assert weight > 0, f"scene {name} can never be chosen"
        for seed in range(3):
            rng = random.Random(seed * 17 + 3)
            pal = _palette(rng)
            art = _gradient(400, 300, pal["sky_top"], pal["sky_bottom"])
            paint(art, rng, pal)
            assert art.get_size() == (400, 300), f"{name} resized the canvas"


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


def check_music_player() -> None:
    """Numpad + switches genre, and prepare() is idempotent."""
    import audio

    calls: list[str | None] = []

    class FakeMetal:
        GENRES = ("metal", "jazz", "disco")

        @staticmethod
        def compose(seed, genre=None):
            calls.append(genre)
            return b"\0\0" * 4410

        @staticmethod
        def pick_genre(previous=None):
            return next(genre for genre in FakeMetal.GENRES
                        if genre != previous)

    real = audio.metal
    audio.metal = FakeMetal
    try:
        player = audio.MusicPlayer(enabled=False)
        player.enabled = True
        player.channels = []
        player.request("jazz")
        assert player.genre == "jazz"
        player.next_track()
        assert player.genre != "jazz", "next song kept the genre"
        if player.thread is not None:
            player.thread.join(2)

        before = calls.count("metal")
        player.prepare("metal")
        player.prepare("metal")
        if player.prepare_thread is not None:
            player.prepare_thread.join(2)
        assert calls.count("metal") == before + 1, (
            "prepare was not idempotent")

        player.request("metal")
        assert player.pending is not None, "prepared track was not consumed"
    finally:
        audio.metal = real


def check_crt() -> None:
    """The CRT pass is deterministic, sized, and a true no-op when off/0%."""
    from crt import PRESETS, CrtOverlay

    assert tuple(PRESETS) == ("off", "low", "medium", "high")
    try:
        CrtOverlay((64, 48), preset="nope")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown CRT preset was accepted")

    def frame(preset: str, intensity: float = 1.0,
              passes: int = 1) -> tuple:
        surface = pygame.Surface((160, 120))
        surface.fill((40, 70, 110))
        for x in range(0, 160, 7):
            pygame.draw.line(surface, (220, 90, 40), (x, 0), (x, 119))
        overlay = CrtOverlay((160, 120), preset=preset,
                             intensity=intensity, seed=5)
        for step in range(passes):
            overlay.apply_inplace(surface, t=1.25 + step * 0.1)
        return surface.get_size(), pygame.image.tobytes(surface, "RGB")

    off = frame("off")
    medium = frame("medium")
    assert off[0] == medium[0] == (160, 120)
    assert off[1] != medium[1], "medium preset did not change the frame"

    assert frame("medium", intensity=0.0) == off, "zero intensity was not off"
    dim = frame("medium", intensity=0.5)
    assert dim != medium, "intensity did not change the medium preset"
    assert dim != frame("medium", intensity=0.0)

    clamped = CrtOverlay((160, 120), preset="medium", intensity=-5.0)
    assert clamped.intensity == 0.0
    clamped.set_intensity(5.0)
    assert clamped.intensity == 1.0

    reference = pygame.Surface((160, 120))
    reference.fill((40, 70, 110))
    for x in range(0, 160, 7):
        pygame.draw.line(reference, (220, 90, 40), (x, 0), (x, 119))
    before = pygame.image.tobytes(reference, "RGB")
    CrtOverlay((160, 120), preset="off").apply_inplace(reference, t=3.0)
    assert pygame.image.tobytes(reference, "RGB") == before, "off was not a no-op"

    assert frame("medium", passes=2) == frame("medium", passes=2)
    assert frame("high", passes=2) == frame("high", passes=2)
    assert frame("high", passes=2) != frame("medium", passes=2)


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
    upcoming = game.next_music_genre
    game.next_wave()
    assert pygame.image.tobytes(game.pulp_bg, "RGB") != before_art, (
        "backdrop did not change with the wave")
    if metal is not None:
        assert upcoming is not None
        assert game.music_genre == upcoming, (
            "next_wave did not use the pre-picked genre")
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
    # Clicking the NASA link must map back through the same letterboxing.
    assert game.canvas_point((WIDTH, HEIGHT), (123, 45)) == (123, 45)
    assert game.canvas_point((1600, 1200), (800, 600)) == (400.0, 300.0)
    assert game.canvas_point((1000, 600), (500, 300)) == (400.0, 300.0)
    assert game.canvas_point((1000, 800), (500, 400)) == (400.0, 300.0)
    pygame.display.set_mode((WIDTH, HEIGHT))
