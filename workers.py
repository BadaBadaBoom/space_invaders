"""Small helpers shared by background workers."""

from __future__ import annotations

import os
import sys


def lower_worker_priority(amount: int = 10) -> None:
    """Deprioritise the calling worker thread without slowing the game loop.

    Linux niceness is per-thread; on other platforms ``os.nice`` would affect
    the whole process, so keep the game responsive there and skip it.
    """
    if not sys.platform.startswith("linux"):
        return
    try:
        os.nice(amount)
    except (AttributeError, OSError):
        pass
