"""Metronome logic and synthesized chime, jingle and shaker sounds (no Qt dependency)."""

import math
import random
import struct
import wave
from pathlib import Path

MIN_BPM = 20
MAX_BPM = 240
DEFAULT_PROGRESSION = "Am | Am | E | E | Am | E | E | Am"
SAMPLE_RATE = 44100


def parse_progression(text: str) -> list[str]:
    """Split a progression such as 'Am | Am | E' into one chord per bar."""
    return [bar.strip() for bar in text.replace("\n", "|").split("|") if bar.strip()]


def find_progression(text: str) -> str | None:
    """Return the first line containing a bar-separated chord progression."""
    for line in text.splitlines():
        candidate = line.split(":", 1)[1] if ":" in line else line
        if candidate.count("|") >= 1 and len(parse_progression(candidate)) >= 2:
            return candidate.strip()
    return None


def interval_ms(bpm: int) -> float:
    if not MIN_BPM <= bpm <= MAX_BPM:
        raise ValueError(f"BPM must be between {MIN_BPM} and {MAX_BPM}")
    return 60000.0 / bpm


def beat_position(tick: int, beats_per_bar: int, bar_count: int) -> tuple[int, int]:
    """Map a running beat counter to (bar index, beat index within the bar)."""
    if beats_per_bar < 1 or bar_count < 1:
        raise ValueError("Beats per bar and bar count must be positive")
    return (tick // beats_per_bar) % bar_count, tick % beats_per_bar


# Pellet strikes (offset seconds, level) that give a jingle bell its rattle.
_PELLETS = ((0.0, 1.0), (0.011, 0.7), (0.025, 0.55), (0.039, 0.4), (0.056, 0.3))
# Inharmonic partials typical of small spherical bells: (ratio, level, decay/s).
_JINGLE_PARTIALS = ((1.0, 1.0, 9.0), (2.32, 0.7, 12.0), (3.87, 0.5, 15.0), (5.41, 0.3, 20.0))


def write_jingle(path: Path, fundamental: float, duration: float = 0.9) -> None:
    """Synthesize a jingle bell: bright metallic partials, a pellet rattle and a shimmering tail."""
    count = int(SAMPLE_RATE * duration)
    samples = [0.0] * count
    for offset, level in _PELLETS:
        begin = int(offset * SAMPLE_RATE)
        for ratio, amplitude, decay in _JINGLE_PARTIALS:
            # Each pellet strikes slightly detuned, so the strikes beat against each other.
            frequency = fundamental * ratio * (1 + 0.004 * offset * 100)
            for n in range(begin, min(count, begin + int(SAMPLE_RATE * 0.35))):
                t = (n - begin) / SAMPLE_RATE
                samples[n] += level * amplitude * math.exp(-decay * t) * math.sin(
                    2 * math.pi * frequency * t
                )
    # Longer, softer ring with a fast tremolo for the shimmer.
    for ratio, amplitude, decay in _JINGLE_PARTIALS[:2]:
        for n in range(count):
            t = n / SAMPLE_RATE
            shimmer = 0.75 + 0.25 * math.sin(2 * math.pi * 38 * t)
            samples[n] += 0.25 * amplitude * shimmer * math.exp(-decay * 0.3 * t) * math.sin(
                2 * math.pi * fundamental * ratio * t
            )
    peak = max(abs(v) for v in samples) or 1.0
    attack = int(SAMPLE_RATE * 0.001)
    frames = bytearray()
    for n, value in enumerate(samples):
        value = value / peak * 0.8
        if n < attack:
            value *= n / attack
        frames += struct.pack("<h", int(value * 32767))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))


CHIME_RATE = 22050
# Music-box style tine: (frequency ratio, level, decay per second).
_CHIME_PARTIALS = ((1.0, 1.0, 2.8), (2.0, 0.35, 4.5), (4.0, 0.2, 7.0), (5.95, 0.1, 10.0))

# Pitched timbres, each a tuple of (frequency ratio, level, decay per second).
TIMBRES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "chime": _CHIME_PARTIALS,
    # Wooden bar: strong 4x and ~10x overtones, short ring.
    "marimba": ((1.0, 1.0, 5.0), (3.9, 0.45, 12.0), (9.8, 0.12, 25.0)),
    # Thumb piano: soft fundamental plus a bright metallic partial.
    "kalimba": ((1.0, 1.0, 4.0), (5.4, 0.3, 11.0), (8.9, 0.08, 18.0)),
    # Metal bar with a long, inharmonic ring.
    "vibraphone": ((1.0, 1.0, 1.4), (4.0, 0.3, 2.5), (10.0, 0.08, 5.0)),
    # Harmonic series with upper partials fading faster, like a nylon string.
    "nylon": tuple((float(h), 1.0 / h**1.2, 2.5 + 1.8 * h) for h in range(1, 8)),
    # Struck steel-string brightness.
    "steel": tuple((float(h), 1.0 / h, 2.0 + 1.2 * h) for h in range(1, 10)),
}
# Unpitched accents: (accent frequency, normal frequency, partials).
PERCUSSION: dict[str, tuple[float, float, tuple[tuple[float, float, float], ...]]] = {
    "woodblock": (1250.0, 950.0, ((1.0, 1.0, 55.0), (2.3, 0.5, 80.0), (3.6, 0.2, 110.0))),
    "cowbell": (820.0, 620.0, ((1.0, 1.0, 14.0), (1.5, 0.8, 18.0), (2.77, 0.4, 28.0))),
    "claves": (2500.0, 2000.0, ((1.0, 1.0, 70.0), (2.7, 0.3, 120.0))),
    "triangle": (3400.0, 2800.0, ((1.0, 1.0, 3.5), (2.76, 0.6, 5.0), (5.4, 0.4, 8.0), (8.9, 0.2, 12.0))),
}


def _write_wav(path: Path, samples: list[float], rate: int, peak_level: float = 0.8) -> None:
    peak = max((abs(v) for v in samples), default=0.0) or 1.0
    frames = b"".join(struct.pack("<h", int(v / peak * peak_level * 32767)) for v in samples)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)


Layer = tuple[
    list[tuple[float, float, float]], tuple[tuple[float, float, float], ...]
]


def write_layers(
    path: Path, layers: list[Layer], duration: float, rate: int = CHIME_RATE
) -> None:
    """Mix several instruments into one file.

    Each layer is (notes, partials); notes are (frequency, start_s, level).
    """
    count = int(rate * duration)
    samples = [0.0] * count
    attack = int(rate * 0.002)
    for notes, partials in layers:
        for frequency, start, level in notes:
            begin = int(start * rate)
            for ratio, amplitude, decay in partials:
                if frequency * ratio >= rate / 2:
                    continue
                step = 2 * math.pi * frequency * ratio / rate
                rate_decay = decay / rate
                for n in range(begin, count):
                    k = n - begin
                    gain = level * amplitude * math.exp(-rate_decay * k)
                    if k < attack:
                        gain *= k / attack
                    samples[n] += gain * math.sin(step * k)
    _write_wav(path, samples, rate)


def write_samples(path: Path, samples: list[float], rate: int, peak_level: float = 0.8) -> None:
    """Write mono samples to a 16-bit WAV file, normalised to the given peak level."""
    _write_wav(path, samples, rate, peak_level)


def write_chime_notes(
    path: Path,
    notes: list[tuple[float, float, float]],
    duration: float,
    rate: int = CHIME_RATE,
    partials: tuple[tuple[float, float, float], ...] | None = None,
) -> None:
    """Mix several tones of one instrument; notes are (frequency, start_s, level)."""
    write_layers(path, [(notes, partials or _CHIME_PARTIALS)], duration, rate)


def write_shaker(path: Path, duration: float = 0.12, rate: int = CHIME_RATE) -> None:
    """Short, bright noise burst used for off-beat subdivisions."""
    generator = random.Random(7)
    previous = 0.0
    samples = []
    for n in range(int(rate * duration)):
        noise = generator.uniform(-1.0, 1.0)
        samples.append((noise - previous) * math.exp(-55.0 * n / rate))
        previous = noise
    _write_wav(path, samples, rate, peak_level=0.5)
