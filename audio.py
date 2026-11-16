"""Background music worker thread and mixer channels."""

from __future__ import annotations

import random
import threading

import pygame

from deps import metal

DEFAULT_VOLUME = 0.32
VOLUME_STEP = 0.1


class MusicPlayer:
    """Composes tracks on a worker thread and loops them, crossfaded."""

    def __init__(self, enabled: bool = True, volume: float = DEFAULT_VOLUME) -> None:
        self.volume = max(0.0, min(1.0, volume))
        self.muted = False
        self.enabled = bool(enabled and metal is not None
                           and pygame.mixer.get_init())
        self.thread: threading.Thread | None = None
        self.pending: bytes | None = None
        self.lock = threading.Lock()
        self.want_new = False
        self.want_genre: str | None = None
        self.genre: str | None = None
        self.current: pygame.mixer.Sound | None = None
        self.channels: list[pygame.mixer.Channel] = []
        self.active = 0
        if self.enabled:
            pygame.mixer.set_num_channels(16)
            self.channels = [pygame.mixer.Channel(14), pygame.mixer.Channel(15)]

    def request(self, genre: str | None = None) -> None:
        """Compose a brand-new song; it fades in as soon as it is rendered."""
        if not self.enabled:
            return
        if self.thread and self.thread.is_alive():
            self.want_new = True
            self.want_genre = genre
        else:
            self._start(genre)

    def next_track(self) -> None:
        """Skip to a freshly composed song, staying in the current genre."""
        self.request(self.genre)

    def _start(self, genre: str | None = None) -> None:
        self.want_new = False
        if genre is None and metal is not None:
            genre = random.choice(metal.GENRES)
        self.genre = genre
        seed = random.randrange(1 << 30)
        self.thread = threading.Thread(target=self._compose, args=(seed, genre),
                                       daemon=True)
        self.thread.start()

    def _compose(self, seed: int, genre: str | None) -> None:
        try:
            data: bytes | None = metal.compose(seed, genre=genre)
        except Exception:  # noqa: BLE001 - a failed compose just goes silent
            data = None
        with self.lock:
            self.pending = data

    def update(self) -> None:
        if not self.enabled:
            return
        if self.want_new and not (self.thread and self.thread.is_alive()):
            self._start(self.want_genre)
        with self.lock:
            data, self.pending = self.pending, None
        if not data:
            return
        try:
            sound = pygame.mixer.Sound(buffer=data)
        except Exception:  # noqa: BLE001 - keep the old track playing
            return
        new_volume = self.level
        old = self.channels[self.active]
        new = self.channels[1 - self.active]
        old.fadeout(600)
        new.set_volume(new_volume)
        new.play(sound, loops=-1, fade_ms=600)
        self.active = 1 - self.active
        self.current = sound

    def _apply_volume(self) -> None:
        level = self.level
        for ch in self.channels:
            ch.set_volume(level)

    def set_volume(self, volume: float) -> float:
        """Set the music volume, clamped to 0.0 - 1.0, and return it."""
        self.volume = max(0.0, min(1.0, float(volume)))
        if self.volume > 0.0:
            self.muted = False
        self._apply_volume()
        return self.volume

    def change_volume(self, delta: float) -> float:
        """Nudge the volume by *delta*; turning it up also clears mute."""
        if delta > 0.0:
            self.muted = False
        self.volume = max(0.0, min(1.0, self.volume + delta))
        self._apply_volume()
        return self.volume

    @property
    def level(self) -> float:
        """Effective output level, with mute folded in."""
        return 0.0 if self.muted else self.volume

    @property
    def volume_percent(self) -> int:
        return round(self.volume * 100)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        self._apply_volume()
        return self.muted
