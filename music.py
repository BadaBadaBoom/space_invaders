"""Procedural soundtrack, synthesized at runtime with numpy.

Nothing is stored on disk: every seed produces a different track.  The
composers pick a tempo, a key, riff/motif shapes, drum patterns and a lead
line, then render them through band-limited oscillators and waveshaping.

Everything is mixed down through a shared mastering stage: constant-power
panning, a synthetic stereo reverb, a tempo-synced ping-pong delay, kick
sidechain ducking, glue compression, a master EQ, RMS targeting and a soft
limiter.  The result is 16-bit **stereo** at 44100 Hz, ready to hand straight
to pygame.mixer as a Sound buffer.

Typical render time is a few seconds for ~45 s of audio, which is short
enough to compose a fresh song on a worker thread each wave.
"""

from __future__ import annotations

import math
import random
from typing import ClassVar

import numpy as np

SR = 44100

# Notes are written as MIDI numbers; E2 is 40.
E2 = 40
MINOR = (0, 2, 3, 5, 7, 8, 10)
PHRYGIAN = (0, 1, 3, 5, 7, 8, 10)
HARMONIC_MINOR = (0, 2, 3, 5, 7, 8, 11)
MAJOR = (0, 2, 4, 5, 7, 9, 11)
DORIAN = (0, 2, 3, 5, 7, 9, 10)
MIXOLYDIAN = (0, 2, 4, 5, 7, 9, 10)


def hz(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69.0) / 12.0)


# --------------------------------------------------------------------------- #
# Band-limited oscillators
# --------------------------------------------------------------------------- #

def _polyblep(phase: np.ndarray, dt: np.ndarray | float) -> np.ndarray:
    """PolyBLEP correction around a waveform discontinuity.

    `phase` is the normalised [0, 1) phase of one cycle and `dt` is the phase
    increment per sample (frequency / SR).  The correction removes most of the
    aliasing a naive saw/square would fold back into the audible band.
    """
    out = np.zeros_like(phase, dtype=np.float64)
    start = phase < dt
    if np.any(start):
        step = dt[start] if isinstance(dt, np.ndarray) else dt
        x = phase[start] / step
        out[start] = 2.0 * x - x * x - 1.0
    end = phase > 1.0 - dt
    if np.any(end):
        step = dt[end] if isinstance(dt, np.ndarray) else dt
        x = (phase[end] - 1.0) / step
        out[end] = x * x + 2.0 * x + 1.0
    return out


def _saw_phase(phase: np.ndarray, dt: np.ndarray | float) -> np.ndarray:
    frac = phase % 1.0
    return 2.0 * frac - 1.0 - _polyblep(frac, dt)


def _saw(freq: float, t: np.ndarray) -> np.ndarray:
    dt = min(0.49, freq / SR)
    return _saw_phase(t * freq, dt)


def _pulse_phase(phase: np.ndarray, dt: np.ndarray | float,
                 duty: float = 0.5) -> np.ndarray:
    """A band-limited pulse built from the difference of two band-limited saws."""
    duty = float(np.clip(duty, 0.02, 0.98))
    a = _saw_phase(phase, dt)
    b = _saw_phase(phase + duty, dt)
    return a - b + (2.0 * duty - 1.0)


def _pulse(freq: float, t: np.ndarray, duty: float = 0.5) -> np.ndarray:
    dt = min(0.49, freq / SR)
    return _pulse_phase(t * freq, dt, duty)


def _env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    attack_curve = np.clip(t / max(attack, 1e-4), 0.0, 1.0)
    return attack_curve * np.exp(-t * decay)


def _sustain(n: int, attack: float, release: float) -> np.ndarray:
    t = np.arange(n) / SR
    rise = np.clip(t / max(attack, 1e-4), 0.0, 1.0)
    fall = np.clip((n / SR - t) / max(release, 1e-4), 0.0, 1.0)
    return rise * fall


# --------------------------------------------------------------------------- #
# Voices
# --------------------------------------------------------------------------- #

def guitar(freqs: list[float], dur: float, drive: float = 7.0,
           muted: bool = False) -> np.ndarray:
    """A distorted power chord: several detuned saws through tanh."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = np.zeros(n)
    for f in freqs:
        for cents, gain in ((-9, 0.55), (0, 1.0), (9, 0.55)):
            wave += gain * _saw(f * 2.0 ** (cents / 1200.0), t)
    wave /= 3.0 * len(freqs)
    env = _env(n, 0.003, 30.0 if muted else 5.5)
    if muted:
        wave *= 0.85
    return np.tanh(drive * wave * env)


def bass(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = 0.6 * _saw(freq, t) + 0.7 * np.sin(2.0 * np.pi * freq * t)
    env = _env(n, 0.004, 7.0)
    return np.tanh(2.2 * wave * env)


def lead(freq: float, dur: float, rng: random.Random) -> np.ndarray:
    """A squealing lead line with vibrato and a touch of bending."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    vibrato = 1.0 + 0.008 * np.sin(2.0 * np.pi * (5.5 + rng.random()) * t)
    inst = freq * vibrato
    phase = np.cumsum(inst) / SR
    dt = np.clip(inst / SR, 1e-6, 0.49)
    wave = _saw_phase(phase, dt)
    wave += 0.5 * np.sin(2.0 * np.pi * phase * 2.0)
    env = _env(n, 0.006, 3.2)
    return np.tanh(4.0 * wave * env) * 0.8


def kick(rng: np.random.Generator, dur: float = 0.30) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    freq = 45.0 + 115.0 * np.exp(-t * 26.0)
    phase = 2.0 * np.pi * np.cumsum(freq) / SR
    body = np.sin(phase) * np.exp(-t * 7.5)
    click = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0) * np.exp(-t * 340.0)
    return np.tanh(1.7 * (body + 0.5 * click))


def snare(rng: np.random.Generator, dur: float = 0.20) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0)
    noise *= np.exp(-t * 23.0)
    body = np.sin(2.0 * np.pi * (180.0 + 45.0 * np.exp(-t * 70.0)) * t)
    body *= np.exp(-t * 26.0) * 0.55
    return np.tanh(1.4 * (0.9 * noise + body))


def hat(rng: np.random.Generator, dur: float = 0.07,
        open_hat: bool = False) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0)
    noise *= 0.6 + 0.4 * np.sin(2.0 * np.pi * 7800.0 * t)
    return noise * np.exp(-t * (26.0 if open_hat else 90.0)) * 0.45


def crash(rng: np.random.Generator, dur: float = 1.7) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0)
    shimmer = noise * (0.5 + 0.5 * np.sin(2.0 * np.pi * 6300.0 * t))
    return shimmer * np.exp(-t * 2.6) * 0.5


def square(freq: float, dur: float, duty: float = 0.5,
           decay: float = 8.0) -> np.ndarray:
    """A band-limited pulse wave: the sound of an 8-bit console."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = _pulse(freq, t, duty)
    return np.tanh(1.3 * wave * _env(n, 0.004, decay))


def pluck(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = 0.65 * _saw(freq, t)
    wave += 0.35 * _pulse(freq, t, 0.3)
    wave = np.convolve(wave, np.ones(3, np.float32) / 3.0, mode="same")
    return np.tanh(1.8 * wave * _env(n, 0.003, 11.0))


def pulse_bass(freq: float, dur: float) -> np.ndarray:
    wave = square(freq, dur, 0.5, 9.0)
    return np.convolve(wave, np.ones(4, np.float32) / 4.0, mode="same")


def slap_bass(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = 0.7 * np.sin(2 * np.pi * freq * t) + 0.8 * _saw(freq, t)
    return np.tanh(2.2 * wave * _env(n, 0.002, 14.0))


def clav(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = _pulse(freq, t, 0.24)
    wave = np.convolve(wave, np.ones(2, np.float32) / 2.0, mode="same")
    return wave * _env(n, 0.002, 18.0) * 0.7


def walking_bass(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = 0.8 * np.sin(2 * np.pi * freq * t) + 0.4 * _saw(freq, t)
    return np.tanh(1.2 * wave * _env(n, 0.01, 4.0))


def epiano(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    index = 2.2 * np.exp(-t * 7.0)
    wave = np.sin(2 * np.pi * freq * t + index * np.sin(2 * np.pi * 2 * freq * t))
    wave += 0.3 * np.sin(2 * np.pi * 3.0 * freq * t) * np.exp(-t * 16.0)
    return np.tanh(1.2 * wave * _env(n, 0.004, 3.0)) * 0.85


def horn(freq: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    vibrato = 1.0 + 0.007 * np.sin(2 * np.pi * (5.0 + rng.random() * 0.8) * t)
    inst = freq * vibrato
    phase = np.cumsum(inst) / SR
    dt = np.clip(inst / SR, 1e-6, 0.49)
    wave = _saw_phase(phase, dt)
    wave = np.convolve(wave, np.ones(7, np.float32) / 7.0, mode="same")
    breath = rng.normal(0.0, 1.0, n).astype(np.float32) * 0.06
    return np.tanh(1.6 * (wave + breath) * _env(n, 0.03, 2.6)) * 0.8


def pad_chord(freqs: list[float], dur: float, attack: float = 0.4,
              release: float = 0.7) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = np.zeros(n)
    for f in freqs:
        for cents, gain in ((-8, 0.5), (0, 1.0), (8, 0.5)):
            wave += gain * _saw(f * 2.0 ** (cents / 1200.0), t)
    wave /= max(1, 2 * len(freqs))
    wave *= _sustain(n, attack, release)
    wave = np.convolve(wave, np.ones(6, np.float32) / 6.0, mode="same")
    return np.tanh(1.1 * wave) * 0.75


def string_stab(freqs: list[float], dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = np.zeros(n)
    for f in freqs:
        wave += _saw(f, t) + 0.5 * _saw(f * 2.003, t)
    wave /= max(1, 1.5 * len(freqs))
    wave *= _sustain(n, 0.015, 0.28)
    return np.tanh(1.4 * wave) * 0.8


def sub_bass(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = np.sin(2 * np.pi * freq * t) + 0.2 * _saw(freq, t)
    return np.tanh(1.4 * wave * _sustain(n, 0.08, 0.4)) * 0.8


def bell(freq: float, dur: float) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    wave = np.sin(2 * np.pi * freq * t) * np.exp(-t * 1.8)
    wave += 0.5 * np.sin(2 * np.pi * 2.76 * freq * t) * np.exp(-t * 2.6)
    wave += 0.25 * np.sin(2 * np.pi * 5.4 * freq * t) * np.exp(-t * 4.0)
    return wave * 0.55


def airy(freq: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    vibrato = 1.0 + 0.004 * np.sin(2 * np.pi * 4.2 * t)
    inst = freq * vibrato
    phase = np.cumsum(inst) / SR
    dt = np.clip(inst / SR, 1e-6, 0.49)
    wave = _saw_phase(phase, dt)
    wave = np.convolve(wave, np.ones(9, np.float32) / 9.0, mode="same")
    breath = rng.normal(0.0, 1.0, n).astype(np.float32) * 0.04
    return np.tanh(1.1 * (wave + breath) * _sustain(n, 0.35, 0.6)) * 0.6


def ride(rng: np.random.Generator, dur: float = 0.5) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0)
    tone = 0.25 * np.sin(2 * np.pi * 6200.0 * t)
    return (0.65 * noise + tone) * np.exp(-t * 4.5) * 0.4


def clap(rng: np.random.Generator, dur: float = 0.22) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0)
    env = np.zeros(n)
    for delay in (0.0, 0.010, 0.021):
        d = int(delay * SR)
        env[d:] = np.maximum(env[d:], np.exp(-t[:n - d] * 55.0))
    return noise * env * 0.5


def shaker(rng: np.random.Generator, dur: float = 0.06) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0)
    return noise * np.exp(-t * 70.0) * 0.3


def rim(rng: np.random.Generator, dur: float = 0.05) -> np.ndarray:
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 1700.0 * t) * np.exp(-t * 110.0)
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0) * np.exp(-t * 150.0)
    return (0.7 * noise + 0.5 * tone) * 0.5


def noise_riser(dur: float, rng: np.random.Generator) -> np.ndarray:
    """A reverse-cymbal-style sweep used to mark section changes."""
    n = max(1, int(dur * SR))
    t = np.arange(n) / SR
    noise = np.diff(rng.normal(0.0, 1.0, n), prepend=0.0).astype(np.float32)
    tone = np.sin(2 * np.pi * np.cumsum(180.0 + 1700.0 * (t / dur)) / SR)
    env = (t / dur) ** 2
    tail = min(n, int(0.025 * SR))
    if tail:
        env[-tail:] *= np.linspace(1.0, 0.0, tail)
    return (0.8 * noise + 0.25 * tone) * env * 0.5


def _add(mix: np.ndarray, wave: np.ndarray, start: int, gain: float = 1.0) -> None:
    if start < 0:
        wave = wave[-start:]
        start = 0
    if start >= mix.size:
        return
    end = min(mix.size, start + wave.size)
    if end <= start:
        return
    mix[start:end] += gain * wave[: end - start]


# --------------------------------------------------------------------------- #
# Shared mix bus / mastering
# --------------------------------------------------------------------------- #

def _fold_tail(bus: np.ndarray, song_samples: int) -> np.ndarray:
    """Fold note/effect tails back onto the start for a seamless loop."""
    dry = bus[:song_samples].astype(np.float32, copy=True)
    tail = bus[song_samples:]
    if tail.size:
        take = min(tail.size, dry.size)
        dry[:take] += tail[:take]
    return dry


def _pan_gains(pan: float) -> tuple[float, float]:
    angle = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _comb(x: np.ndarray, delay: int, feedback: float) -> np.ndarray:
    """A vectorised feedback comb: y[n] = x[n] + g * y[n - delay]."""
    y = x.copy()
    n = y.size
    delay = max(1, int(delay))
    for start in range(delay, n, delay):
        end = min(n, start + delay)
        y[start:end] += feedback * y[start - delay:start - delay + (end - start)]
    return y


def _allpass(x: np.ndarray, delay: int, gain: float) -> np.ndarray:
    """A vectorised Schroeder allpass: y = -g*x + x[n-d] + g*y[n-d]."""
    n = x.size
    y = np.zeros_like(x)
    delay = max(1, int(delay))
    for start in range(0, n, delay):
        end = min(n, start + delay)
        y[start:end] = -gain * x[start:end]
        if start >= delay:
            y[start:end] += x[start - delay:start - delay + (end - start)]
            y[start:end] += gain * y[start - delay:start - delay + (end - start)]
    return y


# Freeverb's delay lengths, tuned for 44.1 kHz.
_COMB_DELAYS = (1116, 1188, 1277, 1356)
_ALLPASS_DELAYS = (556, 441)


def _schroeder_reverb(send: np.ndarray, seed: int
                      ) -> tuple[np.ndarray, np.ndarray]:
    """A lush stereo reverb built from comb and allpass filters.

    This is much cheaper than convolving a full-length impulse response.  The
    input is extended with the start of the next loop, then the extra tail is
    folded back, so the reverb wraps seamlessly with the track.
    """
    rng = np.random.default_rng(seed)
    n = send.size
    extra = min(n, int(1.2 * SR))
    prime = min(n, int(1.5 * SR))
    # Prime with the end of the previous loop and append the next loop's
    # start; the middle then behaves like a steady-state periodic reverb.
    source = np.concatenate((send[-prime:], send, send[:extra]))
    spread_r = 20 + int(rng.integers(0, 8))

    def channel(spread: int) -> np.ndarray:
        out = np.zeros_like(source)
        for delay in _COMB_DELAYS:
            out += _comb(source, delay + spread, 0.82)
        out *= 0.25
        for delay in _ALLPASS_DELAYS:
            out = _allpass(out, delay + spread, 0.5)
        return out

    wet_l = channel(0)[prime:]
    wet_r = channel(spread_r)[prime:]
    for wet in (wet_l, wet_r):
        if extra:
            wet[:extra] += wet[n:n + extra]
    wet_l = wet_l[:n]
    wet_r = wet_r[:n]
    kernel = np.ones(5, dtype=np.float32) / 5.0
    wet_l = np.convolve(wet_l, kernel, mode="same")
    wet_r = np.convolve(wet_r, kernel, mode="same")
    energy = math.sqrt(float(np.mean(send * send))) or 1.0
    for wet in (wet_l, wet_r):
        level = math.sqrt(float(np.mean(wet * wet))) or 1.0
        wet *= energy / level
    return wet_l.astype(np.float32), wet_r.astype(np.float32)


def _boom_tail(send: np.ndarray, spread: int) -> np.ndarray:
    """A long, diffuse tail for the one-shot victory explosion.

    Unlike the loop reverb above this one starts from silence, so it decays
    naturally instead of wrapping the next bar back onto the hit.
    """
    out = np.zeros_like(send)
    for delay in (1116, 1277, 1356, 1491):
        out += _comb(send, delay + spread, 0.78)
    out *= 0.25
    for delay in (556, 441):
        out = _allpass(out, delay + spread, 0.5)
    return out


def _ping_pong(send: np.ndarray, delay_samples: int,
               feedback: float = 0.42, taps: int = 7
               ) -> tuple[np.ndarray, np.ndarray]:
    n = send.size
    delay_samples = max(1, int(delay_samples))
    out_l = np.zeros(n, np.float32)
    out_r = np.zeros(n, np.float32)
    dark = np.convolve(send, np.ones(5, np.float32) / 5.0, mode="same")
    gain = 1.0
    total = 0.0
    for tap in range(taps):
        shift = (tap + 1) * delay_samples
        source = send if tap == 0 else dark
        contribution = np.roll(source, shift) * gain
        if tap % 2 == 0:
            out_l += contribution
        else:
            out_r += contribution
        total += gain * gain
        gain *= feedback
    norm = math.sqrt(total) or 1.0
    return out_l / norm, out_r / norm


def _duck_envelope(n: int, kick_hits: list[int], depth: float,
                   release: float = 0.16) -> np.ndarray | None:
    if not kick_hits or depth <= 0.0:
        return None
    length = int(release * SR)
    if length <= 0:
        return None
    t = np.arange(length) / SR
    curve = (1.0 - depth * np.exp(-t / 0.045)).astype(np.float32)
    env = np.ones(n, np.float32)
    for hit in kick_hits:
        pos = int(hit) % n
        end = pos + length
        if end <= n:
            np.minimum(env[pos:end], curve, out=env[pos:end])
        else:
            first = n - pos
            np.minimum(env[pos:n], curve[:first], out=env[pos:n])
            np.minimum(env[0:end - n], curve[first:], out=env[0:end - n])
    return env


def _glue_compress(stereo: np.ndarray, threshold_db: float = -20.0,
                   ratio: float = 1.9, attack_ms: float = 15.0,
                   release_ms: float = 180.0, block: int = 128) -> np.ndarray:
    """Block-based stereo-linked glue compression with a circular envelope."""
    n = stereo.shape[0]
    if n == 0:
        return stereo
    nb = max(1, (n + block - 1) // block)
    padded = np.zeros((nb * block, 2), np.float32)
    padded[:n] = stereo
    blocks = padded.reshape(nb, block, 2)
    rms = np.sqrt(np.mean(blocks * blocks, axis=(1, 2)) + 1e-12)
    at = math.exp(-block / max(1.0, attack_ms * 0.001 * SR))
    rt = math.exp(-block / max(1.0, release_ms * 0.001 * SR))

    def follower(start: float) -> tuple[np.ndarray, float]:
        env = np.empty(nb, np.float32)
        value = start
        for i in range(nb):
            level = float(rms[i])
            coeff = at if level > value else rt
            value = coeff * value + (1.0 - coeff) * level
            env[i] = value
        return env, value

    env, _ = follower(0.0)
    # Run again from the previous pass's end value so the loop seam is smooth.
    env, _ = follower(float(env[-1]))
    threshold = 10.0 ** (threshold_db / 20.0)
    gain = np.ones(nb, np.float32)
    over = env > threshold
    if np.any(over):
        gain[over] = (threshold / env[over]) ** (1.0 - 1.0 / ratio)
    padded_gain = np.concatenate((gain[-2:], gain, gain[:2]))
    gain = np.convolve(padded_gain, np.ones(5, np.float32) / 5.0,
                       mode="same")[2:-2].astype(np.float32)
    smooth = np.repeat(gain, block)[:n]
    return stereo * smooth[:, None]


_EQ_TAPS = 127
_eq_kernel: np.ndarray | None = None


def _get_eq_kernel() -> np.ndarray:
    """Design a short, gentle master EQ FIR once per process."""
    global _eq_kernel
    if _eq_kernel is not None:
        return _eq_kernel
    n = 16384
    freq = np.maximum(np.fft.rfftfreq(n, 1.0 / SR), 1e-6)
    mag = np.ones_like(freq)
    mag *= 1.0 - 0.12 * np.exp(-0.5 * (np.log2(freq / 3200.0) / 0.8) ** 2)
    mag *= 1.0 + 0.08 * np.clip(np.log2(freq / 7000.0) / 2.0, 0.0, 1.0)
    mag *= 1.0 / (1.0 + (freq / 19500.0) ** 4)
    impulse = np.fft.irfft(mag, n)
    half = _EQ_TAPS // 2
    # The zero-phase impulse sits at index 0 and wraps; rebuild it around 0.
    kernel = np.concatenate((impulse[-half:], impulse[:half + 1]))
    kernel *= np.hanning(_EQ_TAPS)
    probe = abs(np.fft.rfft(kernel, 32768))
    reference = float(np.max(probe)) or 1.0
    kernel /= reference
    _eq_kernel = kernel.astype(np.float32)
    return _eq_kernel


def _master_eq(left: np.ndarray, right: np.ndarray,
               ) -> tuple[np.ndarray, np.ndarray]:
    """Tame the presence band, add air and remove any DC offset."""
    kernel = _get_eq_kernel()
    out_l = np.convolve(left, kernel, mode="same").astype(np.float32)
    out_r = np.convolve(right, kernel, mode="same").astype(np.float32)
    out_l -= float(np.mean(out_l))
    out_r -= float(np.mean(out_r))
    return out_l, out_r


def _mixdown(buses: dict[str, np.ndarray], song_samples: int,
             gains: dict[str, float], pans: dict[str, float],
             reverb_sends: dict[str, float], delay_sends: dict[str, float],
             kick_hits: list[int], duck_buses: tuple[str, ...],
             duck_depth: float, delay_step: float, seed: int,
             target_rms: float = 0.14) -> bytes:
    """Sum the mono buses into a mastered 16-bit stereo int16 buffer."""
    if song_samples <= 0:
        return b""
    prepared: dict[str, np.ndarray] = {}
    duck = _duck_envelope(song_samples, kick_hits, duck_depth) if duck_buses else None
    for name, raw_bus in buses.items():
        bus = _fold_tail(raw_bus, song_samples)
        gain = gains.get(name, 0.0)
        if not gain:
            continue
        # Equalise bus loudness so a quiet pad or clav part is not buried by
        # the kick and bass, then let the per-genre gain set the balance.
        rms = math.sqrt(float(np.mean(bus * bus)))
        scale = min(6.0, gain * 0.10 / max(rms, 1e-5))
        bus = bus * scale
        if duck is not None and name in duck_buses:
            bus = bus * duck
        prepared[name] = bus

    left = np.zeros(song_samples, np.float32)
    right = np.zeros(song_samples, np.float32)
    for name, bus in prepared.items():
        gl, gr = _pan_gains(pans.get(name, 0.0))
        left += bus * gl
        right += bus * gr

    send = np.zeros(song_samples, np.float32)
    for name, level in reverb_sends.items():
        if level and name in prepared:
            send += prepared[name] * level
    if np.any(send):
        wet_l, wet_r = _schroeder_reverb(send, seed)
        left += wet_l * 0.32
        right += wet_r * 0.32

    echo = np.zeros(song_samples, np.float32)
    for name, level in delay_sends.items():
        if level and name in prepared:
            echo += prepared[name] * level
    if np.any(echo):
        delay_samples = max(1, round(delay_step * 0.75 * SR))
        echo_l, echo_r = _ping_pong(echo, delay_samples)
        left += echo_l * 0.26
        right += echo_r * 0.26

    # A gentle mid/side lift makes the reverb and panned parts feel wider
    # without hollowing out kick, bass or the mono fold-down.
    mid = (left + right) * 0.5
    side = (left - right) * 0.5
    side *= 1.35
    left = mid + side
    right = mid - side

    left, right = _master_eq(left, right)
    stereo = np.stack((left, right), axis=1)
    stereo = _glue_compress(stereo)

    rms = math.sqrt(float(np.mean(stereo * stereo)))
    if rms > 1e-6:
        stereo *= target_rms / rms
    stereo = np.tanh(1.15 * stereo) / 1.15

    peak = float(np.max(np.abs(stereo))) or 1.0
    if peak > 0.98:
        stereo *= 0.98 / peak
    elif peak < 0.55:
        stereo *= 0.85 / peak

    fade = min(int(0.003 * SR), stereo.shape[0] // 2)
    if fade > 0:
        stereo[:fade] *= np.linspace(0.0, 1.0, fade)[:, None]
        stereo[-fade:] *= np.linspace(1.0, 0.0, fade)[:, None]

    samples = np.clip(stereo * 32767.0, -32768, 32767).astype(np.int16)
    return samples.reshape(-1).tobytes()


# --------------------------------------------------------------------------- #
# Metal composer
# --------------------------------------------------------------------------- #

# 16th-note hit maps: 1 = play, 0 = silence.
RIFF_RHYTHMS = {
    "gallop":  [1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0],
    "thrash":  [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
    "maiden":  [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    "sync":    [1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 0, 1],
    "halftime":[1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
    "stomp":   [1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1],
}

METAL_SECTION_LEVELS = {
    "intro": 0.72, "verse": 0.90, "chorus": 1.10, "breakdown": 0.72,
    "solo": 1.02, "verse2": 0.95, "outro": 0.60,
}


class Composer:
    """Builds one complete, never-quite-the-same metal track."""

    def __init__(self, seed: int | None = None, shorten: float = 1.0) -> None:
        self.rng = random.Random(seed)
        self.npr = np.random.default_rng(self.rng.getrandbits(63))
        self.master_seed = self.rng.getrandbits(63)
        r = self.rng
        self.tempo = r.choice((148, 156, 164, 172, 180))
        self.beat = 60.0 / self.tempo
        self.step = self.beat / 4.0
        self.step_samples = self.step * SR
        self.scale = r.choice((MINOR, MINOR, PHRYGIAN, HARMONIC_MINOR))
        self.root = E2
        self.shorten = shorten

        self.riff_a, self.riff_b = self._make_riffs()
        self.sections = self._make_sections()

        bars = sum(count for _, count in self.sections)
        self.total_steps = bars * 16
        self.song_samples = round(self.total_steps * self.step_samples)
        # Extra room for note tails, which are folded back onto the start so
        # the track loops seamlessly.
        self.tail_samples = 2 * SR
        self.total_samples = self.song_samples + self.tail_samples

        self.gtr = np.zeros(self.total_samples, dtype=np.float32)
        self.bass_bus = np.zeros(self.total_samples, dtype=np.float32)
        self.drum_bus = np.zeros(self.total_samples, dtype=np.float32)
        self.lead_bus = np.zeros(self.total_samples, dtype=np.float32)
        self.pos = 0  # in 16th steps
        self.section = "intro"
        self.gain_scale = 1.0
        self.kick_hits: list[int] = []
        self.lead_motif: list[list[float]] | None = None
        self.lead_cycle = -1

    # -- composition ------------------------------------------------------- #

    def _degree(self, index: int) -> float:
        octave, step = divmod(index, len(self.scale))
        return self.root + 12 * octave + self.scale[step]

    def _make_riffs(self) -> tuple[dict, dict]:
        r = self.rng
        names = list(RIFF_RHYTHMS)
        rhythm_a = RIFF_RHYTHMS[r.choice(names)]
        rhythm_b = RIFF_RHYTHMS[r.choice(names)]

        def notes_from(rhythm: list[int], degree_choices: list[int]) -> dict:
            hits = [i for i, on in enumerate(rhythm) if on]
            degrees: dict[int, int] = {}
            current = r.choice(degree_choices)
            for i in hits:
                if i % 4 == 0 and r.random() < 0.45:
                    current = r.choice(degree_choices)
                if i == hits[-1] and r.random() < 0.4:
                    degrees[i] = current + 7  # octave-ish finish
                else:
                    degrees[i] = current
            return {"rhythm": rhythm, "degrees": degrees}

        root_choices = [0, 0, 0, 2, 3, 4, 5, -1]
        riff_a = notes_from(rhythm_a, root_choices)
        riff_b = notes_from(rhythm_b, [0, 0, 3, 4, 5, 3])
        return riff_a, riff_b

    def _make_sections(self) -> list[tuple[str, int]]:
        s = self.shorten
        plan = [
            ("intro", 4),
            ("verse", 8),
            ("chorus", 8),
            ("breakdown", 4),
            ("solo", 8),
            ("verse2", 4),
            ("outro", 2),
        ]
        if s < 1.0:
            plan = [(name, max(1, int(count * s))) for name, count in plan]
        return plan

    # -- rendering --------------------------------------------------------- #

    def render(self) -> bytes:
        total = self.song_samples
        for section, bars in self.sections:
            for bar in range(bars):
                last_bar = bar == bars - 1
                self._render_bar(section, bar, last_bar)

        gains = {"gtr": 0.55, "bass": 0.38, "drums": 0.42, "lead": 0.30}
        pans = {"gtr": -0.45, "bass": 0.0, "drums": 0.05, "lead": 0.38}
        reverb = {"gtr": 0.10, "bass": 0.0, "drums": 0.05, "lead": 0.18}
        delay = {"gtr": 0.0, "bass": 0.0, "drums": 0.0, "lead": 0.20}
        return _mixdown(
            {"gtr": self.gtr, "bass": self.bass_bus,
             "drums": self.drum_bus, "lead": self.lead_bus},
            total, gains, pans, reverb, delay,
            self.kick_hits, ("bass",), 0.28, self.beat,
            self.master_seed,
        )

    def _render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        self.section = section
        self.gain_scale = METAL_SECTION_LEVELS.get(section, 1.0)
        start_step = self.pos
        riff = self.riff_b if section == "chorus" else self.riff_a
        rhythm = riff["rhythm"]

        # A big open chord to announce each section.
        if bar == 0 or (section in ("chorus", "solo") and bar == 4):
            self._chord(start_step, self._degree(0), duration=self.beat * 2,
                        gain=0.95)
        # Breakdown: a sustained chord every bar keeps the heavy part from
        # dropping out, even when the riff is sparse.
        if section in ("breakdown", "intro"):
            self._chord(start_step, self._degree(0), duration=self.beat * 4,
                        gain=0.45 if section == "intro" else 0.55)

        # Guitars and bass on the riff grid.
        for step, on in enumerate(rhythm):
            if not on:
                continue
            degree = riff["degrees"].get(step, 0)
            root = self._degree(degree + (3 if section == "chorus" else 0))
            accent = (step % 4 == 0)
            muted = not accent or section in ("verse", "verse2")
            dur = self.step * (0.9 if muted else 1.6)
            self._chord(start_step + step, root, duration=dur,
                        muted=muted, gain=1.0 if accent else 0.8)
            self._bass_note(start_step + step, root, dur * 1.1,
                            gain=0.95 if accent else 0.7)

        # Breakdown: let chords ring and hit hard and slow.
        if section == "breakdown" and bar % 2 == 1:
            self._chord(start_step + 8, self._degree(0), duration=self.beat * 2,
                        gain=1.0)

        if last_bar and section in ("intro", "verse", "verse2"):
            _add(self.drum_bus, noise_riser(self.beat * 4, self.npr),
                 int(start_step * self.step_samples), 0.34)
        if last_bar and section in ("chorus", "solo"):
            _add(self.drum_bus, noise_riser(self.beat * 2, self.npr),
                 int((start_step + 8) * self.step_samples), 0.22)

        self._render_drums(start_step, section, bar, last_bar)

        if section == "solo":
            self._render_lead(start_step, bar)

        self.pos += 16

    def _chord(self, step: int, root: float, duration: float,
               muted: bool = False, gain: float = 1.0) -> None:
        start = int(step * self.step_samples)
        freqs = [hz(root), hz(root + 7), hz(root + 12)]
        _add(self.gtr, guitar(freqs, duration, muted=muted), start,
             gain * self.gain_scale)

    def _bass_note(self, step: int, root: float, duration: float,
                   gain: float = 1.0) -> None:
        start = int(step * self.step_samples)
        _add(self.bass_bus, bass(hz(root - 12), duration), start,
             gain * self.gain_scale)

    def _render_drums(self, start_step: int, section: str, bar: int,
                      last_bar: bool) -> None:
        r = self.npr
        step_samples = self.step_samples

        if section == "intro":
            kicks, snares, hats = (0, 4, 8, 12), (), tuple(range(0, 16, 2))
        elif section == "breakdown":
            kicks, snares, hats = (0, 6, 10), (8,), (0, 4, 8, 12)
        elif section in ("chorus", "solo"):
            kicks = tuple(range(16))
            snares = (4, 12)
            hats = tuple(range(0, 16, 2))
        else:
            kicks = (0, 3, 6, 8, 11, 14)
            snares = (4, 12)
            hats = tuple(range(0, 16, 2))

        def at(step: int, wave: np.ndarray, gain: float = 1.0,
               jitter: float = 0.0) -> None:
            pos = ((start_step + step) * step_samples
                   + r.uniform(-jitter, jitter) * SR)
            _add(self.drum_bus, wave, max(0, int(pos)),
                 gain * self.gain_scale)

        for step in kicks:
            jitter = 0.002 if step % 4 == 0 else 0.004
            pos = ((start_step + step) * step_samples
                   + r.uniform(-jitter, jitter) * SR)
            at(step, kick(r), (1.0 if step % 4 == 0 else 0.8)
               * r.uniform(0.9, 1.08), jitter)
            self.kick_hits.append(max(0, int(pos)))
        for step in snares:
            at(step, snare(r), 0.9 * r.uniform(0.9, 1.06), 0.003)
        for step in hats:
            at(step, hat(r, open_hat=(section in ("chorus", "solo")
                                      and step % 4 == 2)),
               0.8 * r.uniform(0.82, 1.1), 0.005)

        # Two-bar variation: ghost notes and a shifted accent on odd bars.
        if section in ("verse", "verse2", "chorus") and bar % 2 == 1:
            for step in (7, 15):
                if r.random() < 0.45:
                    at(step, snare(r), 0.18 * r.uniform(0.8, 1.2), 0.006)
            if section == "chorus" and r.random() < 0.5:
                at(10, kick(r), 0.55, 0.004)

        if bar == 0 or (section in ("chorus", "solo") and bar == 4):
            at(0, crash(r), 0.9, 0.0)

        # Fill on the last bar of a section.
        if last_bar and section in ("verse", "chorus", "verse2", "solo"):
            for offset, step in enumerate((12, 13, 14, 15)):
                at(step, snare(r), (0.72 + 0.08 * offset)
                   * r.uniform(0.88, 1.08), 0.005)

    def _make_lead_motif(self) -> list[list[float]]:
        r = self.rng
        degrees = [d + 12 for d in self.scale] + [d + 24 for d in self.scale]
        motif: list[list[float]] = []
        step = 0
        while step < 16:
            if r.random() < 0.72:
                length = r.choice((1, 1, 2, 2, 3, 4))
                motif.append([step, length, r.choice(degrees),
                              r.uniform(0.82, 1.05)])
                step += length
            else:
                step += 1
        return motif or [[0, 4, 12, 1.0]]

    def _vary_lead_motif(self, motif: list[list[float]]) -> None:
        if not motif:
            return
        roll = self.rng.random()
        if roll < 0.45:
            i = self.rng.randrange(len(motif))
            motif[i][2] += self.rng.choice((-2, -1, 1, 2))
        elif roll < 0.75:
            i = self.rng.randrange(len(motif))
            motif[i][3] = max(0.65, min(1.1, motif[i][3]
                                         + self.rng.uniform(-0.1, 0.1)))
        elif roll < 0.9 and len(motif) > 2:
            i = self.rng.randrange(len(motif))
            motif[i][2] += 12

    def _render_lead(self, start_step: int, bar: int) -> None:
        if self.lead_motif is None:
            self.lead_motif = self._make_lead_motif()
        cycle = bar // 2
        if cycle != self.lead_cycle:
            self.lead_cycle = cycle
            self._vary_lead_motif(self.lead_motif)
        for step, length, degree, velocity in self.lead_motif:
            note = hz(self.root + degree)
            _add(self.lead_bus,
                 lead(note, length * self.step * 0.95, self.rng),
                 int((start_step + step) * self.step_samples),
                 0.9 * velocity * self.gain_scale)


# --------------------------------------------------------------------------- #
# Genre engine
# --------------------------------------------------------------------------- #

class GenreComposer:
    """Shared engine for the non-metal genres.

    Subclasses define a tempo/key/scale palette, a bar-wise chord progression,
    a section plan and a `render_bar`.  The base class handles placement,
    motif memory, humanised grooves, looping the tail onto the start, and the
    shared stereo mix bus / mastering stage.
    """

    name = "generic"
    tempos = (110,)
    scales = (MINOR,)
    progression = (0, 5, 3, 4)
    sections = (("intro", 4), ("main", 8), ("outro", 4))
    mix_gains: ClassVar[dict[str, float]] = {
        "chords": 0.5, "bass": 0.5, "drums": 0.5, "lead": 0.3,
    }
    pans: ClassVar[dict[str, float]] = {
        "drums": 0.0, "bass": 0.0, "chords": -0.42, "pad": 0.34,
        "arp": 0.55, "lead": -0.34, "extra": 0.0, "perc": 0.48,
    }
    reverb_sends: ClassVar[dict[str, float]] = {
        "drums": 0.05, "bass": 0.0, "chords": 0.16, "pad": 0.28,
        "arp": 0.26, "lead": 0.22, "extra": 0.10, "perc": 0.10,
    }
    delay_sends: ClassVar[dict[str, float]] = {
        "drums": 0.0, "bass": 0.0, "chords": 0.08, "pad": 0.0,
        "arp": 0.12, "lead": 0.22, "extra": 0.0, "perc": 0.0,
    }
    duck_buses = ("bass", "pad")
    duck_depth = 0.30
    swing = 0.0
    section_levels: ClassVar[dict[str, float]] = {
        "intro": 0.72, "verse": 0.95, "main": 1.0, "chorus": 1.12,
        "chorus2": 1.12, "solo": 1.05, "solo2": 1.05, "breakdown": 0.68,
        "break": 0.70, "head": 0.95, "head2": 1.02, "drift": 0.80,
        "deep": 1.0, "return": 0.85, "a": 1.0, "b": 1.06, "a2": 1.06,
        "groove": 1.0, "groove2": 1.05, "outro": 0.55,
    }

    def __init__(self, seed: int | None = None, shorten: float = 1.0) -> None:
        r = random.Random(seed)
        self.rng = r
        self.npr = np.random.default_rng(r.getrandbits(63))
        self.master_seed = r.getrandbits(63)
        self.tempo = r.choice(self.tempos)
        self.beat = 60.0 / self.tempo
        self.step = self.beat / 4.0
        self.step_samples = self.step * SR
        self.scale = r.choice(self.scales)
        self.root = E2
        shorten = max(0.02, shorten)
        self.plan = [(name, max(1, round(bars * shorten)))
                     for name, bars in self.sections]
        self.total_steps = sum(bars for _, bars in self.plan) * 16
        self.song_samples = round(self.total_steps * self.step_samples)
        self.tail_samples = 2 * SR
        self.total_samples = self.song_samples + self.tail_samples
        names = set(self.mix_gains) | {"chords", "bass", "drums", "lead",
                                       "pad", "arp", "extra", "perc"}
        self.buses = {name: np.zeros(self.total_samples, np.float32)
                      for name in names}
        self.pos = 0
        self.section = self.plan[0][0]
        self.kick_hits: list[int] = []
        self.motifs: dict[str, list[list[float]]] = {}
        self.motif_cycle: dict[str, int] = {}

    # -- helpers ----------------------------------------------------------- #

    def deg(self, degree: int) -> int:
        octave, step = divmod(degree, len(self.scale))
        return self.root + 12 * octave + self.scale[step]

    def chord_notes(self, degree: int, size: int = 3) -> list[int]:
        """Scale-correct triad or seventh rooted at a scale degree."""
        return [self.deg(degree + offset) for offset in (0, 2, 4, 6)[:size]]

    def add(self, bus: str, wave: np.ndarray, step: float,
            gain: float = 1.0) -> None:
        level = self.section_levels.get(self.section, 1.0)
        _add(self.buses[bus], wave, round(step * self.step_samples),
             gain * level)

    def _make_motif(self, density: float,
                    lengths: tuple[int, ...]) -> list[list[float]]:
        motif: list[list[float]] = []
        step = 0
        while step < 16:
            if self.rng.random() < density:
                length = self.rng.choice(lengths)
                degree = self.rng.choice((-2, -1, 0, 0, 1, 2, 3, 4, 5, 7))
                octave = self.rng.choice((12, 12, 24))
                motif.append([step, length, degree, octave,
                              self.rng.uniform(0.82, 1.08)])
                step += length
            else:
                step += 1
        return motif or [[0, 4, 0, 12, 1.0]]

    def _vary_motif(self, motif: list[list[float]]) -> None:
        if not motif:
            return
        roll = self.rng.random()
        if roll < 0.42:
            i = self.rng.randrange(len(motif))
            motif[i][2] += self.rng.choice((-2, -1, 1, 2))
        elif roll < 0.72:
            i = self.rng.randrange(len(motif))
            motif[i][3] = 24 if motif[i][3] == 12 else 12
        elif roll < 0.9:
            i = self.rng.randrange(len(motif))
            motif[i][4] = max(0.65, min(1.15, motif[i][4]
                                       + self.rng.uniform(-0.08, 0.08)))

    def melody(self, bus: str, start: float, voice, density: float = 0.6,
               octaves: tuple[int, ...] = (12, 24),
               lengths: tuple[int, ...] = (1, 2, 2, 3, 4),
               gain: float = 0.8, swing: float = 0.0, bar: int = 0,
               root_deg: int = 0) -> None:
        """Play a remembered 1-bar motif, varying it every two bars."""
        if bus not in self.motifs:
            self.motifs[bus] = self._make_motif(density, lengths)
        motif = self.motifs[bus]
        cycle = bar // 2
        if self.motif_cycle.get(bus, -1) != cycle:
            self.motif_cycle[bus] = cycle
            if cycle:
                self._vary_motif(motif)

        for step, length, degree, octave, velocity in motif:
            if step >= 16:
                continue
            note = hz(self.deg(root_deg + degree) + octave)
            offset = swing if step % 4 == 2 else 0.0
            self.add(bus, voice(note, length * self.step * 0.95),
                     start + step + offset, gain * velocity)

    def riser(self, start: float, duration: float, gain: float = 0.3) -> None:
        self.add("extra", noise_riser(duration, self.npr), start, gain)

    def groove(self, start: float, kicks=(), snares=(), ghost_snares=(),
               hats=(), open_hats=(), claps=(), rides=(), shakers=(),
               crash_at_start: bool = False, fill: bool = False,
               swing: float = 0.0, ride_gain: float = 0.45,
               bar: int = 0) -> None:
        def pos(step, jitter=0.0):
            return (start + step + (swing if step % 4 == 2 else 0.0)
                    + self.rng.uniform(-jitter, jitter))

        def vel(base, amount=0.12):
            return base * self.rng.uniform(1.0 - amount, 1.0 + amount)

        for step in kicks:
            jitter = 0.002 if step % 4 == 0 else 0.004
            place = pos(step, jitter)
            self.add("drums", kick(self.npr), place,
                     vel(1.0 if step % 4 == 0 else 0.8, 0.08))
            self.kick_hits.append(max(0, round(place * self.step_samples)))
        for step in snares:
            self.add("drums", snare(self.npr), pos(step, 0.003), vel(0.85))
        for step in ghost_snares:
            self.add("drums", snare(self.npr), pos(step, 0.006), vel(0.22, 0.18))
        for step in hats:
            self.add("perc", hat(self.npr, open_hat=(step in open_hats)),
                     pos(step, 0.006),
                     vel(0.55 if step in open_hats else 0.4, 0.16))
        for step in claps:
            self.add("perc", clap(self.npr), pos(step, 0.005), vel(0.65))
        for step in rides:
            self.add("perc", ride(self.npr), pos(step, 0.007),
                     vel(ride_gain))
        for step in shakers:
            self.add("perc", shaker(self.npr), pos(step, 0.008), vel(0.25))
        if crash_at_start:
            self.add("perc", crash(self.npr), start, 0.8)
        if fill:
            for i, step in enumerate((12, 13, 14, 15)):
                self.add("drums", snare(self.npr), pos(step, 0.005),
                         vel(0.4 + 0.12 * i))
        # Every second bar gets a few quiet 16th-note hat links, so a two-bar
        # pattern never repeats exactly.
        if bar % 2 == 1:
            for step in (3, 7, 11, 15):
                if self.rng.random() < 0.42:
                    self.add("perc", hat(self.npr), pos(step, 0.008),
                             vel(0.2, 0.2))

    # -- rendering --------------------------------------------------------- #

    def render(self) -> bytes:
        for section, bars in self.plan:
            self.section = section
            for bar in range(bars):
                self.render_bar(section, bar, bar == bars - 1)
                self.pos += 16

        gains = dict(self.mix_gains)
        gains["extra"] = 0.4
        gains.setdefault("perc", 0.55)
        return _mixdown(
            self.buses, self.song_samples, gains, self.pans,
            self.reverb_sends, self.delay_sends, self.kick_hits,
            self.duck_buses, self.duck_depth, self.beat, self.master_seed,
        )

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        raise NotImplementedError


class SynthwaveComposer(GenreComposer):
    """Neon-night arpeggios, gated snares and a widescreen pad."""

    name = "synthwave"
    tempos = (98, 104, 112, 118)
    scales = (MINOR, HARMONIC_MINOR)
    progression = (0, 5, 3, 4)
    sections = (("intro", 4), ("main", 8), ("chorus", 8),
                ("solo", 8), ("outro", 4))
    mix_gains: ClassVar[dict[str, float]] = {
        "pad": 0.5, "bass": 0.55, "drums": 0.6,
                 "arp": 0.3, "lead": 0.3}

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        start = self.pos
        root_deg = self.progression[bar % len(self.progression)]
        root = self.deg(root_deg)
        chord = self.chord_notes(root_deg, 4)

        self.add("pad", pad_chord([hz(n) for n in chord],
                                  self.beat * 3.9, 0.25, 0.45), start, 0.9)

        for step in range(0, 16, 2):
            note = root + (12 if step in (6, 14) else 0)
            self.add("bass", pulse_bass(hz(note), self.step * 1.6),
                     start + step, 0.9 if step % 4 == 0 else 0.65)

        if section != "intro":
            for step in range(16):
                note = chord[step % len(chord)] + 24
                self.add("arp", pluck(hz(note), self.step * 0.75),
                         start + step, 0.5)

        if section in ("chorus", "solo"):
            self.melody("lead", start,
                        lambda f, d: lead(f, d, self.rng),
                        density=0.55, gain=0.45, bar=bar,
                        root_deg=root_deg)

        if last_bar and section in ("main", "intro"):
            self.riser(start + 8, self.beat * 2, 0.24)

        self.groove(
            start,
            kicks=(0, 4, 8, 12),
            snares=(4, 12),
            hats=tuple(range(0, 16, 2)),
            open_hats=(2, 6, 10, 14),
            crash_at_start=(bar == 0 and section not in ("intro", "outro")),
            fill=last_bar and section in ("main", "chorus", "solo"),
            bar=bar,
        )


class ChiptuneComposer(GenreComposer):
    """Fast pulse arpeggios, blocky bass and noise-channel drums."""

    name = "chiptune"
    tempos = (150, 160, 172, 180)
    scales = (MAJOR, MINOR, DORIAN)
    progression = (0, 5, 2, 6)
    sections = (("intro", 2), ("a", 8), ("b", 8),
                ("a2", 4), ("outro", 2))
    mix_gains: ClassVar[dict[str, float]] = {
        "chords": 0.18, "bass": 0.5, "drums": 0.5,
                 "arp": 0.35, "lead": 0.45}

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        start = self.pos
        root_deg = self.progression[bar % len(self.progression)]
        root = self.deg(root_deg)
        chord = self.chord_notes(root_deg, 3)

        for step in range(0, 16, 2):
            note = root + (12 if step % 8 == 6 else 0)
            self.add("bass", pulse_bass(hz(note), self.step * 1.4),
                     start + step, 0.9)

        arp_tones = chord + [n + 12 for n in chord]
        if section != "outro":
            for step in range(16):
                note = arp_tones[step % len(arp_tones)] + 12
                self.add("arp", square(hz(note), self.step * 0.8, 0.25),
                         start + step, 0.4)

        if section in ("b", "a2"):
            self.melody(
                "lead", start,
                lambda f, d: square(f, d, 0.35, 6.0),
                density=0.6, gain=0.5, bar=bar, root_deg=root_deg,
            )

        for step in (0, 4, 8, 12):
            self.add("chords", square(hz(chord[0] + 12),
                                      self.step * 0.9, 0.5), start + step, 0.25)

        if last_bar and section == "intro":
            self.riser(start + 8, self.beat * 2, 0.20)

        self.groove(
            start,
            kicks=(0, 8),
            snares=(4, 12),
            hats=tuple(range(0, 16, 2)),
            crash_at_start=(bar == 0 and section not in ("intro", "outro")),
            fill=last_bar and section in ("a", "b"),
            bar=bar,
        )


class FunkComposer(GenreComposer):
    """Syncopated slap bass, clav scratches and tight pocket drums."""

    name = "funk"
    tempos = (102, 110, 116)
    scales = (DORIAN, MINOR, MIXOLYDIAN)
    progression = (0, 3, 0, 6)
    sections = (("intro", 2), ("groove", 8), ("break", 2),
                ("groove2", 8), ("outro", 2))
    mix_gains: ClassVar[dict[str, float]] = {
        "chords": 0.45, "bass": 0.62, "drums": 0.62,
                 "lead": 0.2, "pad": 0.32}
    duck_depth = 0.24

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        start = self.pos
        root_deg = self.progression[bar % len(self.progression)]
        root = self.deg(root_deg)
        chord = self.chord_notes(root_deg, 4)

        # A quiet organ bed keeps the pocket from sounding empty between hits.
        self.add("pad", pad_chord([hz(n) for n in chord],
                                  self.beat * 3.8, 0.05, 0.4), start, 0.8)

        for step in (2, 3, 6, 7, 10, 11, 14, 15):
            if self.rng.random() < 0.7:
                for note in chord[:3]:
                    self.add("chords", clav(hz(note + 12),
                                            self.step * 0.55),
                             start + step, 0.3)

        for i, step in enumerate((0, 3, 6, 8, 10, 14)):
            note = root + (12 if step in (6, 14) else 0)
            self.add("bass", slap_bass(hz(note), self.step * 1.4),
                     start + step, 1.0 if i % 2 == 0 else 0.75)

        if section in ("groove", "groove2") and bar % 4 == 3:
            for step, degree in ((12, 0), (14, 2)):
                self.add("lead",
                         horn(hz(self.deg(root_deg + degree) + 12),
                              self.step * 1.2, self.npr),
                         start + step, 0.4)

        if last_bar and section == "intro":
            self.riser(start + 8, self.beat * 2, 0.20)

        self.groove(
            start,
            kicks=(0, 7, 8, 10),
            snares=(4, 12),
            ghost_snares=(3, 11),
            hats=tuple(range(16)),
            open_hats=(14,),
            crash_at_start=(bar == 0 and section not in ("intro", "outro")),
            fill=last_bar,
            bar=bar,
        )


class JazzComposer(GenreComposer):
    """Walking bass, swung ride cymbal and smoky e-piano comping."""

    name = "jazz"
    tempos = (108, 118, 126)
    scales = (DORIAN, MINOR, MIXOLYDIAN, MAJOR)
    progression = (0, 3, 6, 0)
    sections = (("head", 8), ("solo", 8), ("solo2", 8),
                ("head2", 4), ("outro", 2))
    mix_gains: ClassVar[dict[str, float]] = {
        "chords": 0.38, "bass": 0.5, "drums": 0.4,
                 "lead": 0.3, "pad": 0.1}
    swing = 0.65
    duck_depth = 0.16

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        start = self.pos
        root_deg = self.progression[bar % len(self.progression)]
        root = self.deg(root_deg)
        chord = self.chord_notes(root_deg, 4)
        next_root = self.deg(self.progression[(bar + 1) % len(self.progression)])

        walk = [root, root + self.scale[2], root + 7, next_root - 1]
        for i, note in enumerate(walk):
            self.add("bass", walking_bass(hz(note), self.beat * 0.95),
                     start + i * 4, 0.85)

        for step in (2, 6, 10, 14):
            for note in chord:
                self.add("chords", epiano(hz(note + 12), self.step * 1.7),
                         start + step + self.swing, 0.32)

        if section in ("solo", "solo2", "head"):
            self.melody("lead", start,
                        lambda f, d: horn(f, d, self.npr),
                        density=0.35, lengths=(2, 2, 3, 4),
                        gain=0.4, swing=self.swing, bar=bar,
                        root_deg=root_deg)

        self.groove(
            start,
            kicks=(0,),
            ghost_snares=(11,) if bar % 2 else (3,),
            hats=(0, 4, 8, 12),
            rides=(0, 6, 8, 14),
            swing=self.swing,
            ride_gain=0.5,
            fill=last_bar and section in ("solo", "solo2"),
            bar=bar,
        )


class AmbientComposer(GenreComposer):
    """Slow drifting pads, sub-bass and distant bells."""

    name = "ambient"
    tempos = (58, 64, 70)
    scales = (MINOR, HARMONIC_MINOR, PHRYGIAN)
    progression = (0, 5, 3, 4)
    sections = (("drift", 6), ("deep", 8), ("return", 6))
    mix_gains: ClassVar[dict[str, float]] = {
        "pad": 0.7, "bass": 0.28, "arp": 0.3,
                 "lead": 0.22, "drums": 0.12, "chords": 0.15}
    duck_depth = 0.0

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        start = self.pos
        root_deg = self.progression[bar % len(self.progression)]
        root = self.deg(root_deg)
        chord = self.chord_notes(root_deg, 4)

        self.add("pad", pad_chord([hz(n) for n in chord],
                                  self.beat * 4.1, 1.0, 1.3), start, 0.9)
        self.add("bass", sub_bass(hz(root - 12), self.beat * 4), start, 0.6)

        for step in range(0, 16, 4):
            if self.rng.random() < 0.55:
                note = self.rng.choice([n + 24 for n in chord]
                                       + [n + 36 for n in chord])
                self.add("arp", bell(hz(note), self.beat * 1.4),
                         start + step + self.rng.choice((0, 1, 2)), 0.4)

        if section == "deep" and bar % 2 == 0:
            self.melody("lead", start,
                        lambda f, d: airy(f, d, self.npr),
                        density=0.25, lengths=(2, 3, 4, 6), gain=0.35,
                        bar=bar, root_deg=root_deg)

        if section != "drift" and bar % 2 == 1:
            self.groove(start, kicks=(0, 8), bar=bar)


class DiscoComposer(GenreComposer):
    """Four-on-the-floor kick, octave bass and sweeping string stabs."""

    name = "disco"
    tempos = (112, 118, 124)
    scales = (MINOR, DORIAN)
    progression = (0, 3, 0, 4)
    sections = (("intro", 4), ("verse", 8), ("chorus", 8),
                ("break", 4), ("chorus2", 8), ("outro", 4))
    mix_gains: ClassVar[dict[str, float]] = {
        "chords": 0.45, "bass": 0.55, "drums": 0.55,
                 "lead": 0.22, "pad": 0.18}
    duck_depth = 0.34

    def render_bar(self, section: str, bar: int, last_bar: bool) -> None:
        start = self.pos
        root_deg = self.progression[bar % len(self.progression)]
        root = self.deg(root_deg)
        chord = self.chord_notes(root_deg, 4)

        for step in (2, 6, 10, 14):
            self.add("chords",
                     string_stab([hz(n + 12) for n in chord],
                                 self.step * 0.9), start + step, 0.5)

        for i, step in enumerate(range(0, 16, 2)):
            note = root + (12 if i % 2 else 0)
            self.add("bass", pulse_bass(hz(note), self.step * 1.3),
                     start + step, 0.85)

        if section in ("chorus", "chorus2"):
            self.add("pad", pad_chord([hz(n) for n in chord],
                                      self.beat * 4, 0.35, 0.5), start, 0.5)
            self.melody("lead", start,
                        lambda f, d: string_stab([f], d),
                        density=0.5, octaves=(24,), gain=0.35, bar=bar,
                        root_deg=root_deg)

        if last_bar and section in ("intro", "verse"):
            self.riser(start + 8, self.beat * 2, 0.24)

        self.groove(
            start,
            kicks=(0, 4, 8, 12),
            snares=(4, 12),
            claps=(4, 12),
            shakers=tuple(range(1, 16, 2)),
            hats=tuple(range(0, 16, 2)),
            open_hats=(2, 6, 10, 14),
            crash_at_start=(bar == 0 and section not in ("intro", "outro")),
            fill=last_bar and section != "outro",
            bar=bar,
        )


GENRE_COMPOSERS = {
    "synthwave": SynthwaveComposer,
    "chiptune": ChiptuneComposer,
    "funk": FunkComposer,
    "jazz": JazzComposer,
    "ambient": AmbientComposer,
    "disco": DiscoComposer,
}

# "metal" is handled by the Composer above; the rest by the classes here.
GENRES = ("metal", *GENRE_COMPOSERS)


def pick_genre(previous: str | None = None,
               rng: random.Random | None = None) -> str:
    """Pick a genre that differs from the previous one."""
    rng = rng or random
    choices = [genre for genre in GENRES if genre != previous]
    return rng.choice(choices or list(GENRES))


# --------------------------------------------------------------------------- #
# Public helpers
# --------------------------------------------------------------------------- #

def compose(seed: int | None = None, shorten: float = 1.0,
            genre: str | None = None) -> bytes:
    """Compose a fresh track and return interleaved int16 stereo at SR.

    `genre` is one of GENRES; when omitted a seed-derived genre is chosen.
    """
    if genre not in GENRE_COMPOSERS and genre != "metal":
        genre = random.Random(seed).choice(GENRES)
    if genre == "metal":
        return Composer(seed, shorten).render()
    return GENRE_COMPOSERS[genre](seed, shorten).render()


def compose_wav(seed: int | None = None, path: str = "track.wav",
                genre: str | None = None) -> str:
    """Compose a track and write it to a stereo .wav file (for previewing)."""
    import wave

    data = compose(seed, genre=genre)
    with wave.open(path, "wb") as fh:
        fh.setnchannels(2)
        fh.setsampwidth(2)
        fh.setframerate(SR)
        fh.writeframes(data)
    return path


def explosion(seed: int | None = None, duration: float = 2.2) -> bytes:
    """One-shot victory boom: sub drop, blast body, debris, long tail.

    Returns interleaved int16 stereo at SR, exactly like compose(), so the
    caller can hand it straight to pygame.mixer.Sound(buffer=...).
    """
    rng = np.random.default_rng(seed)
    n = max(1, int(duration * SR))
    t = np.arange(n, dtype=np.float32) / SR
    white = rng.normal(0.0, 1.0, n).astype(np.float32)

    # Sub-bass drop, saturated for weight.
    freq = 26.0 + 69.0 * np.exp(-t * 5.5)
    sub = np.sin(2.0 * np.pi * np.cumsum(freq) / SR)
    sub *= np.exp(-t * 1.9) * (1.0 - np.exp(-t * 900.0))
    sub = np.tanh(sub * 2.2)

    # Blast body, the opening crack, and a short low thump.
    smooth = np.ones(48, dtype=np.float32) / 48.0
    body = np.convolve(white, smooth, mode="same") * np.exp(-t * 4.2) * 2.2
    crack = np.diff(white, prepend=0.0) * np.exp(-t * 26.0) * 0.55
    impact = np.convolve(white, np.ones(5, np.float32) / 5.0, mode="same")
    impact *= np.exp(-t * 60.0) * 1.4

    # Debris: sparse cracks sprinkled through the decaying tail.
    debris = np.zeros(n, dtype=np.float32)
    for hit in rng.integers(0, n, size=90):
        length = min(n - hit, int(SR * rng.uniform(0.004, 0.02)))
        decay = np.exp(-np.arange(length) / max(SR * 0.004, 1.0))
        click = rng.normal(0.0, 1.0, length).astype(np.float32) * decay
        level = float(np.exp(-hit / SR * 2.2)) * float(rng.uniform(0.05, 0.22))
        debris[hit:hit + length] += click * level

    mono = 0.9 * sub + 0.8 * body + crack + 0.7 * impact + debris
    left = np.tanh(1.15 * (mono + 0.55 * _boom_tail(mono, 0)))
    right = np.tanh(1.15 * (mono + 0.55 * _boom_tail(mono, 211)))

    peak = max(float(np.abs(left).max()), float(np.abs(right).max())) or 1.0
    left *= 0.95 / peak
    right *= 0.95 / peak

    fade = min(n, int(0.03 * SR))
    ramp = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    left[-fade:] *= ramp
    right[-fade:] *= ramp

    pcm = np.empty(2 * n, dtype=np.int16)
    pcm[0::2] = np.clip(left * 32767.0, -32768, 32767).astype(np.int16)
    pcm[1::2] = np.clip(right * 32767.0, -32768, 32767).astype(np.int16)
    return pcm.tobytes()
