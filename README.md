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
entities.py    bullets, aliens, player, bunkers, avatar hazards, UFO, capsules,
               the wave boss
leaderboard.py persistent top-100 table
audio.py       MusicPlayer worker thread and mixer channels
render.py      RenderMixin: playfield, HUD, leaderboard, overlays
crt.py         pure-pygame CRT post-process overlay
news.py        NASA story feed for the game-over card
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
| double-tap `←` / `→` | Dash: 126 px burst, 1.2 s cooldown |
| `Space` | Fire (max 3 shots on screen) |
| `P` | Pause / resume |
| `L` | High-score leaderboard (up/down to scroll) |
| `Delete` | On the leaderboard: erase every saved score (press twice) |
| `M` | Mute / unmute music |
| `↑` / `↓` | Music volume up / down (10% steps) |
| numpad `+` | Next song (new genre and composition) |
| `F3` | CRT filter: off / low / medium / high |
| `[` / `]` | CRT intensity down / up (10% steps) |
| `F11` or `Alt+Enter` | Fullscreen on/off |
| `Enter` | Start / restart (composes a new song) |
| `Esc` | Leave fullscreen, or quit |

The dash ignores held movement for its 0.14 s burst, so it works as an
escape even while you are pressing the other way, and the burst is
**invulnerable** — a glowing shield wraps the ship, bullets pass through it,
and dashing into a floating badge destroys the badge instead of you. A pair
of chevrons beside the fleet map goes bright when it is ready and dims while
it recharges.

## The soundtrack

There are no audio files. On launch — and again every time you start a game or
clear a wave — `music.py` composes a brand-new track from a random seed and
renders it to raw 16-bit stereo PCM, which is then looped on a reserved mixer
channel and crossfaded in. The next wave's genre is chosen one wave ahead and
rendered while the current track plays, so the change is ready when the next
wave starts.

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

The numpad `+` key skips to a fresh composition in a different genre; the HUD
label follows the track, and that wave's pre-picked next genre is refreshed if
it collides.

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
At startup the game slices it into six individual sprites (39×39 px — a little
larger than an alien ship, 34×24). The sheet's flat white background is cut
away outside each badge circle, so the artwork inside keeps its white details,
and the most common vivid colours of each badge are sampled to tint its
explosion.

Shortly after each wave begins, a badge starts floating across the arena; it
moves in a straight line at 70–125 px/s and **bounces off the four walls,
the alien formation and the bunkers**. Each badge lives for **10 seconds**: it
starts at full brightness, fades steadily, and at the end of its life vanishes
in a small palette-coloured pop — no points, and it does not count as a kill.
Every 4.5 s after one disappears, another appears. The limit is the wave
number: **one badge on wave 1, two on wave 2, three on wave 3**, and so on.
Spawns are placed in open space, below the formation and above the bunkers.

Only two things can destroy a badge — your bullet, or your ship. A bullet kill
pays **100 points at spawn, falling to 10 just before the badge fades out**,
so shoot early:

| Collides with | Badge | Other party |
| --- | --- | --- |
| Your bullet | Explodes, **+10 to +100 points** (more the sooner you shoot) | Bullet is consumed |
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

## The mystery UFO

Every 25 seconds or so a saucer crosses the top of the arena without warning,
travelling 70–105 px/s from one edge to the other. It is worth **50, 100, 150
or 300 points**, picked when it appears, and it exists only to be shot: it
never fires, never touches the bunkers, and alien fire passes straight
through it.

Because it flies above the formation, you can only reach it through a column
you have already cleared, which is exactly the classic tension. A hit pays the
points, floats the number up and bursts the saucer in silver and orange, with
a screen jolt and its own descending, vibrato'd wail instead of the usual
short blast; a miss costs nothing and the next one is scheduled about 25
seconds later.

## Dive-bombers

Every 4–8 seconds one alien peels out of the formation, stops marching and
steers toward your ship, accelerating as it falls. It stops counting as part
of the formation — the march keeps moving without it, and it can no longer
shoot or trigger the landing line.

Shoot it for its row's points, dash through it to destroy it safely, or let it
reach you and lose a life; if it misses it leaves the bottom of the arena with
a spray of sparks. Dives stop once the wave is down to eight aliens, and the
gap between them tightens as the waves climb. A short high chirp marks each
launch.

## Power-ups

Roughly one alien kill in fourteen leaves a capsule falling at 95 px/s. Catch
it with the ship **or shoot it** — either way the boost is applied, so nothing
is lost when a badge is falling somewhere you cannot reach. Left alone it
falls past the floor and vanishes.

| Capsule | Effect |
| --- | --- |
| `R` (gold) | **Rapid fire** — fire cooldown ×0.4 for 8 seconds |
| `T` (blue) | **Triple shot** — three parallel bullets per press for 10 seconds |
| `B` (green) | **Repair** — every bunker rebuilt to its original shape |

Both timed boosts can run at once, and picking one up again resets its timer.
The HUD shows the remaining seconds under the lives. A repair capsule only
drops when a bunker is actually damaged, and the rebuilt cells count as
deployed, so the run's bunker percentage stays meaningful.

## Boss waves

Every fifth wave fields one wide machine instead of the formation. It hovers
near the top, swaying ±46 px, never marches, never drops toward the landing
line, and brings no escorts.

- **Health** scales with the boss number — 30 hits on wave 5, 42 on wave 10,
  54 on wave 15 — shown as a segmented bar above the hull that turns red in
  the last third.
- **Three fire patterns** cycle: a five-shot fan from across the hull, a
  three-shot volley aimed at your current position (its bullets lean
  horizontally to reach a ship at either wall), and a six-shot rain scattered
  across the arena at mixed speeds.
- Each bullet hit is one point of damage and flashes the hull. The kill clears
  every enemy bullet, pays 1000 points (plus 250 per later boss), explodes
  three times, drops a guaranteed power-up capsule, and holds the arena for
  1.6 s before the next wave starts.
- Only one avatar badge floats during a boss wave, so the fight stays readable.

## 1960s cover art backdrops

Every wave paints a new 800×600 backdrop in the style of a 1960s
science-fiction paperback cover. `covers.make_cover` (called through
`make_pulp_background`) uses only pygame primitives and numpy, so the covers
are different every wave and deterministic for a given seed.

Each cover starts from one of eight limited period palettes (ember, teal,
violet, acid, ultra, rust, cobalt, mint), jittered per painting and sometimes
washed into a bright matte-painting sky. It then paints one of six
compositions:

- a finned rocket climbing past a world, or lifting off beside a lattice
  gantry in a cloud of smoke
- bubble-helmet astronauts on a ridge above a lit domed city
- a flying saucer and its escorts over the skyline, with or without a light
  beam
- boxy invasion robots towering over that domed city while searchlights rake
  the sky, sometimes with a saucer overhead and a giant machine looming in the
  foreground
- a banded ringed giant with rings drawn behind and in front of the disc
- a total eclipse with a coronal glow and a silhouetted ship

Supporting elements include lit domes, setback towers and needle spires,
jagged ridge lines with rim light and craters, deserts with alien flora,
moons, comets, orbit arcs, searchlight beams and distant craft. The planets are shaded with a
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
- The mouse pointer is shown outside active play, so game-over story links can
  be clicked in fullscreen.

## CRT filter

Every frame gets a pure-pygame CRT pass before it is scaled to the window:
scanlines, an RGB aperture grille and a vignette, plus a soft bloom and a slow
rolling refresh band on the default `medium` preset; `high` adds grain and
short phosphor trails. Press `F3` to cycle `off -> low -> medium -> high`, with
a brief on-screen hint. `[` and `]` scale the active preset's strength from 0%
to 100% in 10% steps. The defaults are `CRT_DEFAULT = "medium"` and
`CRT_INTENSITY = 1.0` in `config.py`; the runtime choice is not persisted. The
pass runs on the 800×600 canvas, so its cost stays fixed regardless of window
size, and `off` or 0% intensity skips it entirely.

## What's in it

- 4 rows × 8 aliens, each row worth a different number of points, and the
  fleet's silhouette shifts a little every wave (headgear, eyes, legs, stripes)
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
- **A mystery UFO** (see below) crossing the top of the arena every ~25 s,
  worth 50–300 points and hittable only through a cleared column
- **Dive-bombers** (see below): every few seconds one alien peels out of the
  formation and swoops at you, steering as it falls
- **Power-up capsules**: some alien kills drop a falling capsule for rapid
  fire, triple shot or a bunker repair
- **A boss every fifth wave**: a wide machine with a segmented HP bar, three
  fire patterns and no formation march
- 3 lives, brief invulnerability (the ship flashes) after a hit
- **A dash**: double-tap a direction for an invulnerable 126 px burst that
  overrides held movement, on a 1.2 s cooldown — the answer to a badge
  drifting into your lane
- Endless waves: each cleared wave pays a bonus and starts faster
- Game over when you run out of lives **or** the formation reaches the landing line
- Title, pause, and game-over screens; starfield plus a fresh 1960s cover
  backdrop each wave; particle debris; procedural sound effects and a
  different music genre per wave
- **Hit feedback**: the whole view jolts when the ship takes a hit, a little
  when you shoot an avatar badge, and hard when you beat the board's best;
  every score award floats up as a fading number, and a live 8×4 fleet map in
  the HUD dims as the ranks thin out
- **A persistent top-100 leaderboard** (see below) recording score, wave,
  avatars killed and your shooting statistics under a random silly handle
- **A NASA story on every game-over screen** (see below): picture, headline and
  summary, fetched in the background while you play

## High-score leaderboard

Every completed run is ranked against the best **100** runs ever played and
written to:

```
~/.local/share/space_invaders/leaderboard.json
```

Each run is stamped with a random one-word handle from a pool of silly names
(`BONK`, `PICKLE`, `MOTHMAN`, `TURNIP`, …). The handle is chosen when the run
is saved and stored with it, so it survives restarts; a board written before
handles existed gets named on first load and saved back.

(Override with `SPACE_INVADERS_SCORES=/path/to/file.json`.) The file is loaded
at startup and saved atomically, so scores survive restarts. Corrupt or
partial files are ignored rather than crashing the game.

Each entry stores:

| Column | Meaning |
| --- | --- |
| `RANK` | Board position, 1 = best |
| `NAME` | The run's random handle |
| `SCORE` | Final score |
| `WAVE` | Wave reached |
| `AVATARS` | Floating avatar badges destroyed |
| `BUNKER` | **Percentage of all bunker cells deployed during the run that were destroyed by your own bullets** |
| `ACCURACY` | **Bullets that hit an alien, avatar or UFO ÷ bullets fired**, as a percentage |

Accuracy counts only player bullets; hitting a bunker is a miss for this
statistic. Bunker damage from alien fire, avatar bites and aliens marching
through a bunker is not credited to you, but destroyed cells still count
against the total, so the percentage reflects your own contribution.

Press `L` from the title, pause, game-over or gameplay to open the table; use
`Up`/`Down` (or `PageUp`/`PageDown`) to scroll through all 100 places and
`L`/`Esc` to go back. Your latest run is highlighted in the table, and the
game-over screen shows the run's numbers plus its new rank.

To wipe the board, press `Delete` on that screen and then `Delete` again within
four seconds to confirm. Any other key cancels, so a stray press costs nothing.

During play the record is shown live as `BEST` above your running score, and it
follows you once you pass it. The moment a run beats the board's best, half the
remaining aliens (rounded down, so the wave always keeps at least one) explode
in their row colours and a 2.2-second synthesized blast plays. It happens once
per run, and an empty board simply has no record to beat. A flashing marquee
then scrolls `NEW HIGH SCORE 05381` across the arena for 3 seconds, and play
is frozen while it rolls so the celebration can never get you killed.

## NASA story at game over

Every finished run shows a NASA story on the game-over screen: its picture,
headline and summary, under the run's score, wave, accuracy, bunker and avatar
statistics.

Stories come from [NASA's Recently Published
page](https://www.nasa.gov/news/recently-published/). The first game over shows
the first story on the page; each following run advances by one. When the last
story on a page has been shown, the game follows the page's **Next** button to
the next page and carries on from there.

The next story and its picture are downloaded on a background thread while you
play, so the game-over screen never waits for the network. The card credits the
source (`NASA · type · read time`) and shows the article's URL; click the link
to open the full story in your browser. If the page cannot be reached the card
is simply omitted and the usual game-over screen is shown. No API key or extra
dependency is needed.

## Headless smoke test

```bash
.venv/bin/python main.py --selftest --duration 60
```

Plays the game with pseudo-random input for N seconds under SDL's dummy video
driver, asserting that bullets and aliens stay in bounds, that no frame raises,
and checking bunker erosion, letterboxed scaling at several resolutions, the
avatar hazards (bouncing, every collision type, explosion effects, spawning),
the mystery UFO (spawn timing, crossing, payout, its death shake and wail,
and bullet-only kills),
dive-bombers (launch, steering, leaving the arena, collisions, dash-through
and points),
power-up capsules (drop rate, falling, pickup, both timed boosts and repair),
boss waves (spawning, scaling, sway bounds, all three volleys, damage, the
kill payout and the victory pause),
the dash (double-tap window, burst over held input, wall clamp, cooldown,
invulnerability and dash-through kills),
that each wave paints a different backdrop and rotates through every music
genre without repeats, that the leaderboard keeps 100 sorted entries, reloads
correctly and records each run once, that shooting statistics follow the
accuracy/bunker rules above, and that the record marquee fires and expires, and that the synth is audible, deterministic per
seed, and distinct across genres. Useful in CI without a display.

## Tweaking

The game constants at the top of `main.py` are the knobs: window size, formation
size/spacing, marching speed, bullet speeds, fire cooldown, colors, lives,
number of bunkers, and bunker grid/cell size (`SHIELD_*`).

The CRT defaults are in `config.py`: `CRT_DEFAULT` (`"off"`, `"low"`,
`"medium"` or `"high"`) and `CRT_INTENSITY` (0.0–1.0).

The hazards are tuned by `DRIFTER_SIZE`, `DRIFTER_SPEED_MIN`/`MAX`,
`DRIFTER_SPAWN_DELAY`, `DRIFTER_RESPAWN`, `DRIFTER_LIFE`,
`DRIFTER_POINTS`/`DRIFTER_POINTS_MIN`, and `AVATAR_SHEET`. The concurrent
limit is the wave number (set in `Game.update_drifters`).

The saucer is tuned by `UFO_SPEED_MIN`/`MAX`, `UFO_FIRST_DELAY`, `UFO_RESPAWN`
and `UFO_POINTS` in `config.py`.

Dive-bombers use `DIVE_FIRST_DELAY`, `DIVE_INTERVAL`, `DIVE_MIN_ALIVE`,
`DIVE_SPEED_X`, `DIVE_START_VY`/`MAX_VY`, `DIVE_ACCEL` and `DIVE_TURN`.

Power-up capsules use `POWERUP_DROP_CHANCE`, `POWERUP_FALL_SPEED`,
`POWERUP_RAPID_SCALE`/`TIME`, `POWERUP_TRIPLE_TIME`, and the
`POWERUP_KINDS`/`WEIGHTS`/`COLORS`/`LABELS` tables.

The boss is tuned by `BOSS_EVERY`, `BOSS_HP_BASE`/`STEP`,
`BOSS_SCORE_BASE`/`STEP`, `BOSS_SWAY`/`SWAY_SPEED`, `BOSS_FIRE_MIN`/`MAX` and
`BOSS_VOLLEY_SPEED`.

The dash uses `DASH_TAP_WINDOW` (double-tap window), `DASH_SPEED`, `DASH_TIME`
and `DASH_COOLDOWN`.

The leaderboard size is `LEADERBOARD_SIZE` (100) and its path is
`SCORES_FILE` at the top of `main.py`.

Screen shake is tuned in `config.py`: `SHAKE_DRIFTER`, `SHAKE_UFO`,
`SHAKE_LIFE_LOST` and `SHAKE_RECORD` are the peak displacement in canvas
pixels for each trigger,
`SHAKE_MAX` caps stacked hits and `SHAKE_DECAY` is the fade time constant in
seconds. The floating score numbers use `POPUP_LIFE` and `POPUP_RISE`, and the
record marquee uses `RECORD_BANNER_TIME` and `RECORD_BANNER_SCROLL`. Set the
three trigger strengths to 0 to turn shake off. Each wave's alien silhouette
comes from `alien_look()` in `render.py`, keyed on the wave number.

For the music, see the top of `music.py`: `RIFF_RHYTHMS` defines the rhythm
templates, `Composer._make_sections` and each genre's `sections` define the song
form, and the `GenreComposer` class attributes (`pans`, `reverb_sends`,
`delay_sends`, `duck_depth`, `section_levels`) shape the mix and dynamics.
