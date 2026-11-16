"""Procedural 1960s science-fiction paperback cover paintings.

Every wave asks for a fresh cover.  The painter picks a limited period palette
and one of six compositions -- a rocket ascent, an astronaut vista, a saucer
over a domed city, a robot invasion of that city, a ringed giant, or an
eclipse -- then paints it with flat shapes, airbrushed glows and a final
print-aging pass (halftone, grain, creases, misregistration and a vignette).

Everything is drawn with pygame primitives plus numpy for gradients and the
grain pass.  There are no image assets and no model weights, and the same seed
always produces the same cover.
"""

from __future__ import annotations

import itertools
import math
import random

import numpy as np
import pygame

# Limited period palettes: sky top, sky mid, horizon glow, accent, secondary,
# paper, ink.  Jittered per cover so two covers never share an exact palette.
_SCHEMES = (
    ("ember", (11, 14, 38), (58, 26, 56), (154, 62, 46),
     (236, 92, 52), (250, 196, 96), (242, 228, 200), (10, 9, 20)),
    ("teal", (8, 20, 34), (16, 58, 68), (32, 106, 106),
     (226, 84, 62), (116, 214, 198), (238, 230, 206), (8, 14, 20)),
    ("violet", (14, 10, 38), (48, 22, 74), (96, 40, 96),
     (236, 96, 156), (120, 226, 206), (240, 222, 204), (12, 8, 24)),
    ("acid", (10, 18, 20), (22, 44, 40), (64, 88, 44),
     (208, 226, 96), (240, 126, 62), (236, 232, 204), (10, 14, 12)),
    ("ultra", (6, 10, 30), (18, 20, 60), (40, 34, 96),
     (250, 92, 68), (108, 178, 250), (240, 234, 214), (6, 8, 18)),
    ("rust", (20, 12, 24), (58, 26, 32), (120, 54, 38),
     (224, 108, 54), (226, 196, 132), (240, 226, 198), (14, 10, 14)),
    ("cobalt", (8, 16, 42), (18, 40, 84), (38, 78, 122),
     (246, 146, 62), (140, 218, 226), (238, 234, 214), (8, 10, 24)),
    ("mint", (10, 24, 30), (24, 60, 58), (56, 104, 84),
     (240, 156, 96), (128, 220, 176), (242, 236, 212), (8, 16, 16)),
)

TITLES = (
    "WORLDS BEYOND", "THE STAR BEAST", "PLANET OF TERROR", "VOID RUNNERS",
    "THE CRIMSON MOON", "OUTPOST X-9", "STARFALL", "THE LAST ORBIT",
    "GALAXY OF DOOM", "SIGNAL FROM NOWHERE", "THE SILENT SUN", "DEEP BLACK",
    "TWILIGHT WORLDS", "THE GLASS COMET", "SEA OF STARS", "THE IRON SKY",
    "THE STARS ARE OURS", "PLANET OF THE DAMNED", "SUNS OF DARKNESS",
    "VOID STATION", "THE LAST ASTRONAUT", "WORLDS IN COLLISION",
    "THE SILENT INVADERS", "BEYOND THE RINGS", "THE GLASS WORLD",
    "EMPIRE OF THE STARS", "THE CRIMSON ORBIT", "CITY AT EDGE OF NIGHT",
    "THE DYING SUN", "SEED OF THE STARS", "OUTPOST INFINITY",
    "ORBIT OF DOOM", "THE IRON MOON", "COLLISION COURSE",
    "THE FROZEN SUN", "A WORLD CALLED TOMORROW", "THE SKY IS FALLING",
    "THE ALIEN SHORE", "DARK SIDE OF TIME", "THE SEVENTH PLANET",
)

TAGLINES = (
    "A NOVEL OF THE WORLD OF TOMORROW", "THEY SAID IT COULD NOT HAPPEN",
    "SOMEWHERE BEYOND THE STARS", "ONE SHIP. ONE CHANCE.",
    "NO ONE RETURNS FROM THE RIM", "THE UNIVERSE IS WATCHING",
    "FIRST CONTACT WAS ONLY THE BEGINNING", "MANKIND'S LAST OUTPOST",
    "THE STARS ARE NOT EMPTY", "A THRILLING NOVEL OF THE FUTURE",
)

AUTHORS = (
    "EARL VANCE", "MARGOT KEPLER", "J. T. ARDEN", "RUTH CALDER",
    "LEO MARCHETTI", "ANNA VOSS", "D. R. HALE", "VICTOR SLOAN",
    "IRENE DALLAS", "BRUNO KESSLER",
)

IMPRINTS = ("ORBIT BOOKS", "NOVA PRESS", "STELLAR LIBRARY",
            "COMET BOOKS", "ASTRAL HOUSE")

PRICES = ("35\u00a2", "40\u00a2", "45\u00a2", "50\u00a2", "60\u00a2")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _blend(a: tuple[int, int, int], b: tuple[int, int, int],
           t: float) -> tuple[int, int, int]:
    t = _clamp(t, 0.0, 1.0)
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _lum(colour: tuple[int, int, int]) -> float:
    return (0.2126 * colour[0] + 0.7152 * colour[1]
            + 0.0722 * colour[2]) / 255.0


def _jitter(rng: random.Random, colour: tuple[int, int, int],
            amount: int = 7) -> tuple[int, int, int]:
    return tuple(int(_clamp(c + rng.uniform(-amount, amount), 0, 255))
                 for c in colour)


def _pt(point: tuple[float, float]) -> tuple[int, int]:
    return round(point[0]), round(point[1])


def _pts(points) -> list[tuple[int, int]]:
    return [_pt(point) for point in points]


def _rect(x: float, y: float, w: float, h: float) -> pygame.Rect:
    return pygame.Rect(round(x), round(y),
                       max(1, round(w)), max(1, round(h)))


# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #

def _palette(rng: random.Random) -> dict[str, object]:
    (_name, top, mid, horizon, accent, secondary,
     paper, ink) = rng.choice(_SCHEMES)
    accent = _jitter(rng, accent)
    secondary = _jitter(rng, secondary)
    paper = _jitter(rng, paper, 4)
    ink = _jitter(rng, ink, 3)

    if rng.random() < 0.30:
        # Bright matte-painting sky, with the horizon washing into paper.
        sky_top = _blend(mid, ink, 0.30)
        sky_bottom = _blend(horizon, paper, 0.34)
    else:
        sky_top = _blend(top, ink, 0.18)
        sky_bottom = _blend(mid, horizon, 0.62)

    planet_light = accent if rng.random() < 0.62 else secondary
    planet_light = _blend(planet_light, paper, rng.uniform(0.10, 0.24))
    planet_dark = _blend(ink, top, 0.24)
    rim = _blend(paper, secondary, 0.42)
    terrain_far = _blend(ink, accent, 0.22)
    terrain_mid = _blend(ink, accent, 0.12)
    terrain_near = _blend(ink, (0, 0, 0), 0.42)

    return {
        "sky_top": sky_top,
        "sky_bottom": sky_bottom,
        "accent": accent,
        "accent2": secondary,
        "paper": paper,
        "ink": ink,
        "rim": rim,
        "planet_light": planet_light,
        "planet_dark": planet_dark,
        "terrain_far": terrain_far,
        "terrain_mid": terrain_mid,
        "terrain_near": terrain_near,
        "lights": secondary,
        "craft": paper,
        "craft_shadow": _blend(paper, ink, 0.34),
        "craft_high": _blend(paper, (255, 255, 255), 0.55),
    }


# --------------------------------------------------------------------------- #
# Backdrop primitives
# --------------------------------------------------------------------------- #

def _gradient(w: int, h: int, top: tuple[int, int, int],
              bottom: tuple[int, int, int], power: float = 1.25) -> pygame.Surface:
    t = np.linspace(0.0, 1.0, h, dtype=np.float32) ** power
    cols = np.stack([top[c] + (bottom[c] - top[c]) * t for c in range(3)],
                    axis=1)
    arr = np.repeat(cols[None, :, :], w, axis=0)
    # Ordered dither: an 8-bit sky this dark banded badly without it.
    noise = np.random.default_rng(0x5EEDC0DE).uniform(-1.2, 1.2, (w, h, 1))
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return pygame.surfarray.make_surface(arr)


def _soft_circle(target: pygame.Surface, cx: float, cy: float, radius: float,
                 colour: tuple[int, int, int], alpha: int) -> None:
    """An airbrushed disc, built small and scaled up."""
    radius = max(2.0, float(radius))
    size = 48
    small = pygame.Surface((size, size), pygame.SRCALPHA)
    centre = size // 2
    for i in range(10, 0, -1):
        r = int((centre - 2) * i / 10)
        pygame.draw.circle(small, (*colour, max(1, alpha // 10)),
                           (centre, centre), r)
    scaled = pygame.transform.smoothscale(
        small, (int(radius * 2), int(radius * 2)))
    target.blit(scaled, (int(cx - radius), int(cy - radius)))


def _soft_ellipse(target: pygame.Surface, cx: float, cy: float, rx: float,
                  ry: float, colour: tuple[int, int, int], alpha: int) -> None:
    rx = max(2.0, float(rx))
    ry = max(2.0, float(ry))
    small = pygame.Surface((64, 32), pygame.SRCALPHA)
    pygame.draw.ellipse(small, (*colour, alpha), (2, 2, 60, 28))
    scaled = pygame.transform.smoothscale(small, (int(rx * 2), int(ry * 2)))
    target.blit(scaled, (int(cx - rx), int(cy - ry)))


def _stars(art: pygame.Surface, rng: random.Random,
           pal: dict[str, object], count: int,
           max_y: float | None = None) -> None:
    w, h = art.get_size()
    limit = int(max_y or h)
    for _ in range(count):
        x = rng.randrange(w)
        y = int((rng.random() ** 1.45) * limit)
        roll = rng.random()
        if roll < 0.7:
            base = pal["paper"]
        elif roll < 0.9:
            base = pal["accent2"]
        else:
            base = pal["accent"]
        colour = _blend(pal["sky_top"], base, rng.uniform(0.35, 1.0))
        size = 2 if rng.random() < 0.05 else 1
        art.fill(colour, (x, y, size, size))

    for _ in range(rng.randint(4, 9)):
        x = rng.randrange(18, w - 18)
        y = rng.randrange(14, max(20, int(limit * 0.75)))
        flare = rng.randint(4, 9)
        colour = _blend(pal["sky_top"], pal["paper"], 0.55)
        pygame.draw.line(art, colour, (x - flare, y), (x + flare, y))
        pygame.draw.line(art, colour, (x, y - flare), (x, y + flare))
        art.fill(pal["paper"], (x, y, 1, 1))


def _nebula(art: pygame.Surface, rng: random.Random,
            pal: dict[str, object]) -> None:
    w, h = art.get_size()
    small = pygame.Surface((200, 150), pygame.SRCALPHA)
    for _ in range(rng.randint(6, 10)):
        colour = rng.choice((pal["accent"], pal["accent2"], pal["rim"]))
        rect = _rect(rng.uniform(-50, 200), rng.uniform(-40, 150),
                     rng.uniform(90, 210), rng.uniform(30, 95))
        pygame.draw.ellipse(small, (*colour, rng.randint(12, 28)), rect)
    art.blit(pygame.transform.smoothscale(small, (w, h)), (0, 0))


def _planet(art: pygame.Surface, rng: random.Random,
            pal: dict[str, object], cx: int, cy: int, radius: int,
            bands: bool = False, craters: bool = False) -> None:
    radius = max(4, int(radius))
    for rr, alpha in ((radius * 1.24, 14), (radius * 1.10, 22),
                      (radius * 1.035, 30)):
        _soft_circle(art, cx, cy, rr, pal["rim"], alpha)

    size = radius * 2 + 4
    c = size // 2

    # Shade the sphere with a real light direction instead of stacked discs:
    # the terminator, limb darkening and band curvature all come out of this.
    coords = (np.arange(size, dtype=np.float32) - c) / float(radius)
    xs = coords[:, None]
    ys = coords[None, :]
    r2 = xs * xs + ys * ys
    z = np.sqrt(np.clip(1.0 - r2, 0.0, 1.0))

    lx, ly, lz = -0.50, -0.56, 0.66
    lam = np.clip(xs * lx + ys * ly + z * lz, 0.0, 1.0)
    shade = 0.13 + 0.87 * lam ** 0.85
    shade *= 0.55 + 0.45 * z ** 0.35

    if bands:
        lat = np.arcsin(np.clip(ys, -1.0, 1.0))
        warp = (0.55 * np.sin(xs * 2.4 + 0.9)
                + 0.28 * np.sin(xs * 5.3 + 2.1))
        freq = rng.uniform(7.0, 13.0)
        band = np.sin(lat * freq + warp)
        shade *= 1.0 + rng.uniform(0.07, 0.13) * band * (0.35 + 0.65 * z)

    light = np.array(pal["planet_light"], dtype=np.float32)
    dark = np.array(pal["planet_dark"], dtype=np.float32)
    rgb = dark + (light - dark) * shade[..., None]

    # A warm painted highlight on the lit shoulder.
    hx, hy = -0.36, -0.40
    glow = np.exp(-(((xs - hx) ** 2 + (ys - hy) ** 2) / 0.055))
    rgb += glow[..., None] * np.array((26.0, 20.0, 10.0), dtype=np.float32)

    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    surf.blit(pygame.surfarray.make_surface(
        np.clip(rgb, 0, 255).astype(np.uint8)), (0, 0))

    if craters and radius <= 95:
        for _ in range(rng.randint(5, 12)):
            angle = rng.uniform(0.0, math.tau)
            dist = rng.uniform(0.05, 0.66) * radius
            x = c + math.cos(angle) * dist
            y = c + math.sin(angle) * dist
            cr = rng.uniform(0.035, 0.09) * radius
            shade_col = _blend(pal["planet_light"], pal["planet_dark"], 0.58)
            pygame.draw.circle(surf, shade_col,
                               (int(x), int(y)), max(1, int(cr)))
            pygame.draw.arc(surf, _blend(pal["rim"], pal["paper"], 0.20),
                            _rect(x - cr, y - cr * 0.7,
                                  cr * 2, cr * 1.4),
                            math.radians(20), math.radians(160), 1)

    pygame.draw.arc(surf, _blend(pal["rim"], pal["paper"], 0.30),
                    _rect(2, 2, size - 5, size - 5),
                    math.radians(96), math.radians(188),
                    max(1, radius // 60))

    mask = pygame.Surface((size, size), pygame.SRCALPHA)
    pygame.draw.circle(mask, (255, 255, 255, 255), (c, c), radius)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    art.blit(surf, (cx - c, cy - c))


def _rings(art: pygame.Surface, pal: dict[str, object],
           cx: int, cy: int, radius: int, front: bool) -> None:
    w, h = art.get_size()
    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    bands = (
        (1.000, 0.017, _blend(pal["rim"], pal["paper"], 0.30), 150),
        (0.962, 0.038, _blend(pal["accent"], pal["paper"], 0.20), 190),
        (0.918, 0.011, _blend(pal["paper"], pal["rim"], 0.15), 210),
        (0.884, 0.026, _blend(pal["accent"], pal["ink"], 0.30), 175),
        (0.842, 0.009, _blend(pal["paper"], pal["accent2"], 0.30), 150),
        (0.790, 0.034, _blend(pal["rim"], pal["accent"], 0.35), 165),
        (0.722, 0.010, _blend(pal["paper"], pal["rim"], 0.35), 140),
        (0.664, 0.024, _blend(pal["accent"], pal["ink"], 0.45), 130),
    )
    for scale, thickness, colour, alpha in bands:
        rect = _rect(cx - radius * 1.82 * scale, cy - radius * 0.48 * scale,
                     radius * 3.64 * scale, radius * 0.96 * scale)
        pygame.draw.ellipse(layer, (*colour, alpha), rect,
                            max(1, int(radius * thickness)))

    if front:
        art.set_clip(pygame.Rect(0, cy, w, h - cy))
    else:
        art.set_clip(pygame.Rect(0, 0, w, cy))
    art.blit(layer, (0, 0))
    art.set_clip(None)


def _orbit_arc(art: pygame.Surface, rng: random.Random,
               pal: dict[str, object], cx: int, cy: int, radius: int) -> None:
    rect = _rect(cx - radius, cy - radius * 0.42,
                 radius * 2, radius * 0.84)
    colour = _blend(pal["sky_top"], pal["paper"], 0.42)
    start = rng.uniform(0.1, 0.9)
    pygame.draw.arc(art, colour, rect, start, start + rng.uniform(1.3, 2.2), 1)


def _comet(art: pygame.Surface, rng: random.Random,
           pal: dict[str, object]) -> None:
    w, h = art.get_size()
    x = rng.uniform(w * 0.12, w * 0.88)
    y = rng.uniform(h * 0.14, h * 0.36)
    angle = rng.uniform(math.pi * 1.13, math.pi * 1.40)
    length = rng.uniform(w * 0.12, w * 0.26)
    tail = pygame.Surface((w, h), pygame.SRCALPHA)
    dx, dy = math.cos(angle), math.sin(angle)
    px, py = -dy, dx
    steps = 90
    for i in range(steps):
        t = i / (steps - 1)
        cx = x + dx * length * t + px * math.sin(math.pi * t) * length * 0.08
        cy = y + dy * length * t + py * math.sin(math.pi * t) * length * 0.08
        colour = _blend(pal["paper"], pal["sky_bottom"],
                        min(1.0, 0.15 + 0.85 * t))
        alpha = int(145 * (1.0 - t) ** 0.9)
        radius = max(1, int(3.2 * (1.0 - t) ** 0.55 + 1.0))
        pygame.draw.circle(tail, (*colour, alpha), (int(cx), int(cy)),
                           radius)
    # Faint longer streaks trailing the main plume.
    for k in range(rng.randint(2, 4)):
        off = rng.uniform(-0.09, 0.09) * length
        end = length * rng.uniform(1.1, 1.5)
        pygame.draw.line(tail, (*pal["paper"], 40),
                         (int(x + px * off), int(y + py * off)),
                         (int(x + dx * end + px * off),
                          int(y + dy * end + py * off)), 1)
    art.blit(tail, (0, 0))
    _soft_circle(art, x, y, 13, pal["paper"], 80)
    art.fill(pal["paper"], (int(x), int(y), 2, 2))


# --------------------------------------------------------------------------- #
# Landforms and cities
# --------------------------------------------------------------------------- #

def _ridge_points(rng: random.Random, w: int, y: float, amp: float,
                  levels: int = 5) -> list[tuple[float, float]]:
    pts = [(-20.0, y + rng.uniform(-amp, amp)),
           (w + 20.0, y + rng.uniform(-amp, amp))]
    for _ in range(levels):
        out = [pts[0]]
        for a, b in itertools.pairwise(pts):
            mx = (a[0] + b[0]) * 0.5 + rng.uniform(-7, 7)
            my = (a[1] + b[1]) * 0.5 + rng.uniform(-1, 1) * amp
            out.append((mx, my))
            out.append(b)
        pts = out
        amp *= 0.52
    return pts


def _ridge_y(pts: list[tuple[float, float]], x: float) -> float:
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        if x0 <= x <= x1:
            t = (x - x0) / max(1e-6, x1 - x0)
            return y0 + (y1 - y0) * t
    return pts[-1][1]


def _ridge(art: pygame.Surface, rng: random.Random,
           pal: dict[str, object], y: float, amp: float,
           colour: tuple[int, int, int], rim: bool = True,
           craters: bool = False, shade: bool = True) -> None:
    w, h = art.get_size()
    pts = _ridge_points(rng, w, y, amp)
    poly = [(-20.0, h + 40.0), *pts, (w + 20.0, h + 40.0)]

    layer = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.polygon(layer, (*colour, 255), _pts(poly))

    if shade:
        # Ground plane falls away into shadow instead of reading as a flat
        # black band across the bottom third of the cover.
        rows = np.linspace(0.0, 1.0, h, dtype=np.float32)[None, :]
        top = max(0.01, min(0.99, y / h))
        depth = np.clip((rows - top) / (1.0 - top), 0.0, 1.0)
        factor = 1.0 - 0.62 * depth ** 1.15
        arr = pygame.surfarray.pixels3d(layer)
        arr[:] = (arr * factor[..., None]).astype(np.uint8)
        del arr
    art.blit(layer, (0, 0))

    if rim:
        edge = [(x, yy - 1.5) for x, yy in pts]
        pygame.draw.lines(art, _blend(colour, pal["paper"], 0.30),
                          False, _pts(edge), 2)

    # Grit and pebbles so the near ground has some tooth.
    for _ in range(rng.randint(70, 140)):
        x = rng.uniform(0, w)
        top = _ridge_y(pts, x)
        gy = rng.uniform(top + 3, h)
        if gy > h - 2:
            continue
        tone = (rng.random() - 0.5) * 1.4
        speck = _blend(colour, pal["paper"] if tone > 0 else pal["ink"],
                       abs(tone) * 0.24)
        art.fill(speck, (int(x), int(gy), rng.choice((1, 1, 2)),
                         rng.choice((1, 2))))

    if craters:
        for _ in range(rng.randint(2, 5)):
            x = rng.uniform(30, w - 30)
            top = _ridge_y(pts, x)
            rad = rng.uniform(9, 26)
            cy = top + rad * 0.8 + rng.uniform(6, 26)
            if cy + rad > h:
                continue
            pygame.draw.ellipse(art, _blend(colour, pal["ink"], 0.50),
                                _rect(x - rad, cy - rad * 0.30,
                                      rad * 2, rad * 0.60))
            pygame.draw.arc(art, _blend(colour, pal["paper"], 0.30),
                            _rect(x - rad, cy - rad * 0.30,
                                  rad * 2, rad * 0.60),
                            math.radians(20), math.radians(160), 2)


def _dome_points(cx: float, base_y: float, radius: float,
                 steps: int = 14) -> list[tuple[float, float]]:
    pts = [(cx - radius, base_y)]
    for i in range(steps + 1):
        ang = math.pi * (i / steps)
        pts.append((cx - radius * math.cos(ang),
                    base_y - radius * math.sin(ang)))
    pts.append((cx + radius, base_y))
    return pts


def _city(art: pygame.Surface, rng: random.Random, pal: dict[str, object],
          base_y: int, scale: float = 1.0) -> None:
    w, _h = art.get_size()
    _soft_ellipse(art, w // 2, base_y, w * 0.52, 54 * scale,
                  pal["accent2"], 26)
    fill = _blend(pal["ink"], pal["terrain_far"], 0.45)
    dark = _blend(fill, pal["ink"], 0.45)
    lamp = _blend(pal["lights"], pal["paper"], 0.45)
    x = -12.0
    while x < w:
        kind = rng.random()
        bw = rng.randint(20, 46) * scale
        if kind < 0.54:
            # Ribbed pressure dome with a scatter of lit windows.
            radius = bw * rng.uniform(0.38, 0.70)
            pts = _dome_points(x + bw / 2, base_y, radius)
            pygame.draw.polygon(art, fill, _pts(pts))
            for k in range(1, 5):
                px = x + bw * k / 5
                pygame.draw.line(art, dark, (int(px), base_y),
                                 (int(px), int(base_y - radius * 0.86)), 1)
            pygame.draw.arc(art, _blend(fill, pal["rim"], 0.22),
                            _rect(x, base_y - radius, bw, radius * 2),
                            math.radians(12), math.radians(168), 1)
            for _ in range(rng.randint(3, 8)):
                wx = x + rng.uniform(3, max(4, bw - 3))
                wy = base_y - rng.uniform(2, radius * 0.72)
                art.fill(lamp, (int(wx), int(wy), 1, 2))
            if rng.random() < 0.4:
                ax = x + bw / 2
                pygame.draw.line(art, fill, (int(ax), int(base_y - radius)),
                                 (int(ax), int(base_y - radius - 16)), 1)
                art.fill(lamp, (int(ax), int(base_y - radius - 17), 1, 1))
        elif kind < 0.86:
            # Setback slab tower with a window grid, very period.
            bh = rng.randint(34, 104) * scale
            tiers = rng.randint(1, 3)
            step = bw * 0.16
            top = base_y - bh
            for tier in range(tiers):
                inset = step * tier
                th = bh / tiers
                rect = _rect(x + inset, base_y - th * (tier + 1),
                             bw - inset * 2, th + 1)
                pygame.draw.rect(art, fill, rect)
            band = _blend(fill, pal["ink"], 0.30)
            pygame.draw.rect(art, band, _rect(x + step * (tiers - 1),
                                              top, bw - step * 2 * (tiers - 1),
                                              step * 0.6))
            for _ in range(rng.randint(4, 12)):
                wx = x + rng.uniform(3, max(4, bw - 4))
                wy = rng.uniform(top + 6, base_y - 4)
                art.fill(lamp, (int(wx), int(wy), 1, 1))
            pygame.draw.line(art, fill, (int(x + bw / 2), int(top)),
                             (int(x + bw / 2), int(top - 10)), 1)
        else:
            # Needle spire with a small observation deck.
            bh = rng.randint(46, 116) * scale
            top = base_y - bh
            spine_w = max(2, bw * 0.15)
            pygame.draw.polygon(art, fill,
                                [(int(x + bw * 0.34), base_y),
                                 (int(x + bw * 0.5), top),
                                 (int(x + bw * 0.66), base_y)])
            pygame.draw.rect(art, fill,
                             _rect(x + bw * 0.42, top + bh * 0.42,
                                   bw * 0.16, bh * 0.55))
            if rng.random() < 0.55:
                ring_y = top + bh * rng.uniform(0.30, 0.46)
                pygame.draw.ellipse(art, fill,
                                    _rect(x + bw * 0.5 - spine_w * 1.9,
                                          ring_y, spine_w * 3.8,
                                          spine_w * 1.1))
            pygame.draw.line(art, fill,
                             (int(x + bw * 0.5), int(top)),
                             (int(x + bw * 0.5), int(top - 9)), 1)
            art.fill(lamp, (int(x + bw * 0.5), int(top - 10), 1, 1))
            for _ in range(rng.randint(2, 5)):
                art.fill(lamp,
                         (int(x + bw * 0.5), int(rng.uniform(top + 10, base_y - 4)),
                          1, 1))
        x += bw + rng.randint(2, 10)
        if rng.random() < 0.22:
            x += rng.randint(18, 54)


def _foreground_flora(art: pygame.Surface, rng: random.Random,
                      pal: dict[str, object], base_y: float) -> None:
    """A few near-black cacti, rocks or antennae to break the flat horizon."""
    w, h = art.get_size()
    ink = _blend(pal["ink"], (0, 0, 0), 0.55)
    rim = _blend(pal["terrain_near"], pal["paper"], 0.18)
    for _ in range(rng.randint(2, 5)):
        x = rng.uniform(w * 0.04, w * 0.96)
        height = rng.uniform(h * 0.035, h * 0.085)
        if rng.random() < 0.45:
            # A stubby rock or boulder.
            rw = height * rng.uniform(0.7, 1.5)
            pygame.draw.ellipse(art, ink,
                                _rect(x - rw, base_y - height * 0.55,
                                      rw * 2, height))
            pygame.draw.arc(art, rim,
                            _rect(x - rw, base_y - height * 0.55,
                                  rw * 2, height),
                            math.radians(30), math.radians(150), 1)
        else:
            # Saguaro-ish alien plant, or a thin mast.
            pygame.draw.line(art, ink, (int(x), int(base_y)),
                             (int(x), int(base_y - height)), 3)
            if rng.random() < 0.6:
                side = rng.choice((-1, 1))
                elbow = (x + side * height * 0.34, base_y - height * 0.62)
                pygame.draw.line(art, ink, (int(x), int(base_y - height * 0.40)),
                                 (int(elbow[0]), int(elbow[1])), 3)
                pygame.draw.line(art, ink,
                                 (int(elbow[0]), int(elbow[1])),
                                 (int(elbow[0]),
                                  int(elbow[1] - height * 0.30)), 3)
                pygame.draw.line(art, rim,
                                 (int(elbow[0]) - 1,
                                  int(elbow[1] - height * 0.30)),
                                 (int(elbow[0]) - 1, int(base_y)))
            else:
                art.fill(rim, (int(x), int(base_y - height), 2, 2))


def _beam(art: pygame.Surface, rng: random.Random, pal: dict[str, object],
          x: float, y_top: int, y_bottom: int,
          top_half: float, bottom_half: float) -> None:
    height = max(2, y_bottom - y_top)
    width = int(bottom_half * 2 + 12)
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    cx = width / 2.0
    for i in range(7):
        shrink = 1.0 - i * 0.115
        th = max(1.0, top_half * shrink)
        bh = max(1.0, bottom_half * shrink)
        pygame.draw.polygon(surf, (*pal["accent2"], 18),
                            [(int(cx - th), 0), (int(cx + th), 0),
                             (int(cx + bh), height), (int(cx - bh), height)])
    # A warmer shaft down the middle.
    for i in range(4):
        shrink = 1.0 - i * 0.18
        th = max(1.0, top_half * shrink * 0.55)
        bh = max(1.0, bottom_half * shrink * 0.55)
        pygame.draw.polygon(surf, (*pal["paper"], 12),
                            [(int(cx - th), 0), (int(cx + th), 0),
                             (int(cx + bh), height), (int(cx - bh), height)])
    for _ in range(rng.randint(14, 26)):
        px = cx + rng.uniform(-bottom_half * 0.9, bottom_half * 0.9)
        py = rng.uniform(height * 0.2, height * 0.98)
        colour = _blend(pal["paper"], pal["accent2"], rng.random())
        pygame.draw.circle(surf, (*colour, 150), (int(px), int(py)), 1)
    art.blit(surf, (int(x - cx), y_top))
    # Pool of light where the beam lands.
    _soft_ellipse(art, x, y_bottom, bottom_half * 1.25, 12,
                  pal["accent2"], 46)


def _searchlight(art: pygame.Surface, rng: random.Random,
                 pal: dict[str, object], x: float, base_y: float,
                 length: float) -> None:
    """A raking anti-aircraft beam, translucent enough to stay period."""
    length = max(20.0, float(length))
    angle = rng.uniform(-40.0, 40.0)
    half_top = length * rng.uniform(0.05, 0.09)
    surf = pygame.Surface((int(half_top * 2 + 10), int(length)),
                          pygame.SRCALPHA)
    cx = surf.get_width() / 2.0
    floor = surf.get_height()
    for i in range(6):
        shrink = 1.0 - i * 0.16
        pygame.draw.polygon(
            surf, (*pal["paper"], 7),
            [(int(cx - 2), floor), (int(cx + 2), floor),
             (int(cx + half_top * shrink), 0),
             (int(cx - half_top * shrink), 0)])
    pygame.draw.line(surf, (*pal["paper"], 44),
                     (int(cx), floor), (int(cx), 0), 1)
    rotated = pygame.transform.rotozoom(surf, angle, 1.0)
    art.blit(rotated, rotated.get_rect(midbottom=(int(x), int(base_y))))


# --------------------------------------------------------------------------- #
# Vehicles and figures
# --------------------------------------------------------------------------- #

def _rocket_sprite(rng: random.Random, pal: dict[str, object], height: int,
                   dark: bool = False) -> pygame.Surface:
    """A finned 1950s rocket, drawn upright with its exhaust below."""
    hh = float(height)
    hw_max = hh * 0.15
    surf = pygame.Surface((int(hh * 0.78), int(hh * 1.42)), pygame.SRCALPHA)
    w, h = surf.get_size()
    cx = w / 2.0
    nose = h * 0.03
    tail = h * 0.72
    blen = tail - nose

    def half_width(t: float) -> float:
        if t < 0.16:
            return hw_max * 0.62 * (t / 0.16) ** 0.7
        if t < 0.30:
            return hw_max * (0.62 + 0.38 * (t - 0.16) / 0.14)
        if t < 0.84:
            return hw_max
        return hw_max * (1.0 - 0.22 * ((t - 0.84) / 0.16))

    def at(t: float, side: float, scale: float = 1.0,
           shift: float = 0.0) -> tuple[float, float]:
        return (cx + side * half_width(t) * scale + shift,
                nose + t * blen)

    if dark:
        body_shadow = pal["ink"]
        body = pal["ink"]
        body_high = _blend(pal["ink"], pal["accent2"], 0.35)
        fin_col = _blend(pal["ink"], pal["accent"], 0.20)
        cone = _blend(pal["ink"], pal["accent"], 0.30)
        band = _blend(pal["ink"], pal["accent2"], 0.35)
        glass_rim = pal["ink"]
        glass = _blend(pal["accent2"], pal["ink"], 0.45)
        line_col = _blend(pal["ink"], pal["accent2"], 0.30)
    else:
        body_shadow = pal["craft_shadow"]
        body = pal["craft"]
        body_high = pal["craft_high"]
        fin_col = pal["accent"]
        cone = pal["accent"]
        band = pal["accent2"]
        glass_rim = pal["ink"]
        glass = _blend(pal["accent2"], pal["ink"], 0.15)
        line_col = _blend(pal["craft_shadow"], pal["ink"], 0.35)

    steps = 30
    intervals = [i / steps for i in range(steps + 1)]

    # Rear fin, mostly hidden by the hull.
    pygame.draw.polygon(
        surf, _blend(fin_col, pal["ink"], 0.38),
        _pts([(cx - hw_max * 0.16, nose + blen * 0.62),
              (cx, nose + blen * 1.13),
              (cx + hw_max * 0.16, nose + blen * 0.62)]))

    # Side fins hug the lower hull, leaving the exhaust plume visible below.
    for side in (-1, 1):
        pts = [at(0.60, side, 0.98),
               (cx + side * hw_max * 1.72, nose + blen * 0.93),
               (cx + side * hw_max * 0.90, nose + blen * 0.995)]
        pygame.draw.polygon(surf, fin_col, _pts(pts))
        pygame.draw.lines(surf, _blend(fin_col, pal["paper"], 0.30),
                          False, _pts(pts[:2]), 2)

    # Exhaust: three nested teardrops plus a glow.
    _soft_circle(surf, cx, tail + (h - tail) * 0.22,
                 hw_max * 1.7, pal["accent"], 55)

    def flame(width: float, length: float,
              colour: tuple[int, int, int]) -> None:
        pts = []
        for i in range(13):
            t = i / 12
            pts.append((cx - width * (1.0 - t) ** 0.8,
                        tail + length * t))
        for i in range(12, -1, -1):
            t = i / 12
            pts.append((cx + width * (1.0 - t) ** 0.8,
                        tail + length * t))
        pygame.draw.polygon(surf, colour, _pts(pts))

    flame(hw_max * 0.95, (h - tail) * 1.02, pal["accent"])
    flame(hw_max * 0.62, (h - tail) * 0.74, pal["accent2"])
    flame(hw_max * 0.30, (h - tail) * 0.46, (255, 250, 220))

    # Hull: a shadow silhouette, a light inner silhouette and a highlight.
    body_pts = ([at(t, -1) for t in intervals]
                + [at(t, 1) for t in reversed(intervals)])
    pygame.draw.polygon(surf, body_shadow, _pts(body_pts))
    inner = ([at(t, -1, 0.87, -hw_max * 0.07) for t in intervals]
             + [at(t, 1, 0.87, -hw_max * 0.07)
                for t in reversed(intervals)])
    pygame.draw.polygon(surf, body, _pts(inner))
    stripe = ([at(t, -1, 0.40, -hw_max * 0.24) for t in intervals]
              + [at(t, 1, 0.40, -hw_max * 0.24)
                 for t in reversed(intervals)])
    pygame.draw.polygon(surf, body_high, _pts(stripe))

    # Nose cone and a painted stripe.
    cone_pts = ([(cx, nose)]
                + [at(t, -1) for t in intervals if t <= 0.30]
                + [at(t, 1) for t in reversed(intervals) if t <= 0.30])
    pygame.draw.polygon(surf, cone, _pts(cone_pts))
    pygame.draw.lines(
        surf, _blend(cone, pal["paper"], 0.35), False,
        _pts([(cx, nose + 1)]
             + [at(t, -1, 0.86) for t in intervals if 0.03 <= t <= 0.30]), 2)
    pygame.draw.polygon(surf, band,
                        _pts([at(0.30, -1), at(0.345, -1),
                              at(0.345, 1), at(0.30, 1)]))

    for t in (0.38, 0.60, 0.76):
        pygame.draw.line(surf, line_col, _pt(at(t, -1, 0.86)),
                         _pt(at(t, 1, 0.86)), 1)
    for t in (0.45, 0.56, 0.67):
        x, y = cx, nose + blen * t
        pr = hw_max * 0.18
        pygame.draw.circle(surf, glass_rim, (int(x), int(y)), int(pr + 2))
        pygame.draw.circle(surf, glass, (int(x), int(y)), int(pr))
        pygame.draw.circle(surf, (255, 255, 255),
                           (int(x - pr * 0.4), int(y - pr * 0.4)),
                           max(1, int(pr * 0.30)))

    if rng.random() < 0.6:
        for t in (0.36, 0.50, 0.62, 0.74):
            x, y = at(t, 1, 0.72)
            art_dot = _blend(body, pal["ink"], 0.30)
            pygame.draw.circle(surf, art_dot, _pt((x, y)), 1)
    return surf


def _saucer_sprite(rng: random.Random, pal: dict[str, object],
                   radius: int) -> pygame.Surface:
    radius = max(8, int(radius))
    size = int(radius * 3.2)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size / 2.0
    hull = _blend(pal["paper"], pal["accent2"], 0.28)
    hull_dark = _blend(hull, pal["ink"], 0.58)
    hull_high = _blend(hull, (255, 255, 255), 0.55)

    _soft_circle(surf, cx, cy, radius * 1.35, pal["accent2"], 42)
    pygame.draw.ellipse(surf, hull_dark,
                        _rect(cx - radius * 1.18, cy - radius * 0.02,
                              radius * 2.36, radius * 0.62))
    pygame.draw.ellipse(surf, hull,
                        _rect(cx - radius * 1.35, cy - radius * 0.34,
                              radius * 2.70, radius * 0.70))
    pygame.draw.ellipse(surf, hull_dark,
                        _rect(cx - radius * 1.35, cy - radius * 0.34,
                              radius * 2.70, radius * 0.70),
                        max(1, int(radius * 0.06)))
    pygame.draw.arc(surf, hull_high,
                    _rect(cx - radius * 1.26, cy - radius * 0.31,
                          radius * 2.52, radius * 0.58),
                    math.radians(200), math.radians(340),
                    max(1, int(radius * 0.05)))

    dome = _blend(pal["accent2"], pal["sky_top"], 0.46)
    dome_rect = _rect(cx - radius * 0.62, cy - radius * 0.96,
                      radius * 1.24, radius * 0.96)
    pygame.draw.ellipse(surf, dome, dome_rect)
    pygame.draw.arc(surf, _blend(dome, pal["paper"], 0.65), dome_rect,
                    math.radians(100), math.radians(200),
                    max(1, int(radius * 0.04)))
    pygame.draw.ellipse(surf, hull_dark,
                        _rect(cx - radius * 0.66, cy - radius * 0.18,
                              radius * 1.32, radius * 0.22))

    lights = max(4, int(radius / 16))
    for i in range(lights):
        lx = cx - radius * 0.95 + (i / max(1, lights - 1)) * radius * 1.9
        ly = cy + radius * 0.16 - abs(lx - cx) * 0.03
        pygame.draw.circle(surf, pal["accent2"],
                           (int(lx), int(ly)), max(1, int(radius * 0.045)))
    pygame.draw.circle(surf, hull_dark,
                       (int(cx), int(cy + radius * 0.24)),
                       max(2, int(radius * 0.17)))
    pygame.draw.circle(surf, _blend(hull_dark, pal["paper"], 0.30),
                       (int(cx), int(cy + radius * 0.24)),
                       max(1, int(radius * 0.11)), 1)

    mast_x = cx + rng.uniform(-0.25, 0.25) * radius
    mast_top = cy - radius * 0.96
    pygame.draw.line(surf, hull_dark, (int(mast_x), int(mast_top)),
                     (int(mast_x), int(mast_top - radius * 0.22)), 1)
    pygame.draw.circle(surf, pal["accent2"],
                       (int(mast_x), int(mast_top - radius * 0.24)),
                       max(1, int(radius * 0.035)))
    return surf


def _robot_sprite(rng: random.Random, pal: dict[str, object], height: int,
                  dark: bool = False) -> pygame.Surface:
    """A boxy retro invader robot, drawn upright with its feet at the bottom.

    Silhouette first: the body reads against the sky, a lit rim picks it out
    on one side, and the eyes and chest reactor glow in the palette's second
    accent.  `dark` makes a near-black foreground copy for scale.
    """
    hh = float(max(18, height))
    pad = hh * 0.07
    surf = pygame.Surface((int(hh * 0.60), int(hh + pad)), pygame.SRCALPHA)
    cx = surf.get_width() / 2.0
    top = float(surf.get_height()) - hh

    def y(frac: float) -> float:
        return top + hh * frac

    if dark:
        body = _blend(pal["ink"], (0, 0, 0), 0.45)
        panel = _blend(body, pal["accent"], 0.10)
        edge = _blend(pal["rim"], pal["paper"], 0.30)
    else:
        body = _blend(pal["ink"], pal["accent"], 0.20)
        panel = _blend(body, pal["ink"], 0.45)
        edge = _blend(pal["rim"], pal["paper"], 0.10)
    glow = pal["accent2"]
    hot = _blend(glow, pal["paper"], 0.45)
    rim_w = max(1, int(hh * 0.009))

    # Legs and flared feet.
    _limb(surf, body, (cx - hh * 0.070, y(0.70)),
          (cx - hh * 0.088, y(0.985)), hh * 0.070)
    _limb(surf, body, (cx + hh * 0.070, y(0.70)),
          (cx + hh * 0.088, y(0.985)), hh * 0.070)
    pygame.draw.rect(surf, body,
                     _rect(cx - hh * 0.150, y(0.962), hh * 0.125,
                           hh * 0.034), border_radius=2)
    pygame.draw.rect(surf, body,
                     _rect(cx + hh * 0.025, y(0.962), hh * 0.125,
                           hh * 0.034), border_radius=2)

    # Arms hang behind the torso; pincer hands close below the hips.  A rim
    # on the outside of each limb keeps them from merging into the torso.
    for side in (-1, 1):
        shoulder = (cx + side * hh * 0.168, y(0.315))
        elbow = (cx + side * hh * 0.205, y(0.500))
        wrist = (cx + side * hh * 0.185, y(0.630))
        _limb(surf, body, shoulder, elbow, hh * 0.048)
        _limb(surf, body, elbow, wrist, hh * 0.042)
        for k in (-1, 0, 1):
            tip = (wrist[0] + k * hh * 0.028, wrist[1] + hh * 0.055)
            pygame.draw.line(surf, body, _pt(wrist), _pt(tip),
                             max(1, int(hh * 0.013)))
        pygame.draw.line(surf, edge,
                         _pt((shoulder[0] + side * hh * 0.027, shoulder[1])),
                         _pt((elbow[0] + side * hh * 0.025, elbow[1])), rim_w)
        pygame.draw.line(surf, edge,
                         _pt((elbow[0] + side * hh * 0.023, elbow[1])),
                         _pt((wrist[0] + side * hh * 0.022, wrist[1])), rim_w)

    # Tapered torso.
    pygame.draw.polygon(surf, body, _pts((
        (cx - hh * 0.125, y(0.270)), (cx + hh * 0.125, y(0.270)),
        (cx + hh * 0.095, y(0.710)), (cx - hh * 0.095, y(0.710)))))

    # Chest panel with vent slots and a reactor.
    pygame.draw.rect(surf, panel,
                     _rect(cx - hh * 0.075, y(0.330), hh * 0.150,
                           hh * 0.200), border_radius=2)
    vent = _blend(panel, pal["paper"], 0.30)
    for i in range(3):
        pygame.draw.rect(surf, vent,
                         _rect(cx - hh * 0.055, y(0.355 + i * 0.045),
                               hh * 0.110, hh * 0.012))
    reactor_y = y(0.600)
    _soft_circle(surf, cx, reactor_y, hh * 0.055, glow, 120)
    pygame.draw.circle(surf, glow, (int(cx), int(reactor_y)),
                       max(1, int(hh * 0.024)))
    pygame.draw.circle(surf, hot, (int(cx), int(reactor_y)),
                       max(1, int(hh * 0.010)))

    # Shoulder pads over the arm joints.
    pygame.draw.rect(surf, body,
                     _rect(cx - hh * 0.172, y(0.272), hh * 0.058,
                           hh * 0.086), border_radius=2)
    pygame.draw.rect(surf, body,
                     _rect(cx + hh * 0.114, y(0.272), hh * 0.058,
                           hh * 0.086), border_radius=2)

    # Neck and head.
    pygame.draw.rect(surf, body,
                     _rect(cx - hh * 0.035, y(0.240), hh * 0.070,
                           hh * 0.040))
    pygame.draw.rect(surf, body,
                     _rect(cx - hh * 0.105, y(0.098), hh * 0.210,
                           hh * 0.158),
                     border_radius=int(max(1, hh * 0.012)))

    eye_y = y(0.165)
    if rng.random() < 0.38:
        eyes = (cx,)
        eye_r = hh * 0.032
    else:
        eyes = (cx - hh * 0.052, cx + hh * 0.052)
        eye_r = hh * 0.022
    for ex in eyes:
        _soft_circle(surf, ex, eye_y, eye_r * 2.6, glow, 110)
        pygame.draw.circle(surf, glow, (int(ex), int(eye_y)),
                           max(1, int(eye_r)))
        pygame.draw.circle(surf, hot, (int(ex), int(eye_y)),
                           max(1, int(eye_r * 0.45)))

    # Mouth grille.
    for i in range(3):
        mx = cx + (i - 1) * hh * 0.028
        pygame.draw.line(surf, panel, (int(mx), int(y(0.212))),
                         (int(mx), int(y(0.234))),
                         max(1, int(hh * 0.008)))

    # Antenna.
    ax = cx + rng.uniform(-0.05, 0.05) * hh
    pygame.draw.line(surf, body, (int(ax), int(y(0.098))),
                     (int(ax), int(y(0.035))),
                     max(1, int(hh * 0.010)))
    pygame.draw.circle(surf, glow, (int(ax), int(y(0.030))),
                       max(1, int(hh * 0.014)))

    # Lit rim down the side facing the sky glow.
    pygame.draw.line(surf, edge,
                     (int(cx + hh * 0.121), int(y(0.283))),
                     (int(cx + hh * 0.092), int(y(0.700))), rim_w)
    pygame.draw.line(surf, edge,
                     (int(cx + hh * 0.101), int(y(0.112))),
                     (int(cx + hh * 0.101), int(y(0.240))), rim_w)
    return surf


def _limb(surf: pygame.Surface, colour: tuple[int, int, int],
          a: tuple[float, float], b: tuple[float, float],
          width: float) -> None:
    pygame.draw.line(surf, colour, _pt(a), _pt(b), max(1, int(width)))
    radius = max(1, int(width * 0.5))
    pygame.draw.circle(surf, colour, _pt(a), radius)
    pygame.draw.circle(surf, colour, _pt(b), radius)


def _astronaut_sprite(rng: random.Random, pal: dict[str, object], height: int,
                      pose: str, dark: bool) -> pygame.Surface:
    """A bubble-helmet astronaut, readable at 40 px and at 110 px."""
    hh = float(height)
    pad = 5
    surf = pygame.Surface((int(hh * 0.86) + pad * 2, int(hh) + pad * 2),
                          pygame.SRCALPHA)
    w = surf.get_width()
    cx = w / 2.0
    top = float(pad)
    foot = surf.get_height() - pad

    suit = pal["ink"] if dark else pal["paper"]
    shade = _blend(suit, pal["ink"], 0.38 if not dark else 0.0)
    boot = pal["ink"] if not dark else _blend(pal["ink"], pal["accent2"], 0.25)
    visor = _blend(pal["accent2"], pal["ink"], 0.30 if not dark else 0.55)
    detail = pal["accent2"] if dark else pal["accent"]
    dark_detail = _blend(pal["ink"], pal["accent2"], 0.18)

    def y(frac: float) -> float:
        return top + hh * frac

    hip_l, hip_r = (cx - hh * 0.058, y(0.57)), (cx + hh * 0.058, y(0.57))
    if pose == "walk":
        foot_l = (cx - hh * 0.135, foot)
        foot_r = (cx + hh * 0.105, foot - hh * 0.012)
    else:
        foot_l = (cx - hh * 0.072, foot)
        foot_r = (cx + hh * 0.072, foot)

    # Backpack and limbs, then the torso over them.
    pygame.draw.rect(surf, shade,
                     _rect(cx - hh * 0.155, y(0.265),
                           hh * 0.31, hh * 0.24), border_radius=3)
    _limb(surf, suit, hip_l, foot_l, hh * 0.092)
    _limb(surf, suit, hip_r, foot_r, hh * 0.092)
    pygame.draw.circle(surf, boot, _pt(foot_l), max(2, int(hh * 0.058)))
    pygame.draw.circle(surf, boot, _pt(foot_r), max(2, int(hh * 0.058)))

    shoulder_l = (cx - hh * 0.110, y(0.295))
    shoulder_r = (cx + hh * 0.110, y(0.295))
    down_l = (cx - hh * 0.165, y(0.555))
    down_r = (cx + hh * 0.165, y(0.555))
    if pose == "point":
        hand_l, hand_r = down_l, (cx + hh * 0.280, y(0.105))
    elif pose == "wave":
        hand_l, hand_r = down_l, (cx + hh * 0.300, y(0.200))
    elif pose == "up":
        hand_l, hand_r = (cx - hh * 0.270, y(0.070)), (cx + hh * 0.270, y(0.070))
    elif pose == "walk":
        hand_l, hand_r = (cx - hh * 0.205, y(0.500)), (cx + hh * 0.200, y(0.455))
    elif pose == "flag":
        hand_l, hand_r = down_l, (cx + hh * 0.220, y(0.520))
    else:
        hand_l, hand_r = down_l, down_r
    _limb(surf, suit, shoulder_l, hand_l, hh * 0.070)
    _limb(surf, suit, shoulder_r, hand_r, hh * 0.070)

    torso = [(cx - hh * 0.132, y(0.255)), (cx + hh * 0.132, y(0.255)),
             (cx + hh * 0.104, y(0.575)), (cx - hh * 0.104, y(0.575))]
    pygame.draw.polygon(surf, suit, _pts(torso))
    pygame.draw.rect(surf, shade,
                     _rect(cx - hh * 0.104, y(0.535),
                           hh * 0.208, hh * 0.040))
    pygame.draw.rect(surf, detail,
                     _rect(cx - hh * 0.058, y(0.335),
                           hh * 0.116, hh * 0.085), border_radius=1)
    pygame.draw.circle(surf, dark_detail,
                       (int(cx - hh * 0.022), int(y(0.365))),
                       max(1, int(hh * 0.010)))
    pygame.draw.circle(surf, pal["paper"] if dark else pal["ink"],
                       (int(cx + hh * 0.022), int(y(0.365))),
                       max(1, int(hh * 0.010)))

    # Helmet, visor and highlights.
    head_c = (cx, y(0.135))
    head_r = hh * 0.118
    pygame.draw.circle(surf, suit, _pt(head_c), int(head_r))
    pygame.draw.arc(surf, shade,
                    _rect(cx - head_r, y(0.135) - head_r,
                          head_r * 2, head_r * 2),
                    math.radians(200), math.radians(340),
                    max(1, int(hh * 0.018)))
    visor_rect = _rect(cx - head_r * 0.62, y(0.135) - head_r * 0.48,
                       head_r * 1.24, head_r * 0.92)
    pygame.draw.ellipse(surf, visor, visor_rect)
    pygame.draw.ellipse(surf, _blend(visor, pal["paper"], 0.35),
                        _rect(cx - head_r * 0.52, y(0.135) - head_r * 0.42,
                              head_r * 0.55, head_r * 0.30))
    pygame.draw.arc(surf, _blend(suit, pal["paper"], 0.55),
                    _rect(cx - head_r, y(0.135) - head_r,
                          head_r * 2, head_r * 2),
                    math.radians(105), math.radians(195),
                    max(1, int(hh * 0.016)))

    pygame.draw.line(surf, shade, (int(cx - hh * 0.11), int(y(0.265))),
                     (int(cx + hh * 0.11), int(y(0.265))),
                     max(1, int(hh * 0.014)))
    pygame.draw.line(surf, shade,
                     (int(cx - hh * 0.15), int(y(0.275))),
                     (int(cx - hh * 0.20), int(y(0.135))),
                     max(1, int(hh * 0.012)))
    pygame.draw.circle(surf, detail,
                       (int(cx - hh * 0.20), int(y(0.132))),
                       max(1, int(hh * 0.012)))

    if pose == "flag":
        pole_x = cx + hh * 0.220
        pygame.draw.line(surf, _blend(pal["paper"], pal["ink"], 0.25),
                         (int(pole_x), int(y(0.520))),
                         (int(pole_x), int(y(0.055))), 2)
        pygame.draw.polygon(surf, detail,
                            [(int(pole_x), int(y(0.060))),
                             (int(pole_x + hh * 0.175), int(y(0.105))),
                             (int(pole_x), int(y(0.155)))])
        pygame.draw.circle(surf, pal["paper"],
                           (int(pole_x + hh * 0.070), int(y(0.105))),
                           max(1, int(hh * 0.012)))
    return surf


def _place_astronaut(art: pygame.Surface, rng: random.Random,
                     pal: dict[str, object], x: float, foot_y: float,
                     height: int, pose: str, dark: bool) -> None:
    fig = _astronaut_sprite(rng, pal, height, pose, dark)
    mask = pygame.mask.from_surface(fig)

    def halo(colour: tuple[int, int, int],
             offsets) -> pygame.Surface:
        surf = pygame.Surface(fig.get_size(), pygame.SRCALPHA)
        silhouette = pygame.Surface(fig.get_size(), pygame.SRCALPHA)
        mask.to_surface(silhouette, setcolor=(*colour, 255),
                        unsetcolor=(0, 0, 0, 0))
        for dx, dy in offsets:
            surf.blit(silhouette, (dx, dy))
        return surf

    # A dark contour so the figure separates from bright planets, then a
    # light rim only on the side facing the key light.
    ink = tuple(int(c) for c in pal["ink"])
    contour = halo(ink, ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (2, 0), (-2, 0), (0, 2), (0, -2)))
    contour.blit(fig, (0, 0))
    rim = halo(tuple(int(c) for c in pal["rim"]),
               ((-1, -1), (-1, 0), (0, -1)))
    art.blit(contour, (int(x - fig.get_width() / 2),
                       int(foot_y - fig.get_height())))
    art.blit(rim, (int(x - fig.get_width() / 2),
                   int(foot_y - fig.get_height())))
    art.blit(fig, (int(x - fig.get_width() / 2),
                   int(foot_y - fig.get_height())))


def _trail(art: pygame.Surface, rng: random.Random,
           pal: dict[str, object], start: tuple[float, float],
           direction: tuple[float, float], length: float) -> None:
    """A soft exhaust plume, brightest at the nozzle and fading to smoke."""
    w, h = art.get_size()
    perp = (-direction[1], direction[0])
    curve = rng.uniform(-0.20, 0.20) * length
    n = 52
    pts: list[tuple[float, float]] = []
    for i in range(n):
        t = i / (n - 1)
        pts.append((start[0] - direction[0] * length * t
                    + perp[0] * curve * math.sin(math.pi * t),
                    start[1] - direction[1] * length * t
                    + perp[1] * curve * math.sin(math.pi * t)))

    plume = pygame.Surface((w, h), pygame.SRCALPHA)
    base_radius = _clamp(length * 0.052, 10.0, 26.0)

    def ribbon(radius_scale: float, colour_a: tuple[int, int, int],
               colour_b: tuple[int, int, int], alpha_a: int,
               alpha_b: int, span: float = 1.0) -> None:
        last = int((n - 1) * span)
        for i in range(last):
            t = i / (n - 1)
            t2 = (i + 1) / (n - 1)
            p0, p1 = pts[i], pts[i + 1]
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            dist = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / dist, dx / dist
            w0 = base_radius * radius_scale * (1.0 - t) ** 1.05 + 1.5
            w1 = base_radius * radius_scale * (1.0 - t2) ** 1.05 + 1.5
            colour = _blend(colour_a, colour_b,
                            min(1.0, t / max(1e-6, span)))
            alpha = int(alpha_a + (alpha_b - alpha_a)
                        * min(1.0, t / max(1e-6, span)))
            pygame.draw.polygon(
                plume, (*colour, alpha),
                _pts([(p0[0] + nx * w0, p0[1] + ny * w0),
                      (p1[0] + nx * w1, p1[1] + ny * w1),
                      (p1[0] - nx * w1, p1[1] - ny * w1),
                      (p0[0] - nx * w0, p0[1] - ny * w0)]))

    ribbon(1.7, pal["accent"], pal["sky_bottom"], 26, 0)
    ribbon(1.0, pal["accent"], pal["sky_bottom"], 96, 8)
    ribbon(0.28, (255, 246, 214), pal["accent"], 220, 0, span=0.42)
    art.blit(plume, (0, 0))


def _corona(art: pygame.Surface, rng: random.Random,
            pal: dict[str, object], cx: int, cy: int, radius: int) -> None:
    _soft_circle(art, cx, cy, radius * 1.06, pal["accent2"], 70)
    _soft_circle(art, cx, cy, radius * 1.34, pal["accent2"], 34)
    _soft_circle(art, cx, cy, radius * 1.78, pal["accent"], 18)
    for _ in range(rng.randint(16, 28)):
        ang = rng.uniform(0.0, math.tau)
        inner = radius * 1.02
        outer = radius * rng.uniform(1.12, 1.85)
        colour = _blend(pal["accent2"], pal["sky_top"],
                        rng.uniform(0.15, 0.55))
        pygame.draw.line(art, colour,
                         (int(cx + math.cos(ang) * inner),
                          int(cy + math.sin(ang) * inner)),
                         (int(cx + math.cos(ang) * outer),
                          int(cy + math.sin(ang) * outer)),
                         rng.choice((1, 1, 2)))
    pygame.draw.circle(art, _blend(pal["ink"], (0, 0, 0), 0.55),
                       (cx, cy), radius)
    pygame.draw.circle(art, _blend(pal["paper"], pal["accent2"], 0.45),
                       (cx, cy), radius, max(1, radius // 55))


# --------------------------------------------------------------------------- #
# Cover typography
# --------------------------------------------------------------------------- #

_FONTS: dict[tuple[int, bool], pygame.font.Font] = {}


def _display_font(size: int, serif: bool = False) -> pygame.font.Font:
    if not pygame.font.get_init():
        pygame.font.init()
    key = (int(size), bool(serif))
    if key not in _FONTS:
        name = "liberationserif" if serif else "liberationsans"
        _FONTS[key] = pygame.font.SysFont(name, size, bold=True)
    return _FONTS[key]


def _condense(surface: pygame.Surface, squeeze: float) -> pygame.Surface:
    if squeeze >= 0.99:
        return surface
    w, h = surface.get_size()
    return pygame.transform.smoothscale(surface, (max(1, int(w * squeeze)), h))


def _tracked(font: pygame.font.Font, text: str,
             colour: tuple[int, int, int], tracking: int = 2) -> pygame.Surface:
    glyphs = [font.render(ch, True, colour) for ch in text]
    height = max((g.get_height() for g in glyphs), default=1)
    width = sum(g.get_width() for g in glyphs) + tracking * max(0, len(glyphs) - 1)
    surf = pygame.Surface((max(1, width), height), pygame.SRCALPHA)
    x = 0
    for glyph in glyphs:
        surf.blit(glyph, (x, 0))
        x += glyph.get_width() + tracking
    return surf


def _cover_text(art: pygame.Surface, rng: random.Random,
                pal: dict[str, object]) -> None:
    w, h = art.get_size()

    # A soft ink wash behind the type, grounding the cover.
    band_h = int(h * 0.38)
    band = pygame.Surface((w, band_h), pygame.SRCALPHA)
    for i in range(band_h):
        alpha = int(132 * (i / max(1, band_h - 1)) ** 2.1)
        pygame.draw.line(band, (7, 6, 14, alpha), (0, i), (w, i))
    art.blit(band, (0, h - band_h))

    title = rng.choice(TITLES)
    words = title.split()
    if len(words) > 1 and rng.random() < 0.55:
        cut = rng.randint(1, len(words) - 1)
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    else:
        lines = [title]

    serif = rng.random() < 0.42
    target = w * 0.80
    start = 54 if len(lines) == 1 else 42
    font = _display_font(start, serif)
    squeeze = 1.0
    for size in range(start, 23, -2):
        font = _display_font(size, serif)
        widths = [font.size(line)[0] for line in lines]
        widest = max(widths) or 1
        squeeze = min(0.94, target / widest)
        if squeeze >= 0.64:
            break
    squeeze = max(0.55, squeeze)

    author_font = _display_font(12, False)
    tag_font = _display_font(10, False)
    author = _tracked(author_font, rng.choice(AUTHORS),
                      _blend(pal["paper"], pal["sky_bottom"], 0.26), 2)
    tagline = _tracked(tag_font, rng.choice(TAGLINES),
                       _blend(pal["accent2"], pal["sky_bottom"], 0.18), 2)

    line_h = int(font.get_linesize() * 0.94)
    block_h = (author.get_height() + 5 + len(lines) * line_h
               + 14 + tagline.get_height())
    top = h - 34 - block_h

    art.blit(author, (w // 2 - author.get_width() // 2, top))
    y = top + author.get_height() + 5
    tracking = max(1, font.get_height() // 24)
    warm_colour = _blend(pal["paper"], pal["sky_top"], 0.18)
    for line in lines:
        warm = _tracked(font, line, warm_colour, tracking)
        dark = _tracked(font, line, pal["ink"], tracking)
        fringe = _tracked(font, line, pal["accent"], tracking)
        for surface, dx, dy in ((dark, 3, 3), (fringe, 1, -1), (warm, 0, 0)):
            scaled = _condense(surface, squeeze)
            art.blit(scaled, (w // 2 - scaled.get_width() // 2, y + dy))
        y += line_h

    rule_y = y + 5
    rule_colour = _blend(pal["paper"], pal["accent"], 0.35)
    half = min(w * 0.30, 220)
    pygame.draw.line(art, rule_colour,
                     (w // 2 - half, rule_y), (w // 2 - 11, rule_y), 1)
    pygame.draw.line(art, rule_colour,
                     (w // 2 + 11, rule_y), (w // 2 + half, rule_y), 1)
    d = 4
    pygame.draw.polygon(art, pal["accent2"],
                        [(w // 2, rule_y - d), (w // 2 + d, rule_y),
                         (w // 2, rule_y + d), (w // 2 - d, rule_y)])
    art.blit(tagline, (w // 2 - tagline.get_width() // 2, rule_y + 6))

    tiny = _display_font(9, False)
    dim = _blend(pal["paper"], pal["sky_top"], 0.42)
    imprint = _tracked(tiny, rng.choice(IMPRINTS), dim, 2)
    art.blit(imprint, (w // 2 - imprint.get_width() // 2, h - 17))
    price = _tracked(tiny, rng.choice(PRICES), dim, 0)
    art.blit(price, (w - 30 - price.get_width(), h - 17))
    code = _tracked(tiny, f"{rng.choice('NSVX')}-{rng.randint(100, 199)}",
                    dim, 1)
    art.blit(code, (24, h - 17))


# --------------------------------------------------------------------------- #
# Compositions
# --------------------------------------------------------------------------- #

def _distant_craft(art: pygame.Surface, rng: random.Random,
                   pal: dict[str, object]) -> None:
    w, h = art.get_size()
    side = rng.choice((-1, 1))
    x = w * (rng.uniform(0.13, 0.26) if side < 0 else rng.uniform(0.74, 0.87))
    y = h * rng.uniform(0.09, 0.18)
    _soft_circle(art, x, y, h * 0.045, pal["accent2"], 22)
    if rng.random() < 0.6:
        length = rng.randint(int(h * 0.11), int(h * 0.17))
        sprite = _rocket_sprite(rng, pal, length)
        rot = pygame.transform.rotozoom(sprite, rng.uniform(-30, 30), 1.0)
    else:
        radius = rng.randint(int(w * 0.040), int(w * 0.062))
        sprite = _saucer_sprite(rng, pal, radius)
        rot = pygame.transform.rotozoom(sprite, rng.uniform(-10, 10), 1.0)
    art.blit(rot, rot.get_rect(center=(int(x), int(y))))


def _launch_pad(art: pygame.Surface, rng: random.Random,
                pal: dict[str, object], base_y: int) -> None:
    """A rocket lifting off beside a lattice gantry, wreathed in smoke."""
    w, h = art.get_size()
    height = int(h * rng.uniform(0.40, 0.50))
    side = rng.choice((-1, 1))
    cx = w * (rng.uniform(0.24, 0.39) if side < 0
              else rng.uniform(0.61, 0.76))
    sprite = _rocket_sprite(rng, pal, height)
    tail_y = base_y - h * 0.012
    center_y = tail_y - sprite.get_height() * 0.22
    gantry_x = cx - height * rng.uniform(0.38, 0.46)
    gantry_w = height * 0.15
    gantry_top = base_y - height * rng.uniform(0.66, 0.82)
    ink = _blend(pal["ink"], (0, 0, 0), 0.35)
    rim = _blend(pal["terrain_near"], pal["paper"], 0.30)

    # Smoke first so the rocket and tower sit in front of it.
    for _ in range(rng.randint(12, 19)):
        px = cx + rng.uniform(-1.7, 1.7) * height * 0.20
        py = base_y - rng.uniform(0.0, 0.18) * height
        rx = height * rng.uniform(0.08, 0.22)
        ry = height * rng.uniform(0.035, 0.085)
        tone = _blend(pal["paper"], pal["terrain_far"], rng.uniform(0.25, 0.65))
        _soft_ellipse(art, px, py, rx, ry, tone, rng.randint(70, 125))
    _soft_circle(art, cx, tail_y, height * 0.24, pal["accent"], 100)

    # Lattice gantry.
    pygame.draw.rect(art, ink, _rect(gantry_x, gantry_top,
                                     gantry_w, base_y - gantry_top))
    for i in range(1, 6):
        gy = gantry_top + (base_y - gantry_top) * i / 6
        pygame.draw.line(art, rim, (int(gantry_x), int(gy)),
                         (int(gantry_x + gantry_w), int(gy)), 1)
    for i in range(5):
        gx = gantry_x + gantry_w * i / 5
        pygame.draw.line(art, ink, (int(gx), int(gantry_top)),
                         (int(gx), int(base_y)), 2)
        pygame.draw.line(art, rim, (int(gx), int(gantry_top)),
                         (int(gx), int(base_y)), 1)
    # Swing arm reaching to the hull.
    arm_y = gantry_top + (base_y - gantry_top) * rng.uniform(0.30, 0.55)
    pygame.draw.line(art, ink, (int(gantry_x + gantry_w), int(arm_y)),
                     (int(cx - height * 0.17), int(arm_y)), 3)
    pygame.draw.line(art, rim, (int(gantry_x + gantry_w), int(arm_y - 1)),
                     (int(cx - height * 0.17), int(arm_y - 1)), 1)
    for _ in range(rng.randint(2, 4)):
        ly = rng.uniform(gantry_top + 6, base_y - 6)
        art.fill(pal["accent"], (int(gantry_x + gantry_w * 0.5),
                                 int(ly), 2, 2))

    art.blit(sprite, (int(cx - sprite.get_width() / 2),
                      int(center_y - sprite.get_height() / 2)))


def _scene_rocket(art: pygame.Surface, rng: random.Random,
                  pal: dict[str, object]) -> None:
    w, h = art.get_size()
    radius = int(h * rng.uniform(0.17, 0.30))
    # Sometimes let the world run off the top or side of the frame.
    bleed = rng.random() < 0.30
    if bleed and rng.random() < 0.5:
        cx = -radius // 3 if rng.random() < 0.5 else w + radius // 3
        cy = int(h * rng.uniform(0.10, 0.24))
    else:
        cx = int(rng.uniform(radius * 0.6, w - radius * 0.6))
        cy = int(rng.uniform(radius * 0.55, h * 0.40))
    ringed = rng.random() < 0.32 and radius > 100

    if ringed:
        _rings(art, pal, cx, cy, radius, False)
    _planet(art, rng, pal, cx, cy, radius,
            bands=rng.random() < 0.6, craters=rng.random() < 0.4)
    if ringed:
        _rings(art, pal, cx, cy, radius, True)

    if rng.random() < 0.6:
        moon_r = rng.randint(int(h * 0.025), int(h * 0.05))
        mx = rng.randint(moon_r, w - moon_r)
        my = rng.randint(moon_r, int(h * 0.30))
        if abs(mx - cx) + abs(my - cy) > radius + moon_r + 20:
            _planet(art, rng, pal, mx, my, moon_r, craters=True)

    if rng.random() < 0.45:
        _orbit_arc(art, rng, pal, cx, cy, int(radius * 1.55))
    if rng.random() < 0.5:
        _comet(art, rng, pal)

    launch = rng.random() < 0.34
    if launch:
        far_y = int(h * rng.uniform(0.56, 0.60))
        near_y = int(h * rng.uniform(0.63, 0.675))
    else:
        far_y = int(h * rng.uniform(0.65, 0.70))
        near_y = int(h * rng.uniform(0.71, 0.765))
    _ridge(art, rng, pal, far_y, 18, pal["terrain_far"], rim=False)
    _ridge(art, rng, pal, near_y, 16, pal["terrain_near"],
           craters=rng.random() < 0.45)
    _foreground_flora(art, rng, pal, near_y + 5)

    if launch:
        _launch_pad(art, rng, pal, near_y - 2)
    else:
        height = int(h * rng.uniform(0.38, 0.52))
        angle = rng.choice((-32, -22, -12, 12, 22, 32))
        radians = math.radians(angle)
        direction = (-math.sin(radians), -math.cos(radians))
        nose_x = w * rng.uniform(0.32, 0.68)
        nose_y = h * rng.uniform(0.13, 0.23)
        center = (nose_x - direction[0] * height * 0.42,
                  nose_y - direction[1] * height * 0.42)
        start = (center[0] - direction[0] * height * 0.55,
                 center[1] - direction[1] * height * 0.55)
        _soft_circle(art, center[0], center[1], height * 0.62,
                     pal["accent"], 26)
        _trail(art, rng, pal, start, direction,
               height * rng.uniform(1.05, 1.4))
        sprite = _rocket_sprite(rng, pal, height)
        rotated = pygame.transform.rotozoom(sprite, angle, 1.0)
        art.blit(rotated, rotated.get_rect(center=(int(center[0]),
                                                   int(center[1]))))

    dark = _lum(pal["planet_light"]) > 0.56
    side = rng.choice((-1, 1))
    x = w * (rng.uniform(0.09, 0.19) if side < 0
             else rng.uniform(0.81, 0.91))
    pose = rng.choice(("stand", "point", "wave", "flag"))
    _place_astronaut(art, rng, pal, x, near_y + 2,
                     int(h * rng.uniform(0.15, 0.21)), pose, dark)
    if rng.random() < 0.35:
        x2 = w * (rng.uniform(0.82, 0.90) if side < 0
                  else rng.uniform(0.10, 0.18))
        _place_astronaut(art, rng, pal, x2, near_y + 2,
                         int(h * rng.uniform(0.12, 0.16)),
                         rng.choice(("stand", "point")), dark)


def _scene_astronaut(art: pygame.Surface, rng: random.Random,
                     pal: dict[str, object]) -> None:
    w, h = art.get_size()
    radius = int(h * rng.uniform(0.34, 0.48))
    cx = int(w * rng.uniform(0.28, 0.72))
    cy = int(h * rng.uniform(0.52, 0.62))
    ringed = rng.random() < 0.30 and radius > 140

    if ringed:
        _rings(art, pal, cx, cy, radius, False)
    _planet(art, rng, pal, cx, cy, radius,
            bands=rng.random() < 0.7, craters=rng.random() < 0.35)
    if ringed:
        _rings(art, pal, cx, cy, radius, True)
    if rng.random() < 0.35:
        _orbit_arc(art, rng, pal, cx, cy, int(radius * 1.35))

    if rng.random() < 0.85:
        _distant_craft(art, rng, pal)

    horizon = int(h * rng.uniform(0.60, 0.65))
    _city(art, rng, pal, horizon, scale=rng.uniform(0.8, 1.05))
    far_y = int(h * rng.uniform(0.66, 0.69))
    near_y = int(h * rng.uniform(0.69, 0.73))
    _ridge(art, rng, pal, far_y, 11, pal["terrain_mid"], rim=False)
    _ridge(art, rng, pal, near_y, 12, pal["terrain_near"],
           craters=rng.random() < 0.5)
    _foreground_flora(art, rng, pal, near_y + 5)

    dark = _lum(pal["planet_light"]) > 0.60
    slots = rng.sample(((0.08, 0.17), (0.83, 0.92), (0.19, 0.27)), 2)
    count = rng.choice((1, 2, 2))
    for low, high in slots[:count]:
        pose = rng.choice(("stand", "point", "flag", "wave"))
        _place_astronaut(art, rng, pal, w * rng.uniform(low, high),
                         near_y + 2,
                         int(h * rng.uniform(0.17, 0.24)), pose, dark)
    if rng.random() < 0.45:
        # A big near-silhouette to give the panorama some scale.
        side = rng.choice((-1, 1))
        x = w * (rng.uniform(0.06, 0.13) if side < 0
                 else rng.uniform(0.87, 0.94))
        _place_astronaut(art, rng, pal, x, near_y + 8,
                         int(h * rng.uniform(0.26, 0.33)),
                         rng.choice(("stand", "point")), True)


def _scene_saucer(art: pygame.Surface, rng: random.Random,
                  pal: dict[str, object]) -> None:
    w, h = art.get_size()
    moon_r = int(h * rng.uniform(0.045, 0.08))
    side = rng.choice((-1, 1))
    mx = int(w * (rng.uniform(0.12, 0.24) if side < 0
                  else rng.uniform(0.76, 0.88)))
    my = int(h * rng.uniform(0.10, 0.18))
    _planet(art, rng, pal, mx, my, moon_r, craters=True)
    if rng.random() < 0.45:
        _comet(art, rng, pal)

    ground = int(h * rng.uniform(0.60, 0.66))
    radius = int(w * rng.uniform(0.075, 0.115))
    sx = w * rng.uniform(0.30, 0.70)
    if rng.random() < 0.28:
        # Hovering low over the skyline, about to set down.
        sy = ground - radius * rng.uniform(0.55, 0.95)
    else:
        sy = h * rng.uniform(0.14, 0.24)

    sprite = _saucer_sprite(rng, pal, radius)
    rotated = pygame.transform.rotozoom(sprite, rng.uniform(-9, 9), 1.0)
    art.blit(rotated, rotated.get_rect(center=(int(sx), int(sy))))

    # Escorts in formation on some covers.
    if rng.random() < 0.38:
        for _ in range(rng.randint(1, 2)):
            small = _saucer_sprite(rng, pal,
                                   max(9, int(radius * rng.uniform(0.34, 0.52))))
            ox = sx + rng.choice((-1, 1)) * radius * rng.uniform(1.6, 2.8)
            oy = sy + rng.uniform(-0.9, 0.7) * radius
            art.blit(pygame.transform.rotozoom(small, rng.uniform(-10, 10), 1.0),
                     (int(ox), int(oy)))

    if rng.random() < 0.60:
        _beam(art, rng, pal, sx, int(sy + radius * 0.22), ground,
              radius * 0.55, radius * 2.0)
    _city(art, rng, pal, ground, scale=rng.uniform(0.82, 1.12))

    far_y = int(h * (ground / h + 0.045))
    near_y = int(h * (ground / h + 0.085))
    _ridge(art, rng, pal, far_y, 10, pal["terrain_mid"], rim=False)
    _ridge(art, rng, pal, near_y, 12, pal["terrain_near"],
           craters=rng.random() < 0.4)
    _foreground_flora(art, rng, pal, near_y + 5)

    dark = _lum(pal["planet_light"]) > 0.60
    for _ in range(rng.choice((1, 1, 2))):
        side = rng.choice((-1, 1))
        x = w * (rng.uniform(0.09, 0.22) if side < 0
                 else rng.uniform(0.78, 0.91))
        _place_astronaut(art, rng, pal, x, near_y + 2,
                         int(h * rng.uniform(0.13, 0.19)),
                         rng.choice(("up", "stand", "wave")), dark)


def _scene_robots(art: pygame.Surface, rng: random.Random,
                  pal: dict[str, object]) -> None:
    """A robot invasion: boxy machines standing over the domed city."""
    w, h = art.get_size()

    moon_r = int(h * rng.uniform(0.045, 0.075))
    side = rng.choice((-1, 1))
    mx = int(w * (rng.uniform(0.12, 0.24) if side < 0
                  else rng.uniform(0.76, 0.88)))
    my = int(h * rng.uniform(0.09, 0.17))
    _planet(art, rng, pal, mx, my, moon_r, craters=True)
    if rng.random() < 0.5:
        _comet(art, rng, pal)

    ground = int(h * rng.uniform(0.66, 0.71))
    _city(art, rng, pal, ground, scale=rng.uniform(0.78, 1.06))

    # Searchlights hunt the sky behind the machines.
    for _ in range(rng.randint(1, 3)):
        _searchlight(art, rng, pal, w * rng.uniform(0.06, 0.94), ground,
                     h * rng.uniform(0.55, 0.85))

    # A saucer supervising the work.
    if rng.random() < 0.32:
        radius = int(w * rng.uniform(0.040, 0.058))
        sx = w * rng.uniform(0.22, 0.78)
        sy = ground - radius * rng.uniform(2.2, 3.4)
        sprite = _saucer_sprite(rng, pal, radius)
        art.blit(sprite, sprite.get_rect(center=(int(sx), int(sy))))

    far_y = int(h * (ground / h + 0.035))
    near_y = int(h * (ground / h + 0.068))
    slots = rng.sample(((0.14, 0.30), (0.42, 0.58), (0.70, 0.86)),
                       rng.choice((1, 2, 2)))
    for low, high in slots:
        height = int(h * rng.uniform(0.25, 0.38))
        sprite = _robot_sprite(rng, pal, height)
        if rng.random() < 0.5:
            sprite = pygame.transform.flip(sprite, True, False)
        art.blit(sprite, sprite.get_rect(
            midbottom=(int(w * rng.uniform(low, high)),
                       far_y + int(height * 0.04))))

    _ridge(art, rng, pal, far_y, 10, pal["terrain_far"], rim=False)
    _ridge(art, rng, pal, near_y, 12, pal["terrain_near"],
           craters=rng.random() < 0.45)

    # One machine right up against the camera for scale.
    if rng.random() < 0.68:
        height = int(h * rng.uniform(0.48, 0.66))
        sprite = _robot_sprite(rng, pal, height, dark=True)
        near_side = rng.choice((-1, 1))
        if near_side > 0:
            sprite = pygame.transform.flip(sprite, True, False)
        x = w * (rng.uniform(0.09, 0.21) if near_side < 0
                 else rng.uniform(0.79, 0.91))
        art.blit(sprite, sprite.get_rect(
            midbottom=(int(x), int(h + height * 0.10))))

    _foreground_flora(art, rng, pal, near_y + 5)


def _scene_ringed(art: pygame.Surface, rng: random.Random,
                  pal: dict[str, object]) -> None:
    w, h = art.get_size()
    radius = int(h * rng.uniform(0.33, 0.44))
    cx = int(w * rng.uniform(0.32, 0.68))
    cy = int(h * rng.uniform(0.32, 0.42))

    _rings(art, pal, cx, cy, radius, False)
    _planet(art, rng, pal, cx, cy, radius, bands=True)
    _rings(art, pal, cx, cy, radius, True)
    if rng.random() < 0.5:
        _orbit_arc(art, rng, pal, cx, cy, int(radius * 1.9))
    if rng.random() < 0.6:
        _comet(art, rng, pal)

    far_y = int(h * rng.uniform(0.71, 0.74))
    near_y = int(h * rng.uniform(0.75, 0.78))
    _ridge(art, rng, pal, far_y, 8, pal["terrain_far"], rim=False)
    _ridge(art, rng, pal, near_y, 9, pal["terrain_near"],
           craters=rng.random() < 0.4)
    _foreground_flora(art, rng, pal, near_y + 5)

    for _ in range(rng.choice((1, 1, 2))):
        height = int(h * rng.uniform(0.16, 0.23))
        angle = rng.choice((-72, -58, 58, 72))
        radians = math.radians(angle)
        direction = (-math.sin(radians), -math.cos(radians))
        center = (w * rng.uniform(0.38, 0.62), h * rng.uniform(0.48, 0.56))
        start = (center[0] - direction[0] * height * 0.55,
                 center[1] - direction[1] * height * 0.55)
        _trail(art, rng, pal, start, direction, height * 1.25)
        sprite = _rocket_sprite(rng, pal, height)
        rotated = pygame.transform.rotozoom(sprite, angle, 1.0)
        art.blit(rotated, rotated.get_rect(center=(int(center[0]),
                                                   int(center[1]))))

    side = rng.choice((-1, 1))
    x = w * (rng.uniform(0.09, 0.17) if side < 0
             else rng.uniform(0.83, 0.91))
    _place_astronaut(art, rng, pal, x, near_y + 2,
                     int(h * rng.uniform(0.11, 0.15)),
                     rng.choice(("stand", "point", "flag")),
                     dark=_lum(pal["planet_light"]) > 0.58)


def _scene_eclipse(art: pygame.Surface, rng: random.Random,
                   pal: dict[str, object]) -> None:
    w, h = art.get_size()
    radius = int(h * rng.uniform(0.22, 0.32))
    cx = int(w * rng.uniform(0.32, 0.68))
    cy = int(h * rng.uniform(0.22, 0.31))
    _corona(art, rng, pal, cx, cy, radius)

    if rng.random() < 0.85:
        height = int(h * rng.uniform(0.16, 0.23))
        angle = rng.choice((-82, -68, 68, 82))
        centered_y = cy + radius * rng.uniform(-0.15, 0.45)
        centered_x = cx + radius * rng.uniform(-0.65, 0.65)
        sprite = _rocket_sprite(rng, pal, height, dark=True)
        rotated = pygame.transform.rotozoom(sprite, angle, 1.0)
        art.blit(rotated, rotated.get_rect(center=(int(centered_x),
                                                   int(centered_y))))

    far_y = int(h * rng.uniform(0.69, 0.725))
    near_y = int(h * rng.uniform(0.735, 0.77))
    _ridge(art, rng, pal, far_y, 10, pal["terrain_far"], rim=False)
    _ridge(art, rng, pal, near_y, 11, pal["terrain_near"],
           craters=rng.random() < 0.5)
    _foreground_flora(art, rng, pal, near_y + 5)

    dark = _lum(pal["planet_light"]) > 0.60
    side = rng.choice((-1, 1))
    x = w * (rng.uniform(0.08, 0.18) if side < 0
             else rng.uniform(0.82, 0.92))
    _place_astronaut(art, rng, pal, x, near_y + 4,
                     int(h * rng.uniform(0.20, 0.27)),
                     rng.choice(("up", "point")), True)
    if rng.random() < 0.5:
        x2 = w * (rng.uniform(0.80, 0.90) if side < 0
                  else rng.uniform(0.10, 0.20))
        _place_astronaut(art, rng, pal, x2, near_y + 2,
                         int(h * rng.uniform(0.11, 0.15)),
                         rng.choice(("stand", "wave")), dark)


# --------------------------------------------------------------------------- #
# Print aging and public entry point
# --------------------------------------------------------------------------- #

def _age(art: pygame.Surface, rng: random.Random,
         pal: dict[str, object]) -> None:
    """Fake halftone, grain, misregistration, creases and edge wear."""
    w, h = art.get_size()
    npr = np.random.default_rng(rng.getrandbits(63))
    arr = pygame.surfarray.array3d(art).astype(np.float32)

    arr *= np.array([1.035, 1.0, 0.955], dtype=np.float32)
    arr += 2.5

    dx = rng.choice((-1, 1))
    arr[..., 0] = 0.74 * arr[..., 0] + 0.26 * np.roll(arr[..., 0], dx, axis=0)
    arr[..., 2] = 0.80 * arr[..., 2] + 0.20 * np.roll(arr[..., 2], -dx, axis=1)

    xs = np.arange(w, dtype=np.float32)[:, None]
    ys = np.arange(h, dtype=np.float32)[None, :]

    screen = 0.5 + 0.5 * np.sin((xs + ys) * (math.tau / 3.6))
    arr *= (0.978 + 0.044 * screen)[..., None]
    arr += npr.normal(0.0, 4.2, (w, h)).astype(np.float32)[..., None]

    # Low-frequency paper mottling: cheap blur of a 10x8 noise field.
    low = pygame.Surface((10, 8))
    grain = npr.normal(128.0, 12.0, (10, 8)).clip(0, 255).astype(np.uint8)
    pygame.surfarray.blit_array(low, np.repeat(grain[:, :, None], 3, axis=2))
    mott = (pygame.surfarray.array3d(
        pygame.transform.smoothscale(low, (w, h)))[..., 0].astype(np.float32)
        - 128.0) / 128.0
    arr *= (1.0 + 0.055 * mott)[..., None]

    for _ in range(rng.randint(1, 2)):
        x0 = rng.uniform(0.06, 0.94) * w
        sigma = rng.uniform(0.8, 2.2)
        profile = np.exp(-((xs - x0) / sigma) ** 2)
        arr *= (1.0 - 0.080 * profile)[..., None]
        arr += (5.0 * profile)[..., None]

    nx = xs / (w - 1) * 2.0 - 1.0
    ny = ys / (h - 1) * 2.0 - 1.0
    radial = np.sqrt(nx * nx * 0.90 + ny * ny)
    vignette = np.clip(1.0 - 0.26 * np.clip(radial - 0.52, 0, None) ** 1.5,
                       0.50, 1.0)
    arr *= vignette[..., None]

    pygame.surfarray.blit_array(art, np.clip(arr, 0, 255).astype(np.uint8))

    for _ in range(rng.randint(0, 4)):
        spot_r = rng.randint(6, 20)
        spot = pygame.Surface((spot_r * 2, spot_r * 2), pygame.SRCALPHA)
        pygame.draw.circle(spot, (96, 66, 42, rng.randint(8, 18)),
                           (spot_r, spot_r), spot_r)
        art.blit(spot, (rng.randrange(w), rng.randrange(h)))


# Scene name, painter, and how often it appears (weights need not sum to 100).
SCENES = (
    ("rocket", _scene_rocket, 26),
    ("astronaut", _scene_astronaut, 24),
    ("saucer", _scene_saucer, 18),
    ("robots", _scene_robots, 12),
    ("ringed", _scene_ringed, 11),
    ("eclipse", _scene_eclipse, 9),
)
SCENE_NAMES = tuple(name for name, _paint, _weight in SCENES)
SCENE_WEIGHTS = tuple(weight for _name, _paint, weight in SCENES)
SCENE_PAINTERS = {name: paint for name, paint, _weight in SCENES}


def make_cover(rng: random.Random, width: int = 800,
               height: int = 600) -> pygame.Surface:
    """Paint one fresh 1960s paperback cover, dimmed for gameplay."""
    pal = _palette(rng)
    art = _gradient(width, height, pal["sky_top"], pal["sky_bottom"],
                    rng.uniform(1.05, 1.45))
    _nebula(art, rng, pal)
    _soft_ellipse(art, width * 0.5, height * 0.63,
                  width * 0.78, height * 0.30, pal["accent2"], 24)
    if rng.random() < 0.6:
        _soft_ellipse(art, width * rng.uniform(0.18, 0.82),
                      height * 0.52, width * 0.55, height * 0.34,
                      pal["accent"], 15)
    _stars(art, rng, pal, rng.randint(140, 250), max_y=height * 0.9)

    scene = rng.choices(SCENE_NAMES, weights=SCENE_WEIGHTS, k=1)[0]
    SCENE_PAINTERS[scene](art, rng, pal)

    _cover_text(art, rng, pal)
    _age(art, rng, pal)
    art.set_alpha(rng.randint(58, 76))
    return art
