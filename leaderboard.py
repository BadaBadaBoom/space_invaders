"""Persistent top-100 high-score table."""

from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path

from config import LEADERBOARD_SIZE, SCORES_FILE, clamp


# One-word handles for the board. A finished run is stamped with one when it
# is saved, and it stays with the score across restarts.
SILLY_NAMES = (
    "BONK", "ZORP", "SPLAT", "GRONK", "BLORP", "FIZZLE", "WOBBLE", "PLONK",
    "TOAST", "TATER", "PICKLE", "WALRUS", "SPUD", "NUGGET", "BISCUIT",
    "GOOSE", "WOMBAT", "ZIGGY", "DOOFUS", "SQUID", "TOFU", "BEANS",
    "CABBAGE", "TURNIP", "CRUMPET", "BANJO", "KAZOO", "GRAVY", "MASH",
    "CHEESE", "COOKIE", "WAFFLE", "DONUT", "BAGEL", "PANCAKE", "PUDDING",
    "JELLY", "GOBLIN", "GNOME", "TROLL", "OGRE", "YETI", "MOTHMAN",
    "NESSIE", "BIGFOOT", "ROBOT", "TOASTER", "BLENDER", "KETTLE", "SPOON",
    "LADLE", "TEAPOT", "PLUNGER", "DUSTY", "SPLODGE", "WHISK", "BURRITO",
    "TACO", "NACHO", "SALSA", "GUAC", "PESTO", "HUMMUS", "KETCHUP",
    "MUSTARD", "OLIVE", "CELERY", "RADISH", "PUMPKIN", "SQUASH", "GOURD",
    "CUSTARD", "TRIFLE", "SCONE", "MUFFIN", "BAGPIPE", "TROMBONE", "TUBER",
    "SPROUT", "GARLIC", "ONION", "LEEK", "BASIL", "MINT", "THYME", "SAGE",
    "DILL", "FENNEL", "CUMIN", "NUTMEG", "CLOVE", "GINGER", "WASABI",
    "JALAPENO", "GHOST", "ZOMBIE", "VAMPIRE", "WEREWOLF", "MUMMY",
    "SKELETON", "PIRATE", "NINJA", "COWBOY", "WIZARD", "DWARF", "ELF",
    "FAIRY", "MERMAID", "KRAKEN", "CYCLOPS", "MINOTAUR", "GRIFFIN",
    "DRAGON", "PHOENIX", "UNICORN", "PEGASUS", "CENTAUR", "GOLEM", "IMP",
    "SPRITE", "BANSHEE", "KOBOLD", "MOOSE", "LLAMA", "ALPACA", "PENGUIN",
    "OTTER", "BADGER", "FERRET", "HAMSTER", "GOPHER", "BEAVER", "HADDOCK",
)

_NAME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -'")


def clean_name(raw: object) -> str:
    """Uppercase, single-line handle of at most 12 characters."""
    if not isinstance(raw, str):
        return ""
    name = "".join(ch for ch in raw.upper() if ch in _NAME_CHARS)
    return " ".join(name.split())[:12].strip()


def random_name(taken: set[str] | frozenset[str] = frozenset()) -> str:
    """Pick a handle that is not already on the board, if one is left."""
    pool = [name for name in SILLY_NAMES if name not in taken]
    return random.choice(pool or list(SILLY_NAMES))


def _score_order(entry: dict[str, float | str]) -> tuple:
    return (-float(entry["score"]), -float(entry["wave"]),
            -float(entry["accuracy"]), -float(entry["avatars"]))


class Leaderboard:
    """The best 100 runs, persisted as JSON between sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else SCORES_FILE
        self.entries = self.load()
        # Old boards predate handles: name them once and write that back, so
        # every run keeps the same name on later launches.
        if self._name_entries():
            self.save()

    def _name_entries(self) -> bool:
        """Give unnamed entries a handle; return True when any were added."""
        taken = {str(entry["name"]) for entry in self.entries if entry["name"]}
        added = False
        for entry in self.entries:
            if not entry["name"]:
                entry["name"] = random_name(taken)
                taken.add(str(entry["name"]))
                added = True
        return added

    @property
    def best(self) -> int:
        """Highest score on the board, or 0 when it is empty."""
        return int(self.entries[0]["score"]) if self.entries else 0

    @staticmethod
    def clean_entry(raw: object) -> dict[str, float | str] | None:
        if not isinstance(raw, dict):
            return None
        try:
            entry: dict[str, float | str] = {
                "name": clean_name(raw.get("name")),
                "score": max(0, int(raw["score"])),
                "wave": max(1, int(raw["wave"])),
                "avatars": max(0, int(raw["avatars"])),
                "bunker": float(raw["bunker"]),
                "accuracy": float(raw["accuracy"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(float(entry["bunker"]))
                and math.isfinite(float(entry["accuracy"]))):
            return None
        entry["bunker"] = round(clamp(float(entry["bunker"]), 0.0, 100.0), 2)
        entry["accuracy"] = round(clamp(float(entry["accuracy"]), 0.0, 100.0), 2)
        return entry

    def load(self) -> list[dict[str, float | str]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if isinstance(raw, dict):
            raw = raw.get("scores", [])
        if not isinstance(raw, list):
            return []
        entries = [self.clean_entry(item) for item in raw]
        entries = [entry for entry in entries if entry is not None]
        entries.sort(key=_score_order)
        return entries[:LEADERBOARD_SIZE]

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(json.dumps(self.entries, indent=2),
                            encoding="utf-8")
            os.replace(temp, self.path)
        except OSError:
            # A read-only home directory shouldn't take the game down.
            pass

    def add(self, entry: dict[str, float | str]) -> int | None:
        """Insert a finished run; return its 1-based rank, or None."""
        cleaned = self.clean_entry(entry)
        if cleaned is None:
            return None
        if not cleaned["name"]:
            taken = {str(row["name"]) for row in self.entries if row["name"]}
            cleaned["name"] = random_name(taken)
        self.entries.append(cleaned)
        self.entries.sort(key=_score_order)
        del self.entries[LEADERBOARD_SIZE:]
        self.save()
        for rank, saved in enumerate(self.entries, start=1):
            if saved is cleaned:
                return rank
        return None

    def clear(self) -> int:
        """Erase every saved run; return how many were removed."""
        removed = len(self.entries)
        self.entries = []
        self.save()
        return removed
