"""Renders a score to a WAV file.

Notes are played from bundled solo-violin recordings (VSCO 2 CE, CC0; see
voyager/data/violin/README.md), pitch-shifted from the nearest recorded note with the
sustain looped for long notes. If the recordings are missing, a synthesized violin-like
tone is used instead.
"""

import array
import math
import wave
from pathlib import Path

from voyager.metronome import write_samples
from voyager.timing import TempoMap, TimedNote

RATE = 22050
SAMPLE_DIR = Path(__file__).parent / "data" / "violin"
_NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
LOOP_START, LOOP_END, CROSSFADE = 1.0, 3.6, 0.25  # seconds within each recording
RELEASE = 0.18
MAX_SECONDS = 240.0
# Violin body resonances: (centre Hz, width Hz, gain). They shape a bowed-string spectrum.
FORMANTS = ((290, 80, 1.2), (450, 90, 1.0), (1000, 300, 0.9), (2400, 700, 1.1), (3500, 900, 0.7))
MAX_HARMONICS = 24


def _body_gain(freq: float) -> float:
    return 0.25 + sum(g * math.exp(-(((freq - c) / w) ** 2)) for c, w, g in FORMANTS)


class _Recording:
    def __init__(self, root: int, data: list[float]):
        self.root = root
        self.data = data
        self.loop_start = int(LOOP_START * RATE)
        self.loop_end = min(int(LOOP_END * RATE), len(data) - 1)
        self.crossfade = min(int(CROSSFADE * RATE), self.loop_start)


_recordings: list[_Recording] | None = None


def _load_recordings() -> list[_Recording]:
    global _recordings
    if _recordings is None:
        found = []
        for path in sorted(SAMPLE_DIR.glob("*.wav")):
            name = path.stem
            if len(name) < 2 or name[0] not in _NOTE_BASE or not name[1:].isdigit():
                continue
            try:
                with wave.open(str(path)) as wav:
                    if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() != RATE:
                        continue
                    pcm = array.array("h")
                    pcm.frombytes(wav.readframes(wav.getnframes()))
            except (wave.Error, OSError):
                continue
            sustain = pcm[int(LOOP_START * RATE) : int(LOOP_END * RATE)] or pcm
            level = math.sqrt(sum(v * v for v in sustain) / len(sustain)) or 1.0
            gain = 3000.0 / level  # even loudness across the keyboard
            root = 12 * (int(name[1:]) + 1) + _NOTE_BASE[name[0]]
            found.append(_Recording(root, [v * gain / 32768 for v in pcm]))
        _recordings = found
    return _recordings


def _sampled_tone(pitch: int, seconds: float) -> list[float] | None:
    recordings = _load_recordings()
    if not recordings:
        return None
    rec = min(recordings, key=lambda r: abs(r.root - pitch))
    step = 2 ** ((pitch - rec.root) / 12)
    count = int((seconds + RELEASE) * RATE)
    hold = int(seconds * RATE)
    data, loop_start, loop_end = rec.data, rec.loop_start, rec.loop_end
    span = loop_end - loop_start
    fade_len = rec.crossfade
    last = len(data) - 2

    def sample(position: float) -> float:
        index = int(position)
        if index >= last:
            return 0.0
        frac = position - index
        return data[index] * (1 - frac) + data[index + 1] * frac

    out = []
    for i in range(count):
        position = i * step
        if position >= loop_end:
            position = loop_start + (position - loop_start) % span
        value = sample(position)
        if position > loop_end - fade_len:
            weight = (position - (loop_end - fade_len)) / fade_len
            value = value * (1 - weight) + sample(position - span) * weight
        if i >= hold:
            value *= max(0.0, 1.0 - (i - hold) / (count - hold)) ** 2
        elif i < 200:
            value *= i / 200  # avoid a click at the start
        out.append(value)
    return out


def _tone(pitch: int, seconds: float) -> list[float]:
    """A bowed note: sawtooth-like harmonics through body resonances, delayed vibrato, bow noise."""
    freq = 440.0 * 2 ** ((pitch - 69) / 12)
    release = 0.18
    count = int((seconds + release) * RATE)
    attack = int(min(0.09, seconds * 0.4) * RATE) or 1
    hold = int(seconds * RATE)
    harmonics = [
        (n, _body_gain(n * freq) / n ** 0.9)
        for n in range(1, MAX_HARMONICS + 1)
        if n * freq < RATE * 0.45
    ]
    rate, depth = 5.6, 0.0065
    noise_state = pitch * 7919 + 1
    out = []
    for i in range(count):
        t = i / RATE
        if i < attack:
            env = (i / attack) ** 1.5
        elif i < hold:
            env = 1.0 - 0.08 * (i - attack) / max(1, hold - attack)
        else:
            env = 0.92 * max(0.0, 1.0 - (i - hold) / (count - hold)) ** 2
        # Vibrato fades in after the bow settles; phase is the integral of the frequency.
        fade = min(1.0, max(0.0, (t - 0.18) / 0.35))
        phase = 2 * math.pi * freq * (t - fade * depth * math.cos(2 * math.pi * rate * t) / (2 * math.pi * rate))
        value = sum(amp * math.sin(n * phase) for n, amp in harmonics)
        noise_state = (noise_state * 1103515245 + 12345) & 0x7FFFFFFF
        noise = noise_state / 0x3FFFFFFF - 1.0
        bow = 0.35 * math.exp(-t * 14) + 0.03  # scratchy onset, then a faint bow hiss
        out.append(env * (value + bow * noise * 0.6))
    return out


def _reverb(mix: list[float]) -> list[float]:
    """A light room: a few decaying echoes so notes blend like a recorded violin."""
    for delay, gain in ((int(0.037 * RATE), 0.22), (int(0.071 * RATE), 0.16), (int(0.113 * RATE), 0.1)):
        for i in range(len(mix) - 1, delay - 1, -1):
            mix[i] += mix[i - delay] * gain
    return mix


def _click(accent: bool) -> list[float]:
    """A short wood-like tick for the count-in; the first beat is higher and louder."""
    freq = 1500.0 if accent else 1000.0
    count = int(0.07 * RATE)
    return [
        math.exp(-i / (0.012 * RATE)) * math.sin(2 * math.pi * freq * i / RATE) * (0.55 if accent else 0.4)
        for i in range(count)
    ]


def render_score(
    notes: list[TimedNote],
    tempo_map: TempoMap,
    count_in_beats: int = 0,
    beat_seconds: float = 0.5,
) -> list[float]:
    """Mix notes into one sample buffer, after an optional count-in of clicks.

    Notes starting after MAX_SECONDS are dropped.
    """
    lead = count_in_beats * beat_seconds
    cache: dict[tuple[int, int], list[float]] = {}
    events = []
    for note in notes:
        start = tempo_map.seconds_at(note.start)
        if start >= MAX_SECONDS:
            continue
        length = max(0.05, tempo_map.seconds_at(note.start + note.duration) - start)
        length = min(length, MAX_SECONDS - start)
        events.append((start + lead, length, note))
    if not events:
        return []
    total = int(max(s + l for s, l, _ in events) * RATE) + int(0.2 * RATE)
    mix = [0.0] * total
    for beat in range(count_in_beats):
        offset = int(beat * beat_seconds * RATE)
        for i, value in enumerate(_click(beat == 0)):
            mix[offset + i] += value
    for start, length, note in events:
        key = (note.pitch, round(length * 20))  # 50 ms duration buckets
        tone = cache.get(key)
        if tone is None:
            seconds = key[1] / 20 or 0.05
            tone = _sampled_tone(note.pitch, seconds) or _tone(note.pitch, seconds)
            cache[key] = tone
        gain = note.velocity / 127 * 0.8
        offset = int(start * RATE)
        for i, value in enumerate(tone):
            if offset + i >= total:
                break
            mix[offset + i] += value * gain
    return _reverb(mix)


def write_score_audio(
    notes: list[TimedNote],
    tempo_map: TempoMap,
    path: Path,
    count_in_beats: int = 0,
    beat_seconds: float = 0.5,
) -> bool:
    """Write the rendered score to path; False when there is nothing to play."""
    samples = render_score(notes, tempo_map, count_in_beats, beat_seconds)
    if not samples:
        return False
    write_samples(path, samples, RATE)
    return True
