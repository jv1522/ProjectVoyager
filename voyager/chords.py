"""Chord parsing and guitar-friendly voicings (no Qt dependency)."""

import re
from dataclasses import dataclass

_NOTES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_QUALITIES = {
    "": (0, 4, 7),
    "m": (0, 3, 7),
    "min": (0, 3, 7),
    "-": (0, 3, 7),
    "7": (0, 4, 7, 10),
    "m7": (0, 3, 7, 10),
    "min7": (0, 3, 7, 10),
    "maj7": (0, 4, 7, 11),
    "M7": (0, 4, 7, 11),
    "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9),
    "sus2": (0, 2, 7),
    "sus4": (0, 5, 7),
    "dim": (0, 3, 6),
    "aug": (0, 4, 8),
    "5": (0, 7),
    "add9": (0, 4, 7, 14),
}
_PATTERN = re.compile(r"^([A-G])([#b]?)([^/]*?)(?:/([A-G])([#b]?))?$")


@dataclass(frozen=True)
class Chord:
    name: str
    root: int
    bass: int
    intervals: tuple[int, ...]


def _pitch_class(letter: str, accidental: str) -> int:
    return (_NOTES[letter] + {"#": 1, "b": -1, "": 0}[accidental]) % 12


def parse_chord(name: str) -> Chord | None:
    """Parse names like Am, E, F#m7, Bb, Cmaj7, Dsus4 or A/C#; None if unrecognised."""
    match = _PATTERN.match(name.strip())
    if not match:
        return None
    letter, accidental, quality, bass_letter, bass_accidental = match.groups()
    if quality not in _QUALITIES:
        return None
    root = _pitch_class(letter, accidental)
    bass = _pitch_class(bass_letter, bass_accidental) if bass_letter else root
    return Chord(name.strip(), root, bass, _QUALITIES[quality])


def midi_to_frequency(note: int) -> float:
    return 440.0 * 2 ** ((note - 69) / 12)


def bass_note(chord: Chord) -> int:
    """Bass register note between E2 and D#3, the low range of a guitar."""
    return 40 + (chord.bass - 4) % 12


def chord_tones(chord: Chord) -> list[int]:
    """Chord tones in ascending order, starting one octave above the bass root."""
    base = 40 + (chord.root - 4) % 12 + 12
    return [base + interval for interval in chord.intervals]


def arpeggio_notes(chord: Chord) -> list[int]:
    """Chord tones an octave higher, for bright, bell-like arpeggio notes."""
    return [note + 12 for note in chord_tones(chord)]


def strum_notes(chord: Chord) -> list[int]:
    return [bass_note(chord)] + chord_tones(chord)
