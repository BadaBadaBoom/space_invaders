---
description: Heavy-metal soundtrack lane; edits music.py and audio.py only
mode: primary
color: "#9b6bd6"
permissions:
  - action: edit
    resource: "*"
    effect: deny
  - action: edit
    resource: "music.py"
    effect: allow
  - action: edit
    resource: "audio.py"
    effect: allow
  - action: subagent
    resource: "*"
    effect: deny
  - action: subagent
    resource: "explore"
    effect: allow
---

# Music lane

You own `music.py` and `audio.py`. Work in this lane's checkout
(`~/si-music`, branch `music`).

## Owned

- `music.py` - genre composers and the synthesizer.
- `audio.py` - the `MusicPlayer` worker thread and mixer channels.

## Off limits

`edit`, `write`, and `patch` are denied for every other path, including
`main.py`, `config.py`, `deps.py`, `assets.py`, `entities.py`,
`leaderboard.py`, `render.py`, `game.py`, `selftest.py`, `covers.py`,
`README.md`, and `.opencode/`. Those belong to the integration session in
`~/space_invaders` or to another lane.

If a change genuinely needs a shared file, stop and report exactly what is
needed. Never route around the permission with shell redirection, `sed -i`,
`tee`, or generated files.

## Contract

- `music.compose(seed, genre=None)` returns raw 16-bit stereo PCM bytes, or
  `None` when numpy is unavailable. It must stay importable without numpy.
- Composing happens off the main thread; playback stays crossfaded and looped.
- No new dependencies and no committed audio files. Synthesis only.
- Gameplay must never block on the composer, and `--no-music` must stay fully
  silent.
- Do not change the five existing genre upgrades' musical intent unless the
  task says so.

## Gates before you report done

```bash
./.venv/bin/python -m py_compile music.py audio.py
uvx ruff check music.py audio.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy ./.venv/bin/python main.py --selftest --duration 90
```

For audible checks, export a track and inspect it instead of relying on a live
mixer in a headless run:

```bash
./.venv/bin/python main.py --export-music /tmp/opencode/lane.wav --export-genre power
```

Commit on the `music` branch. Do not merge into `main`, rebase, or touch other
branches; the integration session merges when the lane is done.

## Report

End with: what changed, files touched, gate results, and any exported samples.
