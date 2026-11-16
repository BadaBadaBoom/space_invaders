"""Persistent top-100 high-score table."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from config import LEADERBOARD_SIZE, SCORES_FILE, clamp


def _score_order(entry: dict[str, float]) -> tuple:
    return (-entry["score"], -entry["wave"], -entry["accuracy"],
            -entry["avatars"])


class Leaderboard:
    """The best 100 runs, persisted as JSON between sessions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else SCORES_FILE
        self.entries = self.load()

    @property
    def best(self) -> int:
        """Highest score on the board, or 0 when it is empty."""
        return int(self.entries[0]["score"]) if self.entries else 0

    @staticmethod
    def clean_entry(raw: object) -> dict[str, float] | None:
        if not isinstance(raw, dict):
            return None
        if "name" in raw:
            # Discard records from an abandoned named-board format.
            return None
        try:
            entry = {
                "score": max(0, int(raw["score"])),
                "wave": max(1, int(raw["wave"])),
                "avatars": max(0, int(raw["avatars"])),
                "bunker": float(raw["bunker"]),
                "accuracy": float(raw["accuracy"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(entry["bunker"])
                and math.isfinite(entry["accuracy"])):
            return None
        entry["bunker"] = round(clamp(entry["bunker"], 0.0, 100.0), 2)
        entry["accuracy"] = round(clamp(entry["accuracy"], 0.0, 100.0), 2)
        return entry

    def load(self) -> list[dict[str, float]]:
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

    def add(self, entry: dict[str, float]) -> int | None:
        """Insert a finished run; return its 1-based rank, or None."""
        cleaned = self.clean_entry(entry)
        if cleaned is None:
            return None
        self.entries.append(cleaned)
        self.entries.sort(key=_score_order)
        del self.entries[LEADERBOARD_SIZE:]
        self.save()
        for rank, saved in enumerate(self.entries, start=1):
            if saved is cleaned:
                return rank
        return None
