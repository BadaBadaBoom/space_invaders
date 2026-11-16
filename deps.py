"""Optional heavy dependencies, imported once and shared."""

from __future__ import annotations

try:
    import music as metal
except Exception:  # noqa: BLE001 - numpy missing, or another synth problem
    metal = None

try:
    import covers
except ImportError:  # numpy missing; the game falls back to a gradient
    covers = None

try:
    import numpy as np
except ImportError:  # hazards and music degrade gracefully
    np = None
