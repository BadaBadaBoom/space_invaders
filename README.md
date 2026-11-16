# Space Invaders

A Space Invaders clone in Python/pygame, with destructible bunkers, floating
avatar hazards, fullscreen scaling, a **procedurally painted 1960s sci-fi
paperback cover for every wave**, and a **procedurally composed soundtrack that
changes genre from wave to wave**.

Graphics are drawn with primitives, sound effects are square-wave blips, and the
music is synthesized from scratch at runtime. The only optional asset is the
avatar sheet used for the hazards.

```
main.py        bootstrap, CLI, input, and the event loop
config.py      constants, colours, and file paths
deps.py        optional music/covers/numpy imports
assets.py      fonts, avatar tiles, cover delegation, tone blips
entities.py    bullets, aliens, player, bunkers, avatar hazards
leaderboard.py persistent top-100 table
audio.py       MusicPlayer worker thread and mixer channels
render.py      RenderMixin: playfield, HUD, leaderboard, overlays
game.py        Game state, collisions, waves, and scoring
selftest.py    headless smoke tests and invariant checks
covers.py      procedural 1960s paperback-cover painter
music.py       genre composers / synthesizer
```

Dependencies point one way:

```text
config -> assets -> entities -> render -> game -> main
leaderboard ------------------^
audio ------------------------^
```

That keeps each concern in its own file, so parallel work can be split by
module without two editors touching the same code.

### Parallel lanes

Each lane is a branch plus a worktree, with an agent that can only edit that
lane's files:

| Lane | Branch / worktree | Owns | Agent |
| --- | --- | --- | --- |
| covers | `covers` / `~/si-covers` | `covers.py` | `covers` |
| music | `music` / `~/si-music` | `music.py`, `audio.py` | `music` |
| gameplay | `gameplay` / `~/si-gameplay` | `game.py`, `entities.py` | `gameplay` |
| ui | `ui` / `~/si-ui` | `render.py` | `ui` |

The agent definitions live in `.opencode/agents/`. They deny `edit`, `write`,
and `patch` on everything except the owned files, so a lane cannot change
another module or a shared file by accident. Launch one per worktree:

```bash
cd ~/si-covers
opencode run --agent covers "make the ringed-giant covers rarer"
```

Shared files (`main.py`, `config.py`, `deps.py`, `assets.py`,
`leaderboard.py`, `selftest.py`, `README.md`) belong to the integration
session in `~/space_invaders`. Lanes commit on their own branch; integration
merges them into `main` after the selftest passes.

The `integrate` agent runs that side of the workflow. It has full edit rights
on `main` and a merge checklist: inspect the lane, run its gates, merge with
`--no-ff`, run the full gate, then fast-forward the other lanes.

```bash
cd ~/space_invaders
opencode run --agent integrate "merge the covers lane"
```


## Run

```bash
cd space_invaders
python main.py
```

`main.py` will re-launch itself inside `.venv` if the interpreter you used
doesn't have pygame, so this works with plain `python`, `python3`, or an
activated venv. To be explicit:

```bash
.venv/bin/python main.py
```

From scratch on another machine:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

The music needs **numpy**; without it the game still runs, with sound effects
and painted backdrops, but no soundtrack.

## Controls

| Key | Action |
| --- | --- |
| `←` / `→` or `A` / `D` | Move |
| `Space` | Fire (max 3 shots on screen) |
| `P` | Pause / resume |
| `L` | High-score leaderboard (up/down to scroll) |
| `M` | Mute / unmute music |
| `-` / `=` | Music volume down / up (10% steps) |
| `F11` or `Alt+Enter` | Fullscreen on/off |
| `Enter` | Start / restart (composes a new song) |
| `Esc` | Leave fullscreen, or quit |

## The soundtrack

There are no audio files. On launch — and again every time you start a game or
clear a wave — `music.py` composes a brand-new track from a random seed and
renders it to raw 16-bit stereo PCM, which is then looped on a reserved mixer
channel and crossfaded in.

Every wave gets a different **genre**, drawn from a shuffled bag so all seven
play before any repeats, and two waves in a row never share one:

| Genre | Character |
| --- | --- |
| `metal` | double-kick riffs, distorted power chords, a squealing solo |
| `synthwave` | neon arpeggios, gated snares, widescreen pads |
| `chiptune` | fast pulse arpeggios, blocky bass, noise-channel drums |
| `funk` | syncopated slap bass, clav scratches, tight pocket drums |
| `jazz` | walking bass, swung ride cymbal, smoky e-piano comping |
| `ambient` | slow drifting pads, sub-bass, distant bells |
| `disco` | four-on-the-floor kick, octave bass, sweeping string stabs |

Within a genre, each composition randomizes:

- **tempo** and **key** (E2 root, one of several scales per genre)
- **motif-based melodies**: a one-bar idea is remembered, repeated and varied
  every two bars instead of wandering randomly; sections transpose it with the
  chord progression
- **song form**: intro, main sections, a solo or breakdown, outro, with
  quieter intros, louder choruses, risers and fills at section changes
- **humanised drums**: velocity and timing jitter, ghost notes, two-bar
  pattern variations and genre-specific swing
- **instrument voicings** (detuned band-limited saws, pulse waves, FM e-piano,
  horns, bells, noise percussion)

Synthesis uses **PolyBLEP band-limited saw and pulse oscillators at 44100 Hz**
so high notes and distorted chords stay clean instead of aliasing.  The mix is
fully stereo: mono buses are panned with constant-power law, sent to a stereo
Schroeder reverb and a tempo-synced ping-pong delay (dotted eighths), then
glued with kick sidechain ducking, bus compression, a presence EQ, RMS
targeting and a soft limiter.  A gentle mid/side lift widens the reverb and
panned parts while keeping the bass and kick solid in mono.

Rendering takes roughly 1–6 s depending on the genre and length, runs on a
worker thread, and never stalls the game.  The current genre is shown under
the wave number in the HUD.

Useful flags:

```bash
python main.py --no-music                    # silence the soundtrack
python main.py --music-volume 0.5            # louder music
python main.py --export-music riff.wav       # render one random track and exit
python main.py --export-music jazz.wav --export-genre jazz
```

`--export-music` is the easy way to audition the generator without playing.
Without `--export-genre` the genre is chosen at random.

## Avatar hazards

`~/avatars/image_79efc5be.jpeg` is a 3×2 contact sheet of six round badges.
At startup the game slices it into six individual sprites (46×46 px — a little
larger than an alien ship, 34×24). The sheet's flat white background is cut
away outside each badge circle, so the artwork inside keeps its white details,
and the most common vivid colours of each badge are sampled to tint its
explosion.

Shortly after each wave begins, a badge starts floating across the arena; it
moves in a straight line at 70–125 px/s and **bounces off the four walls,
the alien formation and the bunkers**, never stopping. Every 4.5 s after one
dies, another appears. The limit is the wave number: **one badge on wave 1,
two on wave 2, three on wave 3**, and so on. Spawns are placed in open space,
below the formation and above the bunkers.

Only two things can destroy a badge — your bullet, or your ship:

| Collides with | Badge | Other party |
| --- | --- | --- |
| Your bullet | Explodes, **+50 points** | Bullet is consumed |
| Player ship | Explodes | You lose a life |
| Bunker | Ricochets off | A round bite is erased |
| Alien | Ricochets off | Unharmed |
| Alien bullet | Floats on | Bullet is consumed |

When a badge does die it explodes in a burst of debris, expanding rings and
flashes coloured from its own palette.

If the sheet is missing the game simply runs without hazards. Point it
elsewhere with:

```bash
SPACE_INVADERS_AVATARS=/path/to/sheet.jpeg python main.py
```

## 1960s cover art backdrops

Every wave paints a new 800×600 backdrop in the style of a 1960s
science-fiction paperback cover. `covers.make_cover` (called through
`make_pulp_background`) uses only pygame primitives and numpy, so the covers
are different every wave and deterministic for a given seed.

Each cover starts from one of eight limited period palettes (ember, teal,
violet, acid, ultra, rust, cobalt, mint), jittered per painting and sometimes
washed into a bright matte-painting sky. It then paints one of five
compositions:

- a finned rocket climbing past a world, or lifting off beside a lattice
  gantry in a cloud of smoke
- bubble-helmet astronauts on a ridge above a lit domed city
- a flying saucer and its escorts over the skyline, with or without a light
  beam
- a banded ringed giant with rings drawn behind and in front of the disc
- a total eclipse with a coronal glow and a silhouetted ship

Supporting elements include lit domes, setback towers and needle spires,
jagged ridge lines with rim light and craters, deserts with alien flora,
moons, comets, orbit arcs and distant craft. The planets are shaded with a
real light direction and latitude-band curvature, and the figures cast a
dark contour plus a light rim so they read against both sky and planet.

The type block is period typesetting: a tracked condensed title with offset
accent/shadow misregistration, an author line, a rule and diamond, a tagline,
plus imprint, price and code marks. Finally a print-aging pass composites a
halftone screen, film grain, low-frequency paper mottling, channel
misregistration, a fold crease, foxing spots and a vignette.

The finished cover is dimmed to alpha 58–76, so it sits behind the aliens,
avatars, bullets and bunkers without harming readability. A new one is painted
at each wave start and takes roughly 0.3–0.5 s. If numpy is unavailable the
game falls back to a simple gradient backdrop.

## Fullscreen and scaling

The game always draws into a fixed 800×600 canvas, then scales that canvas to
whatever the window is, preserving the 4:3 aspect ratio and adding black bars
(letterboxing) when needed. Everything — text, ships, bunkers, particles —
grows together on a big display.

- `F11` or `Alt+Enter` toggles fullscreen at the desktop resolution.
- The window is resizable; drag it and the view scales with it.

## What's in it

- 4 rows × 8 aliens, each row worth a different number of points
- The whole formation marches side to side and drops at the walls; it speeds up
  as you thin out the ranks
- Only the front-most alien in each column can shoot, so hiding behind a
  cleared column actually works
- **Four destructible bunkers**: each is a grid of ~300 small cells, so enemy
  (and your own) shots chip away at them, leaving jagged, uneven craters.
  Bunkers are rebuilt fresh at the start of every wave, and aliens that march
  down through one chew a hole in it
- **Floating avatar hazards** (see below), drifting and ricocheting off walls,
  aliens and bunkers, chipping away at bunkers while only your gun or your
  ship can destroy them
- 3 lives, brief invulnerability (the ship flashes) after a hit
- Endless waves: each cleared wave pays a bonus and starts faster
- Game over when you run out of lives **or** the formation reaches the landing line
- Title, pause, and game-over screens; starfield plus a fresh 1960s cover
  backdrop each wave; particle debris; procedural sound effects and a
  different music genre per wave
- **A persistent top-100 leaderboard** (see below) recording score, wave,
  avatars killed and your shooting statistics

## High-score leaderboard

Every completed run is ranked against the best **100** runs ever played and
written to:

```
~/.local/share/space_invaders/leaderboard.json
```

(Override with `SPACE_INVADERS_SCORES=/path/to/file.json`.) The file is loaded
at startup and saved atomically, so scores survive restarts. Corrupt or
partial files are ignored rather than crashing the game.

Each entry stores:

| Column | Meaning |
| --- | --- |
| `SCORE` | Final score |
| `WAVE` | Wave reached |
| `AVATARS` | Floating avatar badges destroyed |
| `BUNKER` | **Percentage of all bunker cells deployed during the run that were destroyed by your own bullets** |
| `ACCURACY` | **Bullets that hit an alien or avatar ÷ bullets fired**, as a percentage |

Accuracy counts only player bullets; hitting a bunker is a miss for this
statistic. Bunker damage from alien fire, avatar bites and aliens marching
through a bunker is not credited to you, but destroyed cells still count
against the total, so the percentage reflects your own contribution.

Press `L` from the title, pause, game-over or gameplay to open the table; use
`Up`/`Down` (or `PageUp`/`PageDown`) to scroll through all 100 places and
`L`/`Esc` to go back. Your latest run is highlighted in the table, and the
game-over screen shows the run's numbers plus its new rank.

## Headless smoke test

```bash
.venv/bin/python main.py --selftest --duration 60
```

Plays the game with pseudo-random input for N seconds under SDL's dummy video
driver, asserting that bullets and aliens stay in bounds, that no frame raises,
and checking bunker erosion, letterboxed scaling at several resolutions, the
avatar hazards (bouncing, every collision type, explosion effects, spawning),
that each wave paints a different backdrop and rotates through every music
genre without repeats, that the leaderboard keeps 100 sorted entries, reloads
correctly and records each run once, that shooting statistics follow the
accuracy/bunker rules above, and that the synth is audible, deterministic per
seed, and distinct across genres. Useful in CI without a display.

## Tweaking

The game constants at the top of `main.py` are the knobs: window size, formation
size/spacing, marching speed, bullet speeds, fire cooldown, colors, lives,
number of bunkers, and bunker grid/cell size (`SHIELD_*`).

The hazards are tuned by `DRIFTER_SIZE`, `DRIFTER_SPEED_MIN`/`MAX`,
`DRIFTER_SPAWN_DELAY`, `DRIFTER_RESPAWN`, `DRIFTER_POINTS`, and
`AVATAR_SHEET`. The concurrent limit is the wave number (set in
`Game.update_drifters`).

The leaderboard size is `LEADERBOARD_SIZE` (100) and its path is
`SCORES_FILE` at the top of `main.py`.

For the music, see the top of `music.py`: `RIFF_RHYTHMS` defines the rhythm
templates, `Composer._make_sections` and each genre's `sections` define the song
form, and the `GenreComposer` class attributes (`pans`, `reverb_sends`,
`delay_sends`, `duck_depth`, `section_levels`) shape the mix and dynamics.
