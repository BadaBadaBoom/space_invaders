#!/usr/bin/env python3
"""Space Invaders — arcade game with a live heavy-metal soundtrack.

Controls
    Left / Right  or  A / D   move
    Space                     fire
    P                         pause
    M                         mute music
    Up / Down                 music volume up / down
    numpad +                  next song
    L                         high-score leaderboard
    F3                        cycle the CRT filter (off / low / medium / high)
    [ / ]                     CRT intensity down / up (10% steps)
    F11  /  Alt+Enter         fullscreen (the view scales to any size)
    Enter                     start / restart (composes a new song)

Requires: pygame-ce (or pygame)  ->  pip install pygame-ce
          numpy (optional, for the music)  ->  pip install numpy
"""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from contextlib import suppress
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

from audio import DEFAULT_VOLUME, VOLUME_STEP, MusicPlayer
from config import (
    CRT_DEFAULT,
    CRT_INTENSITY,
    FPS,
    HEIGHT,
    LEADERBOARD_ROWS,
    LEADERBOARD_SIZE,
    MUSIC_DUCK_GAMEOVER,
    MUSIC_DUCK_PAUSED,
    MUSIC_DUCK_SCORES,
    RIGHT_WALL,
    UI_DIM,
    WIDTH,
)
from crt import CrtOverlay
from deps import metal
from game import Game
from news import NewsFeed
from selftest import selftest

CRT_PRESETS = ("off", "low", "medium", "high")
CRT_INTENSITY_STEP = 0.1
MUSIC_DUCK_LEVELS = {
    "playing": 1.0,
    "title": 1.0,
    "paused": MUSIC_DUCK_PAUSED,
    "help": MUSIC_DUCK_PAUSED,
    "scores": MUSIC_DUCK_SCORES,
    "gameover": MUSIC_DUCK_GAMEOVER,
}


def read_input() -> tuple[int, bool]:
    keys = pygame.key.get_pressed()
    move = int(keys[pygame.K_RIGHT] or keys[pygame.K_d]) - int(keys[pygame.K_LEFT] or keys[pygame.K_a])
    return move, keys[pygame.K_SPACE]


def music_intensity(wave: int) -> float:
    """Scale soundtrack urgency with the wave number (0.0 early, 1.0 late)."""
    # Boss waves get an extra kick; intensity caps at 1.0.
    boss_bonus = 0.18 if wave % 5 == 0 else 0.0
    return min(1.0, (wave - 1) / 9.0 + boss_bonus)


def skip_song(player: MusicPlayer, game: Game) -> None:
    """Skip to a new genre and keep the wave's planned genre in sync."""
    player.next_track()
    if player.genre is None:
        return
    game.music_genre = player.genre
    if game.next_music_genre == game.music_genre:
        game.next_music_genre = game.choose_music_genre()
    player.prepare(game.next_music_genre, music_intensity(game.wave + 1))


def main() -> int:
    parser = argparse.ArgumentParser(description="Space Invaders")
    parser.add_argument("--selftest", action="store_true",
                        help="run a headless simulation and exit (no window)")
    parser.add_argument("--duration", type=float, default=90.0,
                        help="seconds of gameplay to simulate in --selftest")
    parser.add_argument("--no-music", action="store_true",
                        help="start with the soundtrack disabled")
    parser.add_argument("--music-volume", type=float, default=DEFAULT_VOLUME,
                        help=f"music volume, 0.0 - 1.0 "
                             f"(default {DEFAULT_VOLUME})")
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
    crt = CrtOverlay((WIDTH, HEIGHT), preset=CRT_DEFAULT,
                     intensity=CRT_INTENSITY)
    news_feed = NewsFeed()
    music_player = MusicPlayer(enabled=not args.no_music,
                              volume=args.music_volume)
    if not args.no_music and not music_player.enabled:
        print("music disabled (needs numpy: pip install numpy)")

    fire_was_down = False
    fullscreen = False
    running = True
    story_assigned = False
    volume_hint: tuple[str, int] | None = None
    crt_hint: tuple[str, int] | None = None

    def toggle_fullscreen() -> None:
        nonlocal screen, fullscreen
        fullscreen = not fullscreen
        if fullscreen:
            screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)

    # The title screen gets a track while the game is being set up; every
    # new game and every new wave composes another one.  The first NASA
    # story is fetched at the same time so the first game over is ready.
    music_player.request(intensity=0.3)
    news_feed.begin_round()
    last_wave = game.wave

    while running:
        dt = clock.tick(FPS) / 1000.0
        news_feed.update()
        game.update_feedback(dt)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                # pygame 2 resizes the display surface itself when the
                # window manager changes the window size. Calling set_mode()
                # with the size the WM just forced on us can bounce another
                # VIDEORESIZE straight back, which becomes a resize storm
                # under a tiling compositor. Only reconfigure if the surface
                # really lags behind the requested size.
                size = (max(event.w, 320), max(event.h, 240))
                if size != screen.get_size():
                    screen = pygame.display.set_mode(size, pygame.RESIZABLE)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                story = getattr(game, "story", None)
                rect = getattr(game, "story_link_rect", None)
                if game.state == "gameover" and story is not None and rect:
                    point = event.pos
                    mapper = getattr(game, "canvas_point", None)
                    if mapper is not None:
                        point = mapper(screen.get_size(), event.pos)
                    if rect.collidepoint(point):
                        # A missing browser must never take the game down.
                        with suppress(Exception):
                            webbrowser.open(story.link)
            elif event.type == pygame.MOUSEWHEEL and game.state == "scores":
                game.scroll_scores(-event.y * 3)
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
                    elif event.key == pygame.K_DELETE:
                        game.clear_scores()
                    elif event.key == pygame.K_h:
                        game.toggle_help()
                    else:
                        # Any other key cancels a pending erase.
                        game.clear_armed = False
                    continue
                if game.state == "help":
                    if event.key in (pygame.K_h, pygame.K_ESCAPE,
                                     pygame.K_RETURN):
                        game.close_help()
                    continue
                if event.key == pygame.K_ESCAPE:
                    if fullscreen:
                        toggle_fullscreen()
                    else:
                        running = False
                elif event.key == pygame.K_F11 or (
                        event.key == pygame.K_RETURN and event.mod & pygame.KMOD_ALT):
                    toggle_fullscreen()
                elif event.key == pygame.K_F3:
                    index = (CRT_PRESETS.index(crt.preset) + 1) % len(CRT_PRESETS)
                    crt.set_preset(CRT_PRESETS[index])
                    crt_hint = (f"CRT {crt.preset.upper()}",
                                pygame.time.get_ticks() + 1400)
                elif event.key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
                    step = (CRT_INTENSITY_STEP
                            if event.key == pygame.K_RIGHTBRACKET
                            else -CRT_INTENSITY_STEP)
                    crt.set_intensity(crt.intensity + step)
                    level = round(crt.intensity * 100)
                    crt_hint = (f"CRT {crt.preset.upper()} {level}%",
                                pygame.time.get_ticks() + 1400)
                elif event.key == pygame.K_l:
                    game.show_scores()
                elif event.key == pygame.K_h:
                    game.toggle_help()
                elif event.key == pygame.K_RETURN and game.state in ("title", "gameover"):
                    game.start()
                    story_assigned = False
                    news_feed.begin_round()
                    music_player.request(game.music_genre,
                                         music_intensity(game.wave))
                    music_player.prepare(game.next_music_genre,
                                         music_intensity(game.wave + 1))
                    last_wave = game.wave
                elif event.key == pygame.K_p:
                    game.toggle_pause()
                elif event.key in (pygame.K_LEFT, pygame.K_a):
                    game.tap(-1)
                elif event.key in (pygame.K_RIGHT, pygame.K_d):
                    game.tap(1)
                elif event.key == pygame.K_UP:
                    level = music_player.change_volume(VOLUME_STEP)
                    volume_hint = (f"MUSIC {round(level * 100)}%",
                                   pygame.time.get_ticks() + 1400)
                elif event.key == pygame.K_DOWN:
                    level = music_player.change_volume(-VOLUME_STEP)
                    volume_hint = (f"MUSIC {round(level * 100)}%",
                                   pygame.time.get_ticks() + 1400)
                elif event.key == pygame.K_KP_PLUS:
                    skip_song(music_player, game)
                    volume_hint = ("NEXT SONG",
                                   pygame.time.get_ticks() + 1400)
                elif event.key == pygame.K_m:
                    if music_player.toggle_mute():
                        volume_hint = ("MUSIC OFF",
                                       pygame.time.get_ticks() + 1400)
                    else:
                        volume_hint = (
                            f"MUSIC {music_player.volume_percent}%",
                            pygame.time.get_ticks() + 1400)

        move, fire_down = read_input()
        fire = fire_down and not fire_was_down  # only listen for fresh presses
        fire_was_down = fire_down

        if game.state == "playing":
            game.update(dt, move, fire)
            if game.wave != last_wave:
                last_wave = game.wave
                music_player.request(game.music_genre,
                                     music_intensity(game.wave))
                music_player.prepare(game.next_music_genre,
                                     music_intensity(game.wave + 1))
        if game.state in ("playing", "gameover"):
            # Keep the death burst animating under the fading game-over card.
            game.update_effects(dt)

        # Duck the soundtrack outside active play and bring it back on resume.
        game.music_enabled = music_player.enabled
        game.music_muted = music_player.muted
        game.music_volume_percent = music_player.volume_percent
        music_player.set_duck(MUSIC_DUCK_LEVELS.get(game.state, 1.0))
        music_player.update(dt)

        # The story was fetched during the run; pin it to this game over and
        # start looking for the next one during the following game.
        if game.state == "gameover" and not story_assigned:
            story_assigned = True
            story = news_feed.take()
            game.story = story
            if story is not None:
                news_feed.advance()

        # Keep the pointer visible outside active play so fullscreen story
        # links can be clicked; hide it only while the game is being played.
        want_cursor = not fullscreen or game.state != "playing"
        if pygame.mouse.get_visible() != want_cursor:
            pygame.mouse.set_visible(want_cursor)

        game.draw(game.canvas)
        now = pygame.time.get_ticks()
        hint = None
        if volume_hint is not None and now < volume_hint[1]:
            hint = volume_hint[0]
        if crt_hint is not None and now < crt_hint[1]:
            hint = crt_hint[0]
        if music_player.muted and game.state not in ("title", "scores"):
            hint = "MUSIC OFF"
        if hint:
            label = game.font_small.render(hint, True, UI_DIM)
            game.canvas.blit(label, (RIGHT_WALL - label.get_width(),
                                     HEIGHT - 19))
        # The NASA story card stays crisp: keep a pre-CRT copy and put it back.
        panel = getattr(game, "story_panel_rect", None)
        clean_panel = None
        if panel is not None and crt.preset != "off" and crt.intensity > 0:
            clean_panel = game.canvas.subsurface(panel).copy()
        crt.apply_inplace(game.canvas, t=pygame.time.get_ticks() / 1000)
        if clean_panel is not None and panel is not None:
            game.canvas.blit(clean_panel, panel.topleft)
        game.present(screen)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
