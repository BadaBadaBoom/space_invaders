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
    BOSS_COLOR,
    BOSS_DARK,
    BOSS_EVERY,
    BOSS_H,
    BOSS_LIGHT,
    BOSS_W,
    COLS,
    COMBO_WINDOW,
    COVER_FADE_TIME,
    DASH_COOLDOWN,
    DASH_TIME,
    FIELD_TOP,
    FLOOR_Y,
    GAMEOVER_FADE,
    HEIGHT,
    HURT_FLASH_TIME,
    LEADERBOARD_ROWS,
    LEFT_WALL,
    MUZZLE_FLASH_TIME,
    PLAYER_BULLET_COLOR,
    PLAYER_COLOR,
    PLAYER_H,
    PLAYER_W,
    POPUP_RISE,
    POWERUP_COLORS,
    POWERUP_LABELS,
    POWERUP_RAPID_TIME,
    POWERUP_SIZE,
    POWERUP_TRIPLE_TIME,
    RECORD_BANNER_SCROLL,
    RECORD_BANNER_TIME,
    RIGHT_WALL,
    ROW_COLORS,
    SHIELD_TOP_COLOR,
    SHAKE_BANNER,
    SHAKE_DECAY,
    SHAKE_MAX,
    UFO_COLOR,
    UFO_H,
    UFO_LIGHT,
    UFO_W,
    UI_COLOR,
    UI_DIM,
    UI_RECORD,
    WIDTH,
)
from entities import Alien

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
    # -- backdrop transitions --------------------------------------------- #

    def adopt_cover(self, new_bg: pygame.Surface) -> None:
        """Swap in a prefetched cover with a crossfade from the old one."""
        if new_bg is None:
            return
        if self.pulp_bg is not None and new_bg is not self.pulp_bg:
            self._bg_prev = self.pulp_bg
            self._bg_fade = 0.0
        self.pulp_bg = new_bg

    # -- screen shake ------------------------------------------------------ #

    def add_shake(self, strength: float) -> None:
        """Kick the screen; overlapping shakes stack up to SHAKE_MAX pixels."""
        self.shake_energy = min(SHAKE_MAX, self.shake_energy + strength)
        # Restart the wave so the kick lands at full displacement this frame
        # instead of starting wherever the previous one happened to be.
        self.shake_phase = 0.0

    def update_feedback(self, dt: float) -> None:
        """Settle shake and score popups even while the sim is paused or over."""
        # If the current wave's cover was not ready at spawn_wave(), adopt it
        # as soon as it lands.  Only one adoption per wave: take() starts the
        # next wave's render, which must not be consumed until that wave begins.
        prefetcher = getattr(self, "cover_prefetcher", None)
        if prefetcher is not None and getattr(self, "cover_pending", False):
            new_bg = prefetcher.take(block=False)
            if new_bg is not None:
                self.adopt_cover(new_bg)
                self.cover_pending = False
        if getattr(self, "_bg_prev", None) is not None:
            self._bg_fade = min(1.0, getattr(self, "_bg_fade", 1.0)
                                + dt / COVER_FADE_TIME)
            if self._bg_fade >= 1.0:
                self._bg_prev = None
        self.shake_phase += dt
        if self.shake_energy > 0.0:
            self.shake_energy *= math.exp(-dt / SHAKE_DECAY)
            if self.shake_energy < 0.1:
                self.shake_energy = 0.0
        for popup in self.popups:
            popup[1] -= POPUP_RISE * dt
            popup[4] -= dt
        self.popups = [p for p in self.popups if p[4] > 0]
        self.record_banner_time = max(0.0, self.record_banner_time - dt)
        if self.record_banner_time > 0:
            # Keep the view jolting for the whole marquee, not just the hit.
            self.shake_energy = max(self.shake_energy, SHAKE_BANNER)
        self.hurt_flash = max(0.0, getattr(self, "hurt_flash", 0.0) - dt)
        if self.state == "gameover":
            self.game_over_time = min(GAMEOVER_FADE,
                                      getattr(self, "game_over_time", 0.0) + dt)
        else:
            self.game_over_time = 0.0
        if self.state == "playing" and self.wave_intro_time > 0:
            self.wave_intro_time = max(0.0, self.wave_intro_time - dt)
            if self.wave_intro_time == 0 and self.wave_intro_bonus:
                self.spawn_popup(WIDTH / 2, HEIGHT / 2 + 74,
                                 f"+{self.wave_intro_bonus}",
                                 (255, 220, 120))
                self.wave_intro_bonus = 0

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

    def draw_hurt_flash(self, surface: pygame.Surface) -> None:
        """A red edge pulse after the ship is hit, strongest at impact."""
        strength = getattr(self, "hurt_flash", 0.0) / HURT_FLASH_TIME
        if strength <= 0.0:
            return
        vignette = getattr(self, "_hurt_vignette", None)
        if vignette is None:
            vignette = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            depth = 42
            for i in range(depth):
                alpha = int(96 * (1.0 - i / depth) ** 2)
                if alpha <= 0:
                    continue
                pygame.draw.rect(vignette, (255, 38, 72, alpha),
                                 (i, i, WIDTH - i * 2, HEIGHT - i * 2),
                                 width=1)
            self._hurt_vignette = vignette
        vignette.set_alpha(int(255 * min(1.0, strength)))
        surface.blit(vignette, (0, 0))
        vignette.set_alpha(255)

    def draw_wave_intro(self, surface: pygame.Surface) -> None:
        """A short card between waves, also acting as the boss warning."""
        if self.state != "playing":
            return
        remaining = getattr(self, "wave_intro_time", 0.0)
        total = getattr(self, "wave_intro_total", 0.0)
        if remaining <= 0 or total <= 0:
            return
        elapsed = total - remaining
        fade = min(1.0, elapsed / 0.16, remaining / 0.24)
        alpha = int(255 * max(0.0, fade))
        band_h = 96
        top = HEIGHT // 2 - band_h // 2
        band = pygame.Surface((WIDTH, band_h), pygame.SRCALPHA)
        band.fill((8, 10, 24, int(190 * fade)))
        surface.blit(band, (0, top))

        boss = getattr(self, "wave_intro_boss", False)
        accent = (255, 120, 150) if boss else (255, 220, 120)
        line = pygame.Surface((WIDTH, 2), pygame.SRCALPHA)
        line.fill((*accent, int(180 * fade)))
        surface.blit(line, (0, top))
        surface.blit(line, (0, top + band_h - 2))

        title = self.font_big.render(self.wave_intro_title, True,
                                     (255, 255, 255) if not boss else accent)
        title.set_alpha(alpha)
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2,
                             top + 14))
        subtitle = self.font_small.render(self.wave_intro_subtitle, True,
                                          accent)
        subtitle.set_alpha(alpha)
        surface.blit(subtitle, (WIDTH // 2 - subtitle.get_width() // 2,
                                top + 68))

    def draw(self, surface: pygame.Surface) -> None:
        self.draw_background(surface)
        self.draw_walls(surface)
        if self.state not in ("title", "scores"):
            self.draw_aliens(surface)
            self.draw_ufo(surface)
            self.draw_boss(surface)
            self.draw_shields(surface)
            self.draw_drifters(surface)
            self.draw_bullets(surface)
            self.draw_powerups(surface)
            self.draw_player(surface)
            self.draw_debris(surface)
            self.draw_popups(surface)
            self.draw_hud(surface)
        self.draw_hurt_flash(surface)
        self.draw_overlay(surface)
        self.draw_wave_intro(surface)
        self.draw_record_banner(surface)

    def draw_background(self, surface: pygame.Surface) -> None:
        for y in range(0, HEIGHT, 6):
            t = y / HEIGHT
            color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
            pygame.draw.rect(surface, color, (0, y, WIDTH, 6))
        if self.pulp_bg is not None:
            previous = getattr(self, "_bg_prev", None)
            if previous is not None and getattr(self, "_bg_fade", 1.0) < 1.0:
                surface.blit(previous, (0, 0))
                cover = self.pulp_bg
                base_alpha = cover.get_alpha()
                if base_alpha is None:
                    base_alpha = 255
                cover.set_alpha(int(base_alpha * self._bg_fade))
                surface.blit(cover, (0, 0))
                cover.set_alpha(base_alpha)
            else:
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
            if a.diving:
                self.draw_dive_flame(surface, a, x, y)
            self.draw_alien_sprite(surface, x, y, color, frame, look)

    def draw_dive_flame(self, surface: pygame.Surface, alien: Alien,
                        x: int, y: int) -> None:
        """A layered exhaust plume streaming out behind a dive-bomber."""
        speed = math.hypot(alien.vx, alien.vy)
        if speed < 1e-3:
            return
        dx, dy = alien.vx / speed, alien.vy / speed
        px, py = -dy, dx
        cx = x + ALIEN_W / 2
        cy = y + ALIEN_H / 2
        # Leave from the tail rather than the middle of the sprite.
        bx = cx - dx * ALIEN_H * 0.45
        by = cy - dy * ALIEN_H * 0.45
        tick = pygame.time.get_ticks() * 0.02
        flicker = 0.88 + 0.12 * math.sin(tick + alien.x)
        sway = math.sin(tick * 1.7 + alien.y) * 2.2

        length = 24.0 + speed * 0.055
        layers = (
            (1.00, 8.0, (255, 108, 40)),
            (0.68, 5.5, (255, 176, 72)),
            (0.38, 3.0, (255, 242, 190)),
        )
        for scale, half, colour in layers:
            reach = length * flicker * scale
            tip_x = bx - dx * reach + px * sway
            tip_y = by - dy * reach + py * sway
            mid_x = bx - dx * reach * 0.45
            mid_y = by - dy * reach * 0.45
            wing = half * 1.3
            pygame.draw.polygon(surface, colour, (
                (int(bx + px * half), int(by + py * half)),
                (int(mid_x + px * wing), int(mid_y + py * wing)),
                (int(tip_x), int(tip_y)),
                (int(mid_x - px * wing), int(mid_y - py * wing)),
                (int(bx - px * half), int(by - py * half)),
            ))

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

    def draw_ufo(self, surface: pygame.Surface) -> None:
        ufo = self.ufo
        if ufo is None:
            return
        x = int(ufo.x)
        tick = pygame.time.get_ticks()
        y = int(ufo.y) + int(math.sin(tick / 240.0) * 1.5)
        w, h = UFO_W, UFO_H
        cx = x + w // 2

        pygame.draw.ellipse(surface, UFO_COLOR, (x, y + 5, w, h - 5))
        pygame.draw.ellipse(surface, (110, 130, 170), (x, y + 5, w, h - 5), 1)
        pygame.draw.ellipse(surface, (150, 194, 236), (cx - 10, y, 20, 11))
        pygame.draw.ellipse(surface, (78, 118, 168), (cx - 10, y, 20, 11), 1)

        # Running lights blinking in sequence.
        for i in range(4):
            lx = x + 7 + i * (w - 14) // 3
            lit = (tick // 130 + i) % 3 != 0
            pygame.draw.circle(surface, UFO_LIGHT if lit else (96, 70, 52),
                               (lx, y + h - 4), 2)

    def draw_boss(self, surface: pygame.Surface) -> None:
        """The wide wave boss, with a segmented health bar above it."""
        boss = self.boss
        if boss is None:
            return
        x, y = int(boss.x), int(boss.y)
        w, h = BOSS_W, BOSS_H
        flash = self.boss_flash > 0
        enraged = getattr(self, "boss_raged", False)
        if flash:
            hull = dark = rim = light = (255, 255, 255)
        elif enraged:
            # Overdrive repaints the hull in warning reds.
            hull = (255, 96, 118)
            dark = (76, 20, 38)
            rim = (255, 176, 128)
            light = (255, 238, 176)
        else:
            hull = BOSS_COLOR
            dark = BOSS_DARK
            rim = (170, 110, 150)
            light = BOSS_LIGHT

        pulse = 0.5 + 0.5 * math.sin(
            pygame.time.get_ticks() / (150.0 if enraged else 330.0))
        glow_colour = (255, 84, 112) if enraged else BOSS_COLOR
        glow = pygame.Surface((w + 40, h + 40), pygame.SRCALPHA)
        pygame.draw.ellipse(
            glow, (*glow_colour, int((26 if not enraged else 18) + 18 * pulse)),
            glow.get_rect())
        surface.blit(glow, (x - 20, y - 20))

        # Engine pods either side of the hull.
        pod_y = y + int(h * 0.42)
        pygame.draw.ellipse(surface, dark, (x - 8, pod_y, 32, 24))
        pygame.draw.ellipse(surface, dark, (x + w - 24, pod_y, 32, 24))
        for px in (x + 1, x + w - 27):
            pygame.draw.rect(surface, light, (px, pod_y + 14, 12, 4),
                             border_radius=2)

        # Wide hexagonal hull.
        hull_pts = [
            (x + 12, y + int(h * 0.46)),
            (x + int(w * 0.22), y + int(h * 0.16)),
            (x + int(w * 0.78), y + int(h * 0.16)),
            (x + w - 12, y + int(h * 0.46)),
            (x + int(w * 0.72), y + int(h * 0.88)),
            (x + int(w * 0.28), y + int(h * 0.88)),
        ]
        pygame.draw.polygon(surface, hull, hull_pts)
        pygame.draw.polygon(surface, rim, hull_pts, 2)

        # Cockpit dome with a row of eyes.
        dome = pygame.Rect(x + int(w * 0.26), y + 2, int(w * 0.48),
                           int(h * 0.42))
        pygame.draw.ellipse(surface, dark, dome)
        pygame.draw.arc(surface, rim, dome, math.radians(190),
                        math.radians(350), 2)
        for ex in (-18, 0, 18):
            pygame.draw.circle(surface, light,
                               (x + w // 2 + ex, y + int(h * 0.24)), 4)

        # Vent grille and hull lights.
        for i in range(5):
            vx = x + int(w * 0.34) + i * 12
            pygame.draw.rect(surface, dark, (vx, y + int(h * 0.62), 7, 10),
                             border_radius=2)
        for i in range(4):
            lx = x + int(w * 0.16) + i * int(w * 0.22)
            pygame.draw.circle(surface, light, (lx, y + int(h * 0.44)), 2)

        # Segmented health bar, kept above the hull.  It stays hidden while
        # the ship is still sliding into the arena, and a pale ghost segment
        # drains a beat behind the real bar.
        if getattr(self, "boss_entry", 0.0) > 0:
            return
        bar = pygame.Rect(x, y - 14, w, 7)
        pygame.draw.rect(surface, (26, 18, 36), bar, border_radius=3)
        fraction = max(0.0, boss.hp / boss.max_hp)
        ghost = getattr(self, "boss_ghost_hp", boss.hp)
        ghost_fraction = max(fraction, min(1.0, ghost / boss.max_hp))
        if ghost_fraction > fraction:
            ghost_fill = pygame.Rect(
                bar.x + 1, bar.y + 1,
                max(1, int((bar.w - 2) * ghost_fraction)), bar.h - 2)
            pygame.draw.rect(surface, (132, 66, 84), ghost_fill,
                             border_radius=2)
        if fraction > 0:
            if enraged or fraction < 0.35:
                colour = (255, 110, 130)
            else:
                colour = (255, 205, 90)
            fill = pygame.Rect(bar.x + 1, bar.y + 1,
                               max(1, int((bar.w - 2) * fraction)), bar.h - 2)
            pygame.draw.rect(surface, colour, fill, border_radius=2)
        for i in range(1, 10):
            tx = bar.x + bar.w * i // 10
            pygame.draw.line(surface, (26, 18, 36), (tx, bar.y + 1),
                             (tx, bar.y + bar.h - 2), 1)
        pygame.draw.rect(surface, (110, 80, 130), bar, width=1,
                         border_radius=3)

        # Nameplate: which sentinel this is, and when it is angry.
        tier = max(1, self.wave // BOSS_EVERY)
        tag = f"SENTINEL {tier}"
        if enraged:
            tag += "  //  OVERDRIVE"
        colour = (255, 150, 168) if enraged else (255, 196, 214)
        label = self.font_tiny.render(tag, True, colour)
        surface.blit(label, (x + w // 2 - label.get_width() // 2,
                             bar.y - label.get_height() - 3))

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

    def draw_powerups(self, surface: pygame.Surface) -> None:
        tick = pygame.time.get_ticks()
        for powerup in self.powerups:
            colour = POWERUP_COLORS.get(powerup.kind, (255, 255, 255))
            bob = int(math.sin(tick / 170.0 + powerup.x * 0.05) * 1.5)
            rect = pygame.Rect(int(powerup.x), int(powerup.y) + bob,
                               POWERUP_SIZE, POWERUP_SIZE)
            glow = pygame.Surface((rect.w + 12, rect.h + 12), pygame.SRCALPHA)
            pygame.draw.rect(glow, (*colour, 50), glow.get_rect(),
                             border_radius=10)
            surface.blit(glow, (rect.x - 6, rect.y - 6))
            pygame.draw.rect(surface, colour, rect, border_radius=5)
            pygame.draw.rect(surface, (18, 20, 34), rect, width=2,
                             border_radius=5)
            label = self.font_tiny.render(POWERUP_LABELS[powerup.kind],
                                          True, (18, 20, 34))
            surface.blit(label, (rect.centerx - label.get_width() // 2,
                                 rect.centery - label.get_height() // 2))

    def draw_ship(self, surface: pygame.Surface, x: int, y: int,
                  colour: tuple[int, int, int], lean: int = 0) -> None:
        # Twin engine flames flicker behind the hull.
        tick = pygame.time.get_ticks()
        for nx, phase in ((x + 14, 0.0), (x + 31, 1.7)):
            length = 7 + int(4 * (0.5 + 0.5 * math.sin(
                tick / 34.0 + phase + nx * 0.05)))
            pygame.draw.polygon(surface, (255, 132, 54), (
                (nx - 4, y + PLAYER_H - 3), (nx + 4, y + PLAYER_H - 3),
                (nx, y + PLAYER_H + length)))
            pygame.draw.polygon(surface, (255, 232, 170), (
                (nx - 2, y + PLAYER_H - 3), (nx + 2, y + PLAYER_H - 3),
                (nx, y + PLAYER_H + length * 2 // 3)))
        # A small lean makes the ship read as moving without rotating the
        # collision box.
        pygame.draw.rect(surface, colour, (x + 16 + lean, y, 14, 6),
                         border_radius=2)
        pygame.draw.rect(surface, colour, (x + 4 + lean // 2, y + 6,
                                           PLAYER_W - 8, 6))
        pygame.draw.rect(surface, colour, (x, y + 12, PLAYER_W, 6),
                         border_radius=3)
        pygame.draw.rect(surface, (10, 30, 22),
                         (x + 20 + lean, y + 2, 6, 4))

    def draw_muzzle_flash(self, surface: pygame.Surface, x: int, y: int,
                          lean: int = 0) -> None:
        """A brief pale cone above the nose when a shot leaves the ship."""
        mx = x + PLAYER_W // 2 + lean
        pygame.draw.polygon(surface, (255, 244, 190), (
            (mx - 4, y - 1), (mx + 4, y - 1), (mx, y - 13)))
        pygame.draw.circle(surface, (255, 255, 230), (mx, y - 3), 2)

    def draw_dash_shield(self, surface: pygame.Surface, x: int, y: int) -> None:
        """A glowing bubble around the ship during the invulnerable burst."""
        pulse = max(0.0, min(1.0, self.player.dash_time / DASH_TIME))
        w, h = PLAYER_W + 16, PLAYER_H + 18
        shield = pygame.Surface((w + 24, h + 24), pygame.SRCALPHA)
        cx, cy = shield.get_width() // 2, shield.get_height() // 2
        strength = 0.45 + 0.55 * pulse
        for grow, alpha in ((10, 26), (6, 44), (2, 78)):
            pygame.draw.ellipse(
                shield, (140, 240, 255, int(alpha * strength)),
                (cx - w // 2 - grow, cy - h // 2 - grow,
                 w + grow * 2, h + grow * 2))
        pygame.draw.ellipse(shield, (225, 255, 255, int(210 * pulse)),
                            (cx - w // 2, cy - h // 2, w, h), 2)
        surface.blit(shield, (x + PLAYER_W // 2 - cx,
                              y + PLAYER_H // 2 - cy))

    def draw_player(self, surface: pygame.Surface) -> None:
        p = self.player
        x, y = int(p.x), int(p.y)
        if p.dash_time > 0:
            self.draw_dash_shield(surface, x, y)
        if p.invulnerable > 0 and int(p.invulnerable * 12) % 2 == 0:
            return
        lean = p.move_dir * (4 if p.dash_time > 0 else 3)
        recoil = 1 if p.muzzle > MUZZLE_FLASH_TIME * 0.5 else 0
        if p.dash_time > 0 and p.dash_dir:
            # Warp trail behind the burst.
            for step, ghost in ((1, (86, 170, 124)), (2, (44, 92, 68))):
                self.draw_ship(surface, x - p.dash_dir * step * 18, y,
                               ghost, lean)
        self.draw_ship(surface, x, y + recoil, PLAYER_COLOR, lean)
        if p.muzzle > 0:
            self.draw_muzzle_flash(surface, x, y + recoil, lean)

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
        best_text = self.font_small.render(
            f"BEST {best:05d}", True, UI_RECORD)
        score_text = self.font_small.render(
            f"SCORE {self.score:05d}", True, UI_COLOR)

        # A small dark plate with a light rim sits behind the two live numbers
        # so they stay readable over any cover art.  Their widths are fixed
        # (five digits), so the plate can be built once and reused.
        plate_w = max(best_text.get_width(), score_text.get_width()) + 16
        if getattr(self, "_hud_plate_w", None) != plate_w:
            plate = pygame.Surface((plate_w, 44), pygame.SRCALPHA)
            pygame.draw.rect(plate, (6, 8, 18, 170),
                             (0, 0, plate_w, 44), border_radius=7)
            pygame.draw.rect(plate, (170, 190, 245, 70),
                             (0, 0, plate_w, 44), width=1, border_radius=7)
            pygame.draw.line(plate, (210, 225, 255, 45), (8, 1),
                             (plate_w - 8, 1), 1)
            self._hud_plate = plate
            self._hud_plate_w = plate_w
        surface.blit(self._hud_plate, (LEFT_WALL - 8, 0))

        # A 1px shadow on top of the plate keeps the glyph edges crisp.
        best_shadow = self.font_small.render(
            f"BEST {best:05d}", True, (10, 10, 20))
        score_shadow = self.font_small.render(
            f"SCORE {self.score:05d}", True, (10, 10, 20))
        surface.blit(best_shadow, (LEFT_WALL + 1, 2))
        surface.blit(best_text, (LEFT_WALL, 1))
        surface.blit(score_shadow, (LEFT_WALL + 1, 24))
        surface.blit(score_text, (LEFT_WALL, 23))
        wave = self.font_small.render(f"WAVE {self.wave}", True, UI_DIM)
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

        # Dash readiness: four chevrons fill back up as the burst recharges.
        if self.player.dash_time > 0:
            charge = 1.0
        elif self.player.dash_cooldown > 0:
            charge = 1.0 - self.player.dash_cooldown / DASH_COOLDOWN
        else:
            charge = 1.0
        filled = int(math.ceil(charge * 4))
        ready = charge >= 1.0
        pulse = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 190.0)
        for i in range(4):
            x0 = 92 + i * 7
            if i < filled:
                shade = PLAYER_COLOR
                if ready:
                    shade = tuple(int(c * (0.78 + 0.22 * pulse))
                                  for c in PLAYER_COLOR)
            else:
                shade = (44, 50, 78)
            pygame.draw.polygon(surface, shade,
                                ((x0, 48), (x0 + 5, 53), (x0, 58)))

        # Kill chain: how many kills landed inside the chain window.
        if self.combo > 1 and self.combo_time > 0:
            fading = self.combo_time < 0.3
            if fading and int(self.combo_time * 30) % 2:
                chain_colour = (255, 120, 140)
            else:
                chain_colour = (255, 220, 120)
            chain = self.font_tiny.render(f"CHAIN {self.combo}", True,
                                          chain_colour)
            surface.blit(chain, (132, 43))
            track = pygame.Rect(132, 59, chain.get_width(), 3)
            pygame.draw.rect(surface, (42, 38, 54), track)
            fill = pygame.Rect(track.x, track.y,
                               max(1, int(track.w * self.combo_time
                                          / COMBO_WINDOW)), 3)
            pygame.draw.rect(surface, chain_colour, fill)

        # lives as tiny ships, right-aligned
        for i in range(max(0, self.lives)):
            x = RIGHT_WALL - 26 * (i + 1)
            pygame.draw.rect(surface, PLAYER_COLOR, (x, 28, 20, 4), border_radius=2)
            pygame.draw.rect(surface, PLAYER_COLOR, (x + 4, 24, 12, 4), border_radius=2)
        # The slot that was just lost flashes red for a beat.
        if self.hurt_flash > 0 and int(self.hurt_flash * 24) % 2 == 0:
            x = RIGHT_WALL - 26 * (max(0, self.lives) + 1)
            pygame.draw.rect(surface, (255, 80, 105), (x, 28, 20, 4),
                             border_radius=2)
            pygame.draw.rect(surface, (255, 80, 105), (x + 4, 24, 12, 4),
                             border_radius=2)

        # Active boosts as small draining bars, right-aligned under the lives.
        boosts = []
        if self.player.rapid > 0:
            boosts.append(("RAPID", self.player.rapid,
                           POWERUP_RAPID_TIME, (255, 205, 90)))
        if self.player.triple > 0:
            boosts.append(("TRIPLE", self.player.triple,
                           POWERUP_TRIPLE_TIME, (120, 220, 255)))
        if boosts:
            x = RIGHT_WALL
            for name, remaining, duration, colour in reversed(boosts):
                label = self.font_tiny.render(name, True, colour)
                bar_w = 44
                total = label.get_width() + 6 + bar_w
                x -= total
                if remaining < 2.0 and int(remaining * 8) % 2 == 0:
                    colour = (255, 110, 120)
                text = self.font_tiny.render(name, True, colour)
                surface.blit(text, (x, 42))
                track = pygame.Rect(x + label.get_width() + 6, 48, bar_w, 6)
                pygame.draw.rect(surface, (38, 40, 60), track,
                                 border_radius=3)
                fill = pygame.Rect(track.x, track.y,
                                   max(1, int(track.w * min(1.0, remaining
                                       / max(0.001, duration)))), track.h)
                pygame.draw.rect(surface, colour, fill, border_radius=3)
                pygame.draw.rect(surface, (12, 14, 24), track, width=1,
                                 border_radius=3)
                x -= 12

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
                if not highlighted and offset % 2:
                    surface.fill((16, 20, 38), (44, y - 2, 712, 22))
                if highlighted:
                    surface.fill((45, 42, 34), (44, y - 2, 712, 22))
                colour = rank_colors.get(rank, UI_COLOR)
                if highlighted:
                    colour = (255, 230, 140)
                name = str(entry.get("name") or "???")
                name_text = self.font_small.render(name, True, colour)
                surface.blit(name_text, (96, y))
                if highlighted:
                    tag = self.font_tiny.render("NEW", True, (255, 225, 120))
                    surface.blit(tag, (96 + name_text.get_width() + 7, y + 2))
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

            # Scrollbar shows where the visible window sits in the full table.
            if len(entries) > LEADERBOARD_ROWS:
                track = pygame.Rect(772, 148, 4, LEADERBOARD_ROWS * 25 - 4)
                pygame.draw.rect(surface, (38, 42, 70), track, border_radius=2)
                span = LEADERBOARD_ROWS / len(entries)
                thumb_h = max(22, int(track.height * span))
                travel = max(0, track.height - thumb_h)
                offset = (self.score_scroll
                          / max(1, len(entries) - LEADERBOARD_ROWS))
                thumb = pygame.Rect(track.x, track.y + int(travel * offset),
                                    track.w, thumb_h)
                pygame.draw.rect(surface, (150, 170, 230), thumb,
                                 border_radius=2)

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
        # No story card unless the game-over layer draws one this frame.
        self.story_panel_rect = None
        if self.state == "playing":
            return
        if self.state == "gameover":
            self.draw_gameover_overlay(surface)
            return
        shade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        shade.fill((6, 8, 20, 220 if self.state == "scores" else 190))
        surface.blit(shade, (0, 0))

        if self.state == "scores":
            self.draw_leaderboard(surface)
        elif self.state == "title":
            self.draw_title_attract(surface)
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
            self.draw_pause_screen(surface)

    def draw_title_attract(self, surface: pygame.Surface) -> None:
        """A quiet marching fleet and the occasional saucer behind the title."""
        tick = pygame.time.get_ticks() / 1000.0
        spacing = 39
        width = COLS * ALIEN_W + (COLS - 1) * (spacing - ALIEN_W)
        margin = LEFT_WALL + 16
        travel = max(0, WIDTH - margin * 2 - width)
        base = margin + (0.5 + 0.5 * math.sin(tick * 0.34)) * travel
        frame = int(tick * 3.2) % 2
        look = alien_look(1)
        for i in range(COLS):
            x = int(base + i * spacing)
            y = int(104 + math.sin(tick * 2.1 + i * 0.55) * 2)
            colour = tuple(int(c * 0.58) for c in ROW_COLORS[i % len(ROW_COLORS)])
            self.draw_alien_sprite(surface, x, y, colour, frame, look)

        cycle = tick % 13.0
        if cycle < 3.0:
            progress = cycle / 3.0
            x = int(-40 + progress * (WIDTH + 80))
            y = 74 + int(math.sin(tick * 3.0) * 2)
            pygame.draw.ellipse(surface, (92, 104, 138), (x, y + 3, 32, 9))
            pygame.draw.ellipse(surface, (142, 160, 196), (x + 8, y, 16, 7))
            pygame.draw.circle(surface, (255, 118, 76), (x + 16, y + 9), 2)

    def draw_pause_screen(self, surface: pygame.Surface) -> None:
        """Pause doubles as a run summary and a quiet controls reminder."""
        title = self.font_big.render("PAUSED", True, UI_COLOR)
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 108))
        resume = self.font_small.render("press P to resume", True, UI_DIM)
        surface.blit(resume, (WIDTH // 2 - resume.get_width() // 2, 174))

        panel = pygame.Rect(96, 210, 608, 272)
        pygame.draw.rect(surface, (10, 13, 30), panel, border_radius=10)
        pygame.draw.rect(surface, (70, 80, 130), panel, width=1,
                         border_radius=10)
        stats = self.run_stats()
        line = self.font_mid.render(
            f"SCORE {self.score:05d}    WAVE {self.wave}    LIVES {self.lives}",
            True, UI_COLOR)
        surface.blit(line, (WIDTH // 2 - line.get_width() // 2, 230))
        detail = self.font_small.render(
            f"ACCURACY {stats['accuracy']:.1f}%    "
            f"BUNKERS SHOT {stats['bunker']:.1f}%    "
            f"AVATARS {stats['avatars']}", True, UI_DIM)
        surface.blit(detail, (WIDTH // 2 - detail.get_width() // 2, 272))
        pygame.draw.line(surface, (48, 56, 96), (128, 302), (672, 302), 1)

        controls = (
            "MOVE  ARROWS / A-D      FIRE  SPACE      DASH  DOUBLE-TAP",
            "PAUSE  P      SCORES  L      MUSIC  M      CRT  F3      FULLSCREEN  F11",
        )
        for i, text in enumerate(controls):
            label = self.font_tiny.render(text, True, (255, 220, 120))
            surface.blit(label, (WIDTH // 2 - label.get_width() // 2,
                                 322 + i * 28))

        genre = (self.music_genre or "").upper()
        if not genre or not getattr(self, "music_enabled", True):
            music = "MUSIC OFF"
        elif getattr(self, "music_muted", False):
            music = f"TRACK  {genre}    MUSIC OFF"
        else:
            music = (f"TRACK  {genre}    "
                     f"MUSIC {getattr(self, 'music_volume_percent', 0)}%")
        track = self.font_small.render(music, True, (120, 200, 255))
        surface.blit(track, (WIDTH // 2 - track.get_width() // 2, 404))

        hint = self.font_tiny.render(
            "L  high scores      P  resume      ESC  leave fullscreen",
            True, UI_DIM)
        surface.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 446))

    def draw_gameover_overlay(self, surface: pygame.Surface) -> None:
        """Fade the game-over card in over the death explosion."""
        fade = min(1.0, getattr(self, "game_over_time", 0.0) / GAMEOVER_FADE)
        layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        layer.fill((6, 8, 20, 228))
        header = pygame.Rect(34, 52, 732, 170)
        pygame.draw.rect(layer, (10, 13, 30), header, border_radius=10)
        pygame.draw.rect(layer, (46, 54, 92), header, width=1,
                         border_radius=10)
        self.draw_gameover_header(layer)
        story = getattr(self, "story", None)
        self.story_link_rect = None
        if story is not None:
            self.draw_gameover_story(layer, story)
        else:
            self.draw_gameover_fallback(layer)
        hint = self.font_small.render(
            "press ENTER to play again", True, (255, 220, 120))
        scores_hint = self.font_small.render(
            "press L for high scores", True, UI_DIM)
        layer.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 522))
        layer.blit(scores_hint,
                   (WIDTH // 2 - scores_hint.get_width() // 2, 546))
        layer.set_alpha(int(255 * fade))
        surface.blit(layer, (0, 0))

    def draw_gameover_header(self, surface: pygame.Surface) -> None:
        stats = self.run_stats()
        title = self.font_big.render("GAME OVER", True, (255, 110, 130))
        score = self.font_mid.render(
            f"SCORE {self.score}   WAVE {self.wave}", True, UI_COLOR)
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
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 68))
        surface.blit(score, (WIDTH // 2 - score.get_width() // 2, 128))
        surface.blit(line, (WIDTH // 2 - line.get_width() // 2, 160))
        surface.blit(rank, (WIDTH // 2 - rank.get_width() // 2, 186))

    def draw_gameover_fallback(self, surface: pygame.Surface) -> None:
        """The story card's slot when the NASA feed did not answer."""
        panel = pygame.Rect(34, 222, 732, 288)
        pygame.draw.rect(surface, (14, 18, 38), panel, border_radius=10)
        pygame.draw.rect(surface, (46, 54, 92), panel, width=1,
                         border_radius=10)
        title = self.font_mid.render("NO TRANSMISSION", True, UI_DIM)
        sub = self.font_small.render(
            "The NASA story feed did not answer this run.", True, UI_DIM)
        surface.blit(title, (WIDTH // 2 - title.get_width() // 2, 336))
        surface.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 378))


    def draw_record_banner(self, surface: pygame.Surface) -> None:
        """A flashing marquee that scrolls the new record across the arena."""
        remaining = self.record_banner_time
        if remaining <= 0:
            return
        elapsed = RECORD_BANNER_TIME - remaining
        fade = min(1.0, remaining / 0.30)
        height = 88
        top = 232

        band = pygame.Surface((WIDTH, height), pygame.SRCALPHA)
        band.fill((12, 9, 24, int(176 * fade)))
        surface.blit(band, (0, top))

        flash = int(elapsed / 0.11) % 2 == 0
        colour = (255, 246, 205) if flash else (255, 197, 92)
        pygame.draw.rect(surface, colour, (0, top, WIDTH, 2))
        pygame.draw.rect(surface, colour, (0, top + height - 2, WIDTH, 2))

        text = (f"  *  NEW HIGH SCORE  {self.record_banner_score:05d}"
                f"  *  ")
        tile = self.font_mid.render(text, True, colour)
        tile.set_alpha(int(255 * fade))
        width = max(1, tile.get_width())
        offset = int(elapsed * RECORD_BANNER_SCROLL) % width
        baseline = top + height // 2 - tile.get_height() // 2
        x = -offset
        while x < WIDTH:
            surface.blit(tile, (x, baseline))
            x += width

    def draw_gameover_story(self, surface: pygame.Surface, story) -> None:
        """The NASA story card in the game-over panel slot."""
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
