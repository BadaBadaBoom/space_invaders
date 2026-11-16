---
description: 1960s sci-fi paperback cover-art lane; edits covers.py only
mode: primary
color: "#e0a458"
permissions:
  - action: edit
    resource: "*"
    effect: deny
  - action: edit
    resource: "covers.py"
    effect: allow
  - action: subagent
    resource: "*"
    effect: deny
  - action: subagent
    resource: "explore"
    effect: allow
---

# Covers lane

You own `covers.py` and nothing else. Work in this lane's checkout
(`~/si-covers`, branch `covers`).

## Owned

- `covers.py` - the procedural 1960s paperback-cover painter.

## Off limits

`edit`, `write`, and `patch` are denied for every other path, including
`main.py`, `config.py`, `deps.py`, `assets.py`, `entities.py`,
`leaderboard.py`, `audio.py`, `render.py`, `game.py`, `selftest.py`,
`music.py`, `README.md`, and `.opencode/`. Those belong to the integration
session in `~/space_invaders` or to another lane.

If a change genuinely needs a shared file, stop and report exactly what is
needed. Never route around the permission with shell redirection, `sed -i`,
`tee`, or generated files.

## Contract

- `covers.make_cover(rng, width=800, height=600)` returns a dimmed pygame
  surface (alpha 58-76), deterministic for a given `random.Random` state.
- Backgrounds sit behind gameplay: keep the lower two thirds readable and the
  HUD area (y 24-48) clear.
- No new dependencies, no generated image assets, no model weights. Only
  `pygame` and `numpy` already in the project.
- Keep render cost near 0.3-0.5 s per cover.
- Preserve the existing cover families, period palettes, and the numpy
  print-aging pass unless the task says otherwise.

## Gates before you report done

```bash
./.venv/bin/python -m py_compile covers.py
uvx ruff check covers.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy ./.venv/bin/python main.py --selftest --duration 90
```

Render a contact sheet of several seeds to `/tmp/opencode/` and inspect it when
the change is visual.

Commit on the `covers` branch. Do not merge into `main`, rebase, or touch other
branches; the integration session merges when the lane is done.

## Report

End with: what changed, files touched, gate results, and where any screenshots
went.
