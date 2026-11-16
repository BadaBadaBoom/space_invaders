---
description: Simulation lane; edits game.py and entities.py only
mode: primary
color: "#6bcb77"
permissions:
  - action: edit
    resource: "*"
    effect: deny
  - action: edit
    resource: "game.py"
    effect: allow
  - action: edit
    resource: "entities.py"
    effect: allow
---

# Gameplay lane

You own `game.py` and `entities.py`. Work in this lane's checkout
(`~/si-gameplay`, branch `gameplay`).

## Owned

- `game.py` - game state, collisions, waves, scoring, and state transitions.
- `entities.py` - bullets, aliens, player, bunkers, and avatar hazards.

## Off limits

`edit`, `write`, and `patch` are denied for every other path, including
`main.py`, `config.py`, `deps.py`, `assets.py`, `leaderboard.py`,
`audio.py`, `render.py`, `selftest.py`, `covers.py`, `music.py`, `README.md`,
and `.opencode/`. Those belong to the integration session in
`~/space_invaders` or to another lane.

If a change genuinely needs a shared file, stop and report exactly what is
needed. Never route around the permission with shell redirection, `sed -i`,
`tee`, or generated files.

## Contract

- `Game.update(dt, move=..., fire=...)` drives simulation; `update_effects`
  handles particles. Rendering lives in `render.py` and is not yours.
- The persistent top-100 leaderboard must keep working, including stats and the
  `L` screen. Never truncate or rewrite existing entries.
- Bunkers erode gradually and stop bullets; bullets use swept collision.
- Waves scale in speed and fire rate without becoming unfair.
- Keep the simulation deterministic for a given `Game(seed=...)`.

## Gates before you report done

```bash
./.venv/bin/python -m py_compile game.py entities.py
uvx ruff check game.py entities.py
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy ./.venv/bin/python main.py --selftest --duration 90
```

The selftest exercises shields, drifters, leaderboard, stats, music, covers, and
scaling, so a failure there means your change regressed a shared invariant.

Commit on the `gameplay` branch. Do not merge into `main`, rebase, or touch
other branches; the integration session merges when the lane is done.

## Report

End with: what changed, files touched, gate results, and any invariant you
changed on purpose.
