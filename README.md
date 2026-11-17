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
| `P` | Pause / resume (the pause screen summarises the run) |
| `I` | Toggle invincible test mode; it survives run restarts until turned off |
| `H` | Help card: every command plus an illustrated guide to the power-up capsules |
| `L` | High-score leaderboard (up/down, `PageUp`/`PageDown` or the mouse wheel to scroll) |
| `←` / `→` on game over | Read the previous / next NASA article |
| `Delete` | On the leaderboard: erase every saved score (press twice) |
| `M` | Mute / unmute music |
| `↑` / `↓` | Music volume up / down (10% steps) |
| numpad `+` | Next song (new genre and composition) |
| `F3` | CRT filter: off / low / medium / high |
| `[` / `]` | CRT intensity down / up (10% steps) |
| `F11` or `Alt+Enter` | Fullscreen on/off |
| `Enter` | Start / restart (composes a new song) |
| `Esc` | Leave fullscreen, or quit |

`I` is a testing aid rather than a gameplay feature. While it is on, enemy
fire, dive-bombers, avatar badges and the landing line cannot end the run. The
HUD shows `INVINCIBLE`, and the setting survives run restarts until you press
`I` again. Toggle it off when you want the run to be lethal again.

The dash ignores held movement for its 0.14 s burst, so it works as an
escape even while you are pressing the other way, and the burst is
**invulnerable** — a glowing shield wraps the ship, bullets pass through it,
and dashing into a floating badge destroys the badge instead of you. Four
chevrons beside the fleet map refill as the dash recharges, then pulse when it
is ready.

The ship itself reacts to what it is doing: twin engine flames flicker behind
the hull, it leans into held movement, and firing kicks the nose back under a
short muzzle flash. Active RAPID and TRIPLE pickups show as draining bars under
the lives and blink when they are nearly out.

## The soundtrack

There are no audio files. On launch — and again every time you start a game or
clear a wave — `music.py` composes a brand-new track from a random seed and
renders it to raw 16-bit stereo PCM, which is then looped on a reserved mixer
channel and crossfaded in. The next wave's genre is chosen one wave ahead and
rendered while the current track plays, so the change is ready when the next
wave starts.

The soundtrack also gets **more urgent as you advance**: higher waves run at a
slightly faster tempo, get busier drum fills and push the lead/bus levels a
little harder.  A short three-note fanfare plays each time you clear a wave,
sitting on top of the crossfade.  Track length is tuned by `MUSIC_SHORTEN` in
`config.py` so the worker reliably finishes the next song before you clear the
current wave.

The soundtrack follows the game's state too: it **ducks smoothly** to 35% on
pause and the help card, 45% on the leaderboard, fades out for game over, and
swells back to full on resume or restart.  The fade time and each level are set
by `MUSIC_DUCK_FADE`, `MUSIC_DUCK_PAUSED`, `MUSIC_DUCK_SCORES` and
`MUSIC_DUCK_GAMEOVER` in `config.py`.

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

Every 4–8 seconds a group of aliens peels out of the formation at the same
time, stops marching and steers toward your ship, accelerating as it falls.
Each one drags a layered flame plume and a trail of embers behind it, which
stream opposite to its dive angle. Divers stop counting as part of the
formation — the march keeps moving without them, and they can no longer shoot
or trigger the landing line.

The group size is chosen uniformly from one up to the current wave, capped at
`DIVE_MAX_GROUP` (5):

| Wave | Possible simultaneous divers |
| --- | --- |
| 1 | 1 |
| 2 | 1 or 2 |
| 3 | 1, 2 or 3 |
| 4 | 1, 2, 3 or 4 |
| 5+ | 1, 2, 3, 4 or 5 |

Shoot a diver for its row's points, dash through it to destroy it safely, or
let it reach you and lose a life; if it misses it leaves the bottom of the
arena with a spray of sparks. The next group only launches once the current
divers are gone, and dives stop entirely once the wave is down to eight
aliens. The gap between groups tightens as the waves climb, and a short high
chirp marks each launch.

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
The HUD shows each one as a draining bar under the lives, blinking when it is
nearly out. A repair capsule only drops when a bunker is actually damaged, and
the rebuilt cells count as deployed, so the run's bunker percentage stays
meaningful.

Press **H** at any time for the help card: it lists every command and shows
each capsule at illustration size with its effect and duration. The card
freezes the fight while it is open, returns to whatever screen it was opened
from, and is also reachable from the title, pause, game-over and leaderboard
screens.

## Boss waves

Every fifth wave fields one wide machine instead of the formation. A longer
`CAPITAL SHIP INBOUND` card warns you first, then the hull **slides down from
above the arena** over 1 second. It cannot fire until it settles, and its
health bar and `SENTINEL 1` nameplate only appear once it is in place. After
that it hovers near the top, swaying ±46 px, never marches, never drops toward
the landing line, and brings no formation escorts.

- **Health** scales with the boss number — 30 hits on wave 5, 42 on wave 10,
  54 on wave 15 — shown as a segmented bar above the hull that turns red in
  the last third. A pale **ghost segment** drains a beat behind the real bar,
  so a burst of damage stays legible against the health it just removed.
- **Three fire patterns** cycle: a five-shot fan from across the hull, a
  three-shot volley aimed at your current position (its bullets lean
  horizontally to reach a ship at either wall), and a six-shot rain scattered
  across the arena at mixed speeds.
- **Kamikaze summons**: between volleys the boss can open one to five random
  portals in the arena below its hull. Each spits out a diving alien that
  steers like an ordinary dive-bomber; they can be shot for their row's
  points, and they all die with the boss.
- **Phasing bunkers**: every 2–3 seconds the bunkers blink out for
  `SHIELD_BLINK_TIME` (0.8 s). While phased they neither block bullets nor
  take damage; when they return they keep the exact craters they had before.
  The boss entrance is protected by solid cover, and the bunkers return for
  the victory beat.
- **Overdrive** starts the moment the hull crosses half health: the palette
  flashes to warning reds, the `SENTINEL` nameplate gains `// OVERDRIVE`, the
  arena shakes, a ring and sparks burst off the hull, and its sway and volley
  rate increase (`BOSS_RAGE_SWAY_SCALE`, `BOSS_RAGE_FIRE_SCALE`).
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
for each wave, but it is rendered on a worker thread so the wave transition
does not hitch; when it lands, the old cover **crossfades** into the new one
over `COVER_FADE_TIME` (0.55 s) instead of cutting. If numpy is unavailable the
game falls back to a simple gradient backdrop.

## Fullscreen and scaling

The game always draws into a fixed 800×600 canvas, then scales that canvas to
whatever the window is, preserving the 4:3 aspect ratio. Rather than flat black
bars, the space around the canvas is filled with a matching **starfield
bezel**, so a wide fullscreen display looks deliberate. Everything — text,
ships, bunkers, particles — grows together on a big display.

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
size, and `off` or 0% intensity skips it entirely. During active play, the top
HUD strip (`HUD_CRT_HEIGHT`, 64 px) — BEST/SCORE, the fleet map, chain, dash
and boost timers, wave and lives — is capped at the **medium** preset, so
selecting `high` only intensifies the playfield below it. The NASA story card
is kept fully crisp.

## Rendering caches

The canvas is still redrawn every frame, but the parts that never change are
painted once. The gradient and the active cover are baked into a single opaque
backdrop per wave (blitting a semi-transparent full-screen cover every frame
was by far the largest draw cost), invader sprites are cached per wave look,
colour and animation frame, HUD/menu labels come from a small text cache, and
the game-over card and help-card power-up icons are built once and reused.
Bullet and power-up glows are cached, drifter fades scale the shared tile
instead of copying it, collisions avoid per-bullet sorts, and the CRT bloom
reuses its scaled surfaces. In the headless benchmark the full update/draw/
present loop roughly halved, with the draw pass about twice as fast.

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
- **Dive-bombers** (see below): every few seconds a group of aliens peels out
  of the formation, leaves a burning trail and swoops at you, steering as it
  falls; the group grows from one to five as the waves climb
- **Power-up capsules**: some alien kills drop a falling capsule for rapid
  fire, triple shot or a bunker repair
- **A boss every fifth wave**: a warning card, a slide-in entrance, a
  `SENTINEL` nameplate, a ghost-drained HP bar, three fire patterns, kamikaze
  summons, phasing bunkers, and an overdrive phase below half health
- 3 lives; a hit bursts the ship where it actually died, pulses a red edge
  vignette and blinks the lost life icon as the replacement ship arrives
- **A dash**: double-tap a direction for an invulnerable 126 px burst that
  overrides held movement, on a 1.2 s cooldown — the answer to a badge
  drifting into your lane
- **Kill chains**: kills landed within 1.35 s of each other extend a `CHAIN`
  counter, raise the popup multiplier and climb a short chirp; a hit or a
  cleared wave breaks the chain
- Endless waves: each cleared wave pays `+100` and opens a short intro card
  that holds the fight while the new fleet arrives
- Game over when you run out of lives **or** the formation reaches the landing line
- Title, pause, and game-over screens: an attract-mode fleet and saucer
  behind the title, a pause card with score/wave/lives/accuracy, and a
  game-over card that fades in over the death beat; a help card on **H** with
  every command and a picture of each power-up capsule; a starfield plus a
  fresh 1960s cover backdrop each wave, crossfaded in; particle debris;
  procedural sound effects and a different music genre per wave
- **Hit feedback**: the whole view jolts when the ship takes a hit, a little
  when you shoot an avatar badge, and hard when you beat the board's best;
  every score award floats up as a fading number, and the HUD tracks the
  live 8×4 fleet map (dimming as ranks thin), dash recharge, kill chain and
  power-up timers
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
`Up`/`Down` (or `PageUp`/`PageDown`) or the mouse wheel to scroll through all
100 places and `L`/`Esc` to go back. The screen draws a scrollbar when the
table is longer than the visible 15 rows. Opening it after a run **auto-scrolls
to the new entry**, which is highlighted and tagged `NEW`, even when the run
landed near the bottom. Alt rows are shaded so long scores stay readable. The
game-over card still shows the run's numbers plus its new rank.

To wipe the board, press `Delete` on that screen and then `Delete` again within
four seconds to confirm. Any other key cancels, so a stray press costs nothing.

During play the record is shown live as `BEST` above your running score, and it
follows you once you pass it. The moment a run beats the board's best, half the
remaining aliens (rounded down, so the wave always keeps at least one) explode
in their row colours and a 2.2-second synthesized blast plays. It happens once
per run, and an empty board simply has no record to beat. A flashing marquee
then scrolls `NEW HIGH SCORE 05381` across the arena for 3 seconds with the
whole view shaking the entire time, and play is frozen while it rolls so the
celebration can never get you killed.

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

On the game-over card, press `←` / `→` to read the previous or next article
without starting another run. Adjacent stories and page boundaries are fetched
in the background; the current card stays on screen until the next one is
ready, with `LOADING ARTICLE...` shown at the bottom. The arrows arm after
`GAMEOVER_ARTICLE_DELAY` (0.5 s), so a held fire key or an accidental tap on
the death frame does not skip the first story. The feed's own position is
untouched, so the next run still starts with the next unread story.

## Headless smoke test

```bash
.venv/bin/python main.py --selftest --duration 60
```

Plays the game with pseudo-random input for N seconds under SDL's dummy video
driver, asserting that bullets and aliens stay in bounds, that no frame raises,
and checking bunker erosion, letterboxed scaling at several resolutions, the
avatar hazards (bouncing, every collision type, explosion effects, spawning),
the mystery UFO (spawn timing, crossing, payout, its death shake and wail, and
bullet-only kills), dive-bombers (launch, wave-scaled group sizes, steering,
leaving the arena, collisions, dash-through and points), power-up capsules
(drop rate, falling, pickup, both timed boosts and repair), boss waves
(warning card, entry slide
and fire lock, scaling, sway bounds, all three volleys, damage, ghost health,
the overdrive trigger, kamikaze summons, phasing bunkers that keep their
damage, kill payout and victory pause), the dash (double-tap
window, burst over held input, wall clamp, cooldown, invulnerability and
dash-through kills), the flow beats (wave cards freeze and release the sim, the
`+100` bonus lands after the card, the death burst and red vignette fire, the
game-over card fades in, and the pause summary paints), the invincibility test
toggle (survives bullets, badge collisions and the landing line, persists
across restarts, and becomes lethal again when switched off), the help card
(opens
from the title, play, pause, game over and leaderboard, freezes the fight
while open, returns to the same screen, and has a cached illustration for
every power-up), the render caches (label, sprite and backdrop reuse, bounded
backdrop storage, and game-over-card invalidation), the feel pass (muzzle
flash, movement lean, kill chains and expiry, cover crossfade, title attract
loop), leaderboard landing (auto-scroll to a low-ranked new entry, top of the
table from the title), audio ducking, game-over article browsing (cached
neighbours, page crossings, edge stops, and the separate browse cursor), that
each wave paints a different backdrop and rotates through every music genre
without repeats, that the leaderboard keeps 100 sorted entries, reloads
correctly and records each run once, that shooting statistics follow the
accuracy/bunker rules above, that the record marquee fires and expires, and
that the synth is audible, deterministic per seed, and distinct across
genres. Useful in CI without a display.

## Tweaking

The game constants at the top of `config.py` are the knobs: window size,
formation size/spacing, marching speed, bullet speeds, fire cooldown, colours,
lives, number of bunkers, and bunker grid/cell size (`SHIELD_*`).

Flow beats are tuned by `WAVE_INTRO_TIME` and `WAVE_INTRO_BOSS_TIME` (how long
the card holds the fight), `GAMEOVER_FADE` (game-over layer fade-in),
`GAMEOVER_ARTICLE_DELAY` (how long the article arrows stay disarmed) and
`HURT_FLASH_TIME` (red edge vignette after a lost life). The feel pass uses
`MUZZLE_FLASH_TIME`, `COMBO_WINDOW` (kill-chain lifetime) and
`COVER_FADE_TIME` (backdrop crossfade).

The CRT defaults are in `config.py`: `CRT_DEFAULT` (`"off"`, `"low"`,
`"medium"` or `"high"`), `CRT_INTENSITY` (0.0–1.0) and `HUD_CRT_HEIGHT`
(height of the top strip whose effect is capped at medium). The dark wash
behind the title, pause and help cards is `OVERLAY_DIM`; the leaderboard uses
the heavier `SCORES_DIM`.

The hazards are tuned by `DRIFTER_SIZE`, `DRIFTER_SPEED_MIN`/`MAX`,
`DRIFTER_SPAWN_DELAY`, `DRIFTER_RESPAWN`, `DRIFTER_LIFE`,
`DRIFTER_POINTS`/`DRIFTER_POINTS_MIN`, and `AVATAR_SHEET`. The concurrent
limit is the wave number (set in `Game.update_drifters`).

The saucer is tuned by `UFO_SPEED_MIN`/`MAX`, `UFO_FIRST_DELAY`, `UFO_RESPAWN`
and `UFO_POINTS` in `config.py`.

Dive-bombers use `DIVE_FIRST_DELAY`, `DIVE_INTERVAL`, `DIVE_MIN_ALIVE`,
`DIVE_MAX_GROUP`, `DIVE_SPEED_X`, `DIVE_START_VY`/`MAX_VY`, `DIVE_ACCEL` and
`DIVE_TURN`.

Power-up capsules use `POWERUP_DROP_CHANCE`, `POWERUP_FALL_SPEED`,
`POWERUP_RAPID_SCALE`/`TIME`, `POWERUP_TRIPLE_TIME`, and the
`POWERUP_KINDS`/`WEIGHTS`/`COLORS`/`LABELS` tables.

The boss is tuned by `BOSS_EVERY`, `BOSS_ENTRY_TIME`, `BOSS_HP_BASE`/`STEP`,
`BOSS_SCORE_BASE`/`STEP`, `BOSS_SWAY`/`SWAY_SPEED`, `BOSS_FIRE_MIN`/`MAX`,
`BOSS_RAGE_FIRE_SCALE`/`BOSS_RAGE_SWAY_SCALE` and `BOSS_VOLLEY_SPEED`. Its
kamikaze summons reuse `DIVE_MAX_GROUP` and the dive steering constants;
bunker phasing uses `SHIELD_BLINK_INTERVAL` and `SHIELD_BLINK_TIME`.

The dash uses `DASH_TAP_WINDOW` (double-tap window), `DASH_SPEED`, `DASH_TIME`
and `DASH_COOLDOWN`.

The leaderboard size is `LEADERBOARD_SIZE` (100) and its path is `SCORES_FILE`
in `config.py`.

Screen shake is tuned in `config.py`: `SHAKE_DRIFTER`, `SHAKE_UFO`,
`SHAKE_LIFE_LOST`, `SHAKE_RECORD` and `SHAKE_BOSS_RAGE` are the peak
displacement in canvas pixels for each trigger, `SHAKE_BANNER` is the level
held while the record marquee rolls, `SHAKE_MAX` caps stacked hits and
`SHAKE_DECAY` is the fade time constant in seconds. The floating score numbers
use `POPUP_LIFE` and `POPUP_RISE`, and the record marquee uses
`RECORD_BANNER_TIME` and `RECORD_BANNER_SCROLL`. Set the trigger strengths to 0
to turn shake off. Each wave's alien silhouette comes from `alien_look()` in
`render.py`, keyed on the wave number.

For the music, `MUSIC_SHORTEN` in `config.py` controls loop length (smaller
= faster composition and more reliable prefetching).  `RIFF_RHYTHMS` defines
the rhythm templates, `Composer._make_sections` and each genre's `sections`
define the song form, and the `GenreComposer` class attributes (`pans`,
`reverb_sends`, `delay_sends`, `duck_depth`, `section_levels`) shape the mix
and dynamics.  The intensity passed into `compose()` scales tempo, lead/bus
levels and drum density so later waves feel more urgent.  The state ducking
uses `MUSIC_DUCK_FADE` and the three `MUSIC_DUCK_*` levels described above.
