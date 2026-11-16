---
description: Rendering lane; edits render.py only
mode: primary
color: "#6ba8d6"
permissions:
  - action: edit
    resource: "*"
    effect: deny
  - action: edit
    resource: "render.py"
    effect: allow
  - action: subagent
    resource: "*"
    effect: deny
  - action: subagent
    resource: "explore"
    effect: allow
---

# UI lane

You own `render.py` and nothing else. Work in this lane's checkout
(`~/si-ui`, branch `ui`).

## Owned

- `render.py` - `RenderMixin`: playfield, HUD, leaderboard, and overlays.

## Off limits

`edit`, `write`, and `patch` are denied for every other path, including
`main.py`, `config.py`, `deps.py`, `assets.py`, `entities.py`,
`leaderboard.py`, `audio.py`, `game.py`, `selftest.py`, `covers.py`,
`music.py`, `README.md`, and `.opencode/`. Those belong to the integration
session in `~/space_invaders` or to another lane.

If a change genuinely needs a shared file, stop and report exactly what is
needed. Never route around the permission with shell redirection, `sed -i`,
`tee`, or generated files.

## Contract

- `RenderMixin.draw(surface)` is a dispatcher; keep one method per layer so
  other lanes can call them without collisions.
- Read state, do not mutate it: rendering must not change scores, positions, or
  RNG state.
- Draw on the fixed 800x600 canvas; `main.py` handles scaling to any window.
- The backdrop is drawn by `assets`/`covers`; stay out of its layering and keep
  aliens, bullets, the player, and the HUD legible on top of it.
- HUD text sits in the top band; the leaderboard must stay scrollable and show
  full stats.

## Gates before you report done

```bash
./.venv/bin/python -m py_compile render.py
uvx ruff check render.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy ./.venv/bin/python main.py --selftest --duration 90
```

For visual checks, render the title, gameplay, and leaderboard screens with the
dummy video driver, save PNGs under `/tmp/opencode/`, and inspect them.

Commit on the `ui` branch. Do not merge into `main`, rebase, or touch other
branches; the integration session merges when the lane is done.

## Report

End with: what changed, files touched, gate results, and where screenshots went.
