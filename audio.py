"""Background music worker thread and mixer channels."""

from __future__ import annotations

import math
import random
import threading

import pygame

from config import MUSIC_DUCK_FADE, MUSIC_SHORTEN
from deps import metal

DEFAULT_VOLUME = 0.32
VOLUME_STEP = 0.1


class MusicPlayer:
    """Composes tracks on a worker thread and loops them, crossfaded."""

    def __init__(self, enabled: bool = True, volume: float = DEFAULT_VOLUME) -> None:
        self.volume = max(0.0, min(1.0, volume))
        self.muted = False
        # Runtime attenuation used for pause/game-over; independent of the
        # user's volume so raising the volume still works while ducked.
        self.duck = 1.0
        self.duck_target = 1.0
        self.enabled = bool(enabled and metal is not None
                           and pygame.mixer.get_init())
        self.thread: threading.Thread | None = None
        self.pending: bytes | None = None
        self.lock = threading.Lock()
        self.want_new = False
        self.want_genre: str | None = None
        self.genre: str | None = None
        self.intensity: float = 0.5
        self.current: pygame.mixer.Sound | None = None
        # Guards ``pending`` so a track consumed from the prepared slot cannot
        # be overwritten by a compose worker that was already in flight.
        self.compose_generation = 0
        self.channels: list[pygame.mixer.Channel] = []
        self.active = 0
        # One-slot prefetch.  ``prepare()`` renders the next wave's track on
        # its own worker and parks it here, keyed by genre, until a matching
        # ``request()`` claims it.  The generation counter lets a newer
        # prepare supersede an older one by discarding stale results.
        self.prepared: bytes | None = None
        self.prepared_genre: str | None = None
        self.prepare_thread: threading.Thread | None = None
        self.prepare_generation = 0
        # Genre currently being rendered by an in-flight prepare worker.  Used
        # to make repeated prepare() calls for the same genre idempotent.
        self.preparing_genre: str | None = None
        if self.enabled:
            pygame.mixer.set_num_channels(16)
            self.channels = [pygame.mixer.Channel(14), pygame.mixer.Channel(15)]

    def prepare(self, genre: str, intensity: float = 0.5) -> None:
        """Render *genre* into the single prepared slot on a worker thread.

        Never blocks the caller.  Calling twice for the same genre is a no-op
        while a track for it is already parked or still being rendered.  A
        prepare for a different genre supersedes the old one: it bumps the
        generation counter and takes over the single slot, so a stale worker
        that finishes later has its result discarded.
        """
        if not self.enabled:
            return
        with self.lock:
            # Already prepared and parked for this genre, or a worker is still
            # rendering it: nothing to do.
            if ((self.prepared is not None and self.prepared_genre == genre)
                    or self.preparing_genre == genre):
                return
            # A different genre supersedes the old prepare.  Clear the single
            # slot so no stale track survives, and invalidate any in-flight
            # worker before starting the new one.
            self.prepare_generation += 1
            generation = self.prepare_generation
            self.preparing_genre = genre
            self.prepared = None
            self.prepared_genre = None
        seed = random.randrange(1 << 30)
        thread = threading.Thread(
            target=self._prepare_compose,
            args=(seed, genre, generation, intensity),
            daemon=True)
        self.prepare_thread = thread
        thread.start()

    def _prepare_compose(self, seed: int, genre: str, generation: int,
                         intensity: float = 0.5) -> None:
        try:
            data: bytes | None = metal.compose(seed, shorten=MUSIC_SHORTEN,
                                               genre=genre,
                                               intensity=intensity)
        except Exception:  # noqa: BLE001 - a failed compose just goes silent
            data = None
        with self.lock:
            if generation != self.prepare_generation:
                return  # superseded by a newer prepare, or already consumed
            # This worker still owns the slot: mark it done, then publish.
            self.preparing_genre = None
            if data:
                self.prepared = data
                self.prepared_genre = genre

    def _take_prepared(self, genre: str | None) -> bool:
        """Move a matching prepared track into ``pending``; return success."""
        if genre is None:
            return False
        with self.lock:
            if self.prepared is None or self.prepared_genre != genre:
                return False
            data = self.prepared
            # Consume and clear the slot, invalidate any stale prepare worker,
            # and stop an in-flight compose worker from clobbering ``pending``.
            self.prepared = None
            self.prepared_genre = None
            self.prepare_generation += 1
            self.compose_generation += 1
            self.pending = data
        # Fulfilling a request supersedes any queued compose request.  These
        # fields are only ever touched from the main thread.
        self.want_new = False
        self.want_genre = None
        self.genre = genre
        return True

    def request(self, genre: str | None = None,
                intensity: float = 0.5) -> None:
        """Queue a brand-new song; it fades in as soon as it is rendered.

        When a track for *genre* has already been prepared it is used
        instantly - no new compose thread is started - and ``pending`` is
        populated right away for ``update()`` to crossfade in.  Otherwise the
        original compose behaviour applies.  ``intensity`` in [0, 1] scales
        the urgency of the generated track.
        """
        if not self.enabled:
            return
        self.intensity = max(0.0, min(1.0, float(intensity)))
        # Publish the requested genre right away so callers can display it
        # before the new track has finished rendering.
        if genre is not None:
            self.genre = genre
        if self._take_prepared(genre):
            return
        if self.thread and self.thread.is_alive():
            self.want_new = True
            self.want_genre = genre
        else:
            self._start(genre, self.intensity)

    def next_track(self) -> None:
        """Skip to a freshly composed song in a different genre."""
        current = self.genre
        genre = metal.pick_genre(current) if metal is not None else None
        self.request(genre, self.intensity)

    def _start(self, genre: str | None = None,
               intensity: float = 0.5) -> None:
        self.want_new = False
        if genre is None and metal is not None:
            genre = random.choice(metal.GENRES)
        self.genre = genre
        seed = random.randrange(1 << 30)
        self.compose_generation += 1
        generation = self.compose_generation
        self.thread = threading.Thread(
            target=self._compose, args=(seed, genre, generation, intensity),
            daemon=True)
        self.thread.start()

    def _compose(self, seed: int, genre: str | None,
                 generation: int | None = None,
                 intensity: float = 0.5) -> None:
        try:
            data: bytes | None = metal.compose(seed, shorten=MUSIC_SHORTEN,
                                               genre=genre,
                                               intensity=intensity)
        except Exception:  # noqa: BLE001 - a failed compose just goes silent
            data = None
        with self.lock:
            if generation is not None and generation != self.compose_generation:
                return  # superseded by a track taken from the prepared slot
            self.pending = data

    def update(self, dt: float = 0.0) -> None:
        if not self.enabled:
            return
        if abs(self.duck - self.duck_target) > 1e-3:
            if dt <= 0.0:
                self.duck = self.duck_target
            else:
                blend = 1.0 - math.exp(-dt / MUSIC_DUCK_FADE)
                self.duck += (self.duck_target - self.duck) * blend
            self._apply_volume()
        if self.want_new and not (self.thread and self.thread.is_alive()):
            self._start(self.want_genre, self.intensity)
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

    def set_duck(self, factor: float) -> None:
        """Set the runtime output scale (1.0 = full, 0.0 = silent)."""
        self.duck_target = max(0.0, min(1.0, float(factor)))

    @property
    def level(self) -> float:
        """Effective output level, with mute and ducking folded in."""
        if self.muted:
            return 0.0
        return self.volume * self.duck

    @property
    def volume_percent(self) -> int:
        return round(self.volume * 100)

    def toggle_mute(self) -> bool:
        self.muted = not self.muted
        self._apply_volume()
        return self.muted
