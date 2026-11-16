"""Playfield, HUD, leaderboard, and overlay rendering."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pygame

from config import (
    ALIEN_BULLET_COLOR,
    ALIEN_H,
    ALIEN_W,
    BG_BOTTOM,
    BG_TOP,
    FIELD_TOP,
    FLOOR_Y,
    HEIGHT,
    LEADERBOARD_ROWS,
    LEFT_WALL,
    PLAYER_BULLET_COLOR,
    PLAYER_COLOR,
    PLAYER_W,
    POPUP_RISE,
    RIGHT_WALL,
    ROW_COLORS,
    SHAKE_DECAY,
    SHAKE_MAX,
    UI_COLOR,
    UI_DIM,
    WIDTH,
)

_ELLIPSIS = "…"


@dataclass(frozen=True)
class AlienLook:
    """One wave's take on the invader silhouette.

    Every field is an index into a small drawing variation, so the whole
    fleet shares a look for the wave while each wave looks a little different.
    """
    antenna: int = 0     # 0 pods, 1 horns, 2 crest, 3 fins
    eyes: int = 0        # 0 squares, 1 visor, 2 dots, 3 mono-eye
    legs: int = 0        # 0 wide, 1 narrow, 2 pointed
    roundness: int = 4   # body corner radius
    stripe: bool = False


DEFAULT_LOOK = AlienLook()
_LOOK_CACHE: dict[int, AlienLook] = {}


def alien_look(wave: int) -> AlienLook:
    """Per-wave look with no feature repeated two waves running.

    Wave 1 is the classic silhouette, and each following wave advances every
    feature independently, so the fleet changes a little every time without
    ever drifting far from a recognizable invader.
    """
    look = _LOOK_CACHE.get(wave)
    if look is None:
        step = wave - 1
        look = AlienLook(
            antenna=step % 4,
            eyes=(step * 3) % 4,
            legs=(step * 2) % 3,
            roundness=(4, 6, 1)[step % 3],
            stripe=step % 5 == 4,
        )
        _LOOK_CACHE[wave] = look
    return look


def wrap_text(font: pygame.font.Font, text: str, width: int,
              max_lines: int) -> list[str]:
    """Greedily wrap *text* into at most *max_lines* lines no wider than
    *width*, measuring with ``font.size``.

    Words longer than the box are split by character so nothing clips.  If
    the content needs more than *max_lines* lines the result is truncated and
    the final line is trimmed and suffixed with an ellipsis.
    """
    words = str(text).split()
    lines: list[str] = []
    line = ""

    def fits(value: str) -> bool:
        return font.size(value)[0] <= width

    for word in words:
        candidate = f"{line} {word}" if line else word
        if fits(candidate):
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        if fits(word):
            line = word
            continue
        # A single word wider than the box: hard-wrap it by character.
        chunk = ""
        for char in word:
            if chunk and not fits(chunk + char):
                lines.append(chunk)
                chunk = ""
            chunk += char
        line = chunk
    if line:
        lines.append(line)

    if len(lines) <= max_lines:
        return lines

    kept = lines[:max_lines]
    last = kept[-1]
    while last and not fits(last + _ELLIPSIS):
        last = last[:-1]
    kept[-1] = last.rstrip() + _ELLIPSIS
    return kept


class RenderMixin:
    # -- screen shake ------------------------------------------------------ #

    def add_shake(self, strength: float) -> None:
        """Kick the screen; overlapping shakes stack up to SHAKE_MAX pixels."""
        self.shake_energy = min(SHAKE_MAX, self.shake_energy + strength)
        # Restart the wave so the kick lands at full displacement this frame
        # instead of starting wherever the previous one happened to be.
        self.shake_phase = 0.0

    def update_feedback(self, dt: float) -> None:
        """Settle shake and score popups even while the sim is paused or over."""
        self.shake_phase += dt
        if self.shake_energy > 0.0:
            self.shake_energy *= math.exp(-dt / SHAKE_DECAY)
            if self.shake_energy < 0.1:
                self.shake_energy = 0.0
        for popup in self.popups:
            popup[1] -= POPUP_RISE * dt
            popup[4] -= dt
        self.popups = [p for p in self.popups if p[4] > 0]

    def shake_offset(self) -> tuple[int, int]:
        """Current whole-canvas offset in pixels, or (0, 0) when settled."""
        amplitude = self.shake_energy * 0.8
        if amplitude < 0.5:
            return 0, 0
        phase = self.shake_phase
        # Two incommensurate frequencies around 9-13 Hz: fast enough to read as
        # a jolt, slow enough that consecutive frames still cohere.
        return (round(math.cos(phase * 57.0) * amplitude),
                round(math.sin(phase * 83.0 + 1.3) * amplitude))

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
            self.draw_popups(surface)
            self.draw_hud(surface)
        self.draw_overlay(surface)

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
        look = alien_look(getattr(self, "wave", 1))
        for a in self.aliens:
            if not a.alive:
                continue
            color = ROW_COLORS[a.row % len(ROW_COLORS)]
            x, y = int(a.x), int(a.y)
            self.draw_alien_sprite(surface, x, y, color, frame, look)

    def draw_alien_sprite(self, surface: pygame.Surface, x: int, y: int,
                          color: tuple[int, int, int], frame: int,
                          look: AlienLook | None = None) -> None:
        look = look or DEFAULT_LOOK
        w, h = ALIEN_W, ALIEN_H
        dark = (20, 20, 35)
        body = pygame.Rect(x + 4, y + 2, w - 8, h - 10)
        pygame.draw.rect(surface, color, body, border_radius=look.roundness)

        # Headgear.
        if look.antenna == 0:      # twin pods
            pygame.draw.rect(surface, color, (x + 2, y, 6, 6), border_radius=2)
            pygame.draw.rect(surface, color, (x + w - 8, y, 6, 6), border_radius=2)
        elif look.antenna == 1:    # swept horns
            pygame.draw.polygon(surface, color,
                                ((x + 5, y + 5), (x + 1, y - 2), (x + 11, y + 1)))
            pygame.draw.polygon(surface, color,
                                ((x + w - 5, y + 5), (x + w - 1, y - 2),
                                 (x + w - 11, y + 1)))
        elif look.antenna == 2:    # single crest
            pygame.draw.rect(surface, color, (x + 12, y - 2, 10, 8),
                             border_radius=4)
        else:                      # side fins
            pygame.draw.rect(surface, color, (x, y + 7, 4, 9), border_radius=1)
            pygame.draw.rect(surface, color, (x + w - 4, y + 7, 4, 9), border_radius=1)

        # Eyes.
        if look.eyes == 0:
            pygame.draw.rect(surface, dark, (x + 10, y + 8, 4, 4))
            pygame.draw.rect(surface, dark, (x + w - 14, y + 8, 4, 4))
        elif look.eyes == 1:       # visor
            pygame.draw.rect(surface, dark, (x + 9, y + 9, w - 18, 3),
                             border_radius=1)
        elif look.eyes == 2:       # round eyes
            pygame.draw.circle(surface, dark, (x + 12, y + 10), 2)
            pygame.draw.circle(surface, dark, (x + w - 12, y + 10), 2)
        else:                      # mono-eye
            pygame.draw.circle(surface, dark, (x + w // 2, y + 10), 4)
            pygame.draw.circle(surface, (240, 245, 255),
                               (x + w // 2 - 1, y + 9), 1)

        if look.stripe:
            stripe = tuple(min(255, int(c + (255 - c) * 0.45)) for c in color)
            pygame.draw.rect(surface, stripe, (x + 6, y + 13, w - 12, 2),
                             border_radius=1)

        # Legs, alternating between two frames.
        if look.legs == 0:
            if frame == 0:
                pygame.draw.rect(surface, color, (x, y + h - 7, 7, 6))
                pygame.draw.rect(surface, color, (x + w - 7, y + h - 7, 7, 6))
            else:
                pygame.draw.rect(surface, color, (x + 6, y + h - 7, 7, 7))
                pygame.draw.rect(surface, color, (x + w - 13, y + h - 7, 7, 7))
        elif look.legs == 1:
            step = 0 if frame == 0 else 3
            pygame.draw.rect(surface, color, (x + 8 + step, y + h - 7, 5, 7))
            pygame.draw.rect(surface, color, (x + w - 13 - step, y + h - 7, 5, 7))
        else:
            step = 0 if frame == 0 else 2
            pygame.draw.polygon(surface, color,
                                ((x + 7, y + h - 8), (x + 3 + step, y + h),
                                 (x + 13, y + h - 8)))
            pygame.draw.polygon(surface, color,
                                ((x + w - 7, y + h - 8),
                                 (x + w - 3 - step, y + h),
                                 (x + w - 13, y + h - 8)))

    def draw_shields(self, surface: pygame.Surface) -> None:
        for s in self.shields:
            s.draw(surface)

    def draw_drifters(self, surface: pygame.Surface) -> None:
        for d in self.drifters:
            fade = getattr(d, "fade", 1.0)
            if fade < 1.0:
                # fade multiplies the sprite's own alpha: copy so the shared
                # alpha-cut image is never modified.
                image = d.image.copy()
                image.set_alpha(max(0, min(255, round(255 * fade))))
                surface.blit(image, (int(d.x), int(d.y)))
            else:
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

    def draw_popups(self, surface: pygame.Surface) -> None:
        """Rising, fading "+points" numbers over where they were earned."""
        for x, y, text, colour, life, total in self.popups:
            fade = max(0.0, min(1.0, life / total))
            label = self.font_tiny.render(text, True, colour)
            # Solid for the first half of its life, then fade away.
            label.set_alpha(int(255 * min(1.0, fade * 2.0)))
            surface.blit(label, (int(x) - label.get_width() // 2, int(y)))

    def draw_hud(self, surface: pygame.Surface) -> None:
        # Live record: follows the running score the moment it passes the board.
        best = max(self.leaderboard.best, self.score)
        best_text = self.font_tiny.render(f"BEST {best:05d}", True, UI_DIM)
        surface.blit(best_text, (LEFT_WALL, 4))
        score = self.font_small.render(f"SCORE {self.score:05d}", True, UI_COLOR)
        wave = self.font_small.render(f"WAVE {self.wave}", True, UI_DIM)
        surface.blit(score, (LEFT_WALL, 24))
        surface.blit(wave, (WIDTH // 2 - wave.get_width() // 2, 24))
        if self.music_genre:
            label = self.font_small.render(
                f"({self.music_genre})", True, (80, 88, 130))
            surface.blit(label, (WIDTH // 2 - label.get_width() // 2, 44))

        # Fleet progress: the whole formation as a dot map, dimmed where the
        # ranks have been thinned out.  8x4 cells of 4px with a 1px gutter fit
        # under the score without reaching the playfield.
        for a in self.aliens:
            cell = 4
            x = LEFT_WALL + a.col * (cell + 1)
            y = 45 + a.row * (cell + 1)
            colour = (ROW_COLORS[a.row % len(ROW_COLORS)] if a.alive
                      else (40, 44, 68))
            pygame.draw.rect(surface, colour, (x, y, cell, 3))

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
            ("RANK", 80),
            ("SCORE", 310),
            ("WAVE", 390),
            ("AVATARS", 480),
            ("BUNKER", 610),
            ("ACCURACY", 740),
        )
        for label, right in columns:
            text = self.font_tiny.render(label, True, (255, 220, 120))
            surface.blit(text, (right - text.get_width(), 112))
        name_head = self.font_tiny.render("NAME", True, (255, 220, 120))
        surface.blit(name_head, (96, 112))
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
                name = str(entry.get("name") or "???")
                name_text = self.font_small.render(name, True, colour)
                surface.blit(name_text, (96, y))
                values = (
                    (f"{rank}", 80),
                    (f"{int(entry['score'])}", 310),
                    (f"{int(entry['wave'])}", 390),
                    (f"{int(entry['avatars'])}", 480),
                    (f"{entry['bunker']:.1f}%", 610),
                    (f"{entry['accuracy']:.1f}%", 740),
                )
                for value, right in values:
                    text = self.font_small.render(value, True, colour)
                    surface.blit(text, (right - text.get_width(), y))

            end = start + len(visible)
            footer = self.font_tiny.render(
                f"SHOWING {start + 1}-{end} OF {len(entries)}", True, UI_DIM)
            surface.blit(footer, (WIDTH // 2 - footer.get_width() // 2, 540))

        armed = (self.clear_armed
                 and pygame.time.get_ticks() < self.clear_hint_until)
        if armed:
            hint = self.font_tiny.render(
                f"ERASE ALL {len(entries)} SCORES?  PRESS DELETE AGAIN",
                True, (255, 120, 140))
        elif entries:
            hint = self.font_tiny.render(
                "UP / DOWN  SCROLL      L / ESC  BACK      DELETE  ERASE ALL",
                True, UI_DIM)
        else:
            hint = self.font_tiny.render("L / ESC  BACK", True, UI_DIM)
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 566))

    def draw_overlay(self, surface: pygame.Surface) -> None:
        # No story card unless draw_gameover_story runs this frame.
        self.story_panel_rect = None
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
                ("CRT", "F3 filter   [ / ] intensity"),
                ("MUSIC", "M  mute   ↑/↓ volume   NUMPAD + next"),
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
            story = getattr(self, "story", None)
            if story is not None:
                self.draw_gameover_story(surface, story)
                return
            # Offline layout has no clickable link.
            self.story_link_rect = None
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

    def draw_gameover_story(self, surface: pygame.Surface, story) -> None:
        """Game-over screen with the NASA story card alongside all stats."""
        stats = self.run_stats()

        title = self.font_big.render("GAME OVER", True, (255, 110, 130))
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 68))

        score = self.font_mid.render(
            f"Score {self.score}   Wave {self.wave}", True, UI_COLOR)
        surface.blit(score, (WIDTH // 2 - score.get_width() // 2, 128))

        line = self.font_small.render(
            f"AVATARS KILLED {stats['avatars']}    "
            f"BUNKERS SHOT {stats['bunker']:.1f}%    "
            f"ACCURACY {stats['accuracy']:.1f}%", True, UI_COLOR)
        surface.blit(line, (WIDTH // 2 - line.get_width() // 2, 160))

        if self.last_rank is not None:
            rank = self.font_mid.render(
                f"NEW HIGH SCORE  #{self.last_rank}", True, (255, 225, 120))
            surface.blit(rank, (WIDTH // 2 - rank.get_width() // 2, 186))
        else:
            rank = self.font_small.render(
                "DID NOT MAKE THE TOP 100", True, UI_DIM)
            surface.blit(rank, (WIDTH // 2 - rank.get_width() // 2, 190))

        panel = pygame.Rect(34, 222, 732, 288)
        # Marks the NASA story panel that the CRT pass leaves unfiltered.
        self.story_panel_rect = panel
        pygame.draw.rect(surface, (14, 18, 38), panel, border_radius=10)
        pygame.draw.rect(surface, (46, 54, 92), panel, width=1, border_radius=10)

        box = pygame.Rect(48, 234, 320, 180)
        image = getattr(story, "image", None)
        if image is not None:
            surface.blit(image, box.topleft)
        else:
            pygame.draw.rect(surface, (24, 28, 52), box)
            nasa = self.font_mid.render("NASA", True, UI_DIM)
            surface.blit(nasa, (box.centerx - nasa.get_width() // 2,
                                box.centery - nasa.get_height() // 2))
        pygame.draw.rect(surface, (60, 70, 110), box, width=1)

        heading_lines = wrap_text(self.font_small, story.title, 368, 3)
        for i, text in enumerate(heading_lines):
            label = self.font_small.render(text, True, (255, 225, 140))
            surface.blit(label, (384, 234 + i * 22))

        summary_y = 234 + len(heading_lines) * 22 + 16
        # Leave room for the attribution (460) and link (482) rows.
        max_lines = max(0, (452 - summary_y) // 17)
        for i, text in enumerate(wrap_text(
                self.font_tiny, story.summary, 368, max_lines)):
            label = self.font_tiny.render(text, True, UI_COLOR)
            surface.blit(label, (384, summary_y + i * 17))

        kind = getattr(story, "kind", "")
        read_time = getattr(story, "read_time", "")
        attribution = "NASA"
        if kind:
            attribution += f" · {kind}"
        if read_time:
            attribution += f" · {read_time}"
        label = self.font_tiny.render(attribution, True, UI_DIM)
        surface.blit(label, (48, 460))

        link = getattr(story, "link", "") or ""
        if link:
            click = self.font_tiny.render("click to open", True, UI_DIM)
            surface.blit(click, (752 - click.get_width(), 460))

        text = link
        if text.startswith("https://"):
            text = text[len("https://"):]
        elif text.startswith("http://"):
            text = text[len("http://"):]
        lines = wrap_text(self.font_tiny, text, 704, 1)
        text = lines[0] if lines else ""
        if text:
            label = self.font_tiny.render(text, True, (130, 200, 255))
            surface.blit(label, (48, 482))
            text_width = label.get_width()
            pygame.draw.line(surface, (90, 130, 170),
                             (48, 498), (48 + text_width, 498), 1)
            self.story_link_rect = pygame.Rect(48, 482, text_width, 17)
        else:
            self.story_link_rect = None

        hint = self.font_small.render(
            "press ENTER to play again", True, (255, 220, 120))
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 522))
        scores_hint = self.font_small.render(
            "press L for high scores", True, UI_DIM)
        surface.blit(scores_hint,
                     (WIDTH // 2 - scores_hint.get_width() // 2, 546))

    def canvas_point(self, window_size, pos):
        """Map a window pixel back onto the 800x600 canvas."""
        sw, sh = window_size
        if (sw, sh) == (WIDTH, HEIGHT):
            return pos
        scale = min(sw / WIDTH, sh / HEIGHT)
        w = max(1, int(WIDTH * scale))
        h = max(1, int(HEIGHT * scale))
        ox = (sw - w) // 2
        oy = (sh - h) // 2
        return ((pos[0] - ox) / scale, (pos[1] - oy) / scale)
