"""Sheet-music analysis: key, time signature, tempo and chords (no Qt dependency).

The local scanner only reads text embedded in a PDF (title, key and tempo
markings, chord symbols). It cannot read engraved notes; for that, hand the PDF
to an AI assistant through the JSON exchange and import its answer.
"""

import re
from dataclasses import dataclass, field

from voyager.chords import parse_chord
from voyager.metronome import MAX_BPM, MIN_BPM

MAX_BARS = 32
TEMPO_WORDS = {
    "larghissimo": 30,
    "largo": 50,
    "adagio": 66,
    "andante": 80,
    "moderato": 100,
    "allegretto": 112,
    "allegro": 128,
    "vivace": 150,
    "presto": 170,
}
_TIME_SIGNATURE = re.compile(r"(?<![\d/.])(\d{1,2})\s*/\s*(2|4|8|16)(?![\d/])")
_KEY_LABELLED = re.compile(
    r"[Kk]ey(?:\s+of|\s+signature)?\s*[:\-]?\s*([A-G][#b♯♭]?)\s*[-\s]?(major|minor|maj|min|Major|Minor)\b"
)
_KEY_IN = re.compile(r"\b[Ii]n\s+([A-G][#b♯♭]?)\s*[-\s]?(major|minor|Major|Minor)\b")
_KEY_BARE = re.compile(r"\b([A-G][#b♯♭]?)\s+(major|minor|Major|Minor)\b")
_TEMPO_MARK = re.compile(r"(?:♩|♪|[Qq]uarter\s*(?:note)?)\s*[=:]\s*(\d{2,3})")
_TEMPO_BPM = re.compile(r"(\d{2,3})\s*(?:bpm|BPM)|(?:bpm|BPM|[Tt]empo)\s*[:=]\s*(\d{2,3})")

_SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_FLAT_MAJOR_KEYS = {5, 10, 3, 8, 1, 6}  # F Bb Eb Ab Db Gb
_FLAT_MINOR_KEYS = {2, 7, 0, 5, 10, 3}  # D G C F Bb Eb
_NOTE_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass
class SheetAnalysis:
    key: str | None = None  # e.g. "G major"
    beats: int | None = None
    unit: int | None = None
    tempo: int | None = None
    progression: str = ""
    source: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def time_signature(self) -> str | None:
        return f"{self.beats}/{self.unit}" if self.beats and self.unit else None

    @property
    def found_anything(self) -> bool:
        return any([self.key, self.beats, self.tempo, self.progression])


def tonic_and_mode(key: str) -> tuple[int, bool] | None:
    """Return (pitch class, is_minor) for a key such as 'F# minor', or None."""
    match = re.fullmatch(
        r"\s*([A-Ga-g])([#b♯♭]?)\s*[-\s]?(major|minor|maj|min)\s*", key, re.IGNORECASE
    )
    if not match:
        return None
    letter, accidental, mode = match.groups()
    shift = {"#": 1, "♯": 1, "b": -1, "♭": -1, "": 0}[accidental]
    pitch = (_NOTE_BASE[letter.upper()] + shift) % 12
    return pitch, mode.lower().startswith("min")


def _normalise_key(note: str, mode: str) -> str:
    note = note.replace("♯", "#").replace("♭", "b")
    return f"{note} {'minor' if mode.lower().startswith('min') else 'major'}"


def pitch_names(tonic: int, minor: bool) -> tuple[str, ...]:
    """Note spellings (sharps or flats) that suit the given key."""
    flat_keys = _FLAT_MINOR_KEYS if minor else _FLAT_MAJOR_KEYS
    return _FLAT_NAMES if tonic in flat_keys else _SHARP_NAMES


def suggest_progression(key: str, bars: int = 8) -> str:
    """A simple, singable progression in the given key (I-IV-V, or i-iv-V in minor)."""
    parsed = tonic_and_mode(key)
    if parsed is None:
        raise ValueError(f"Unrecognised key: {key!r}")
    tonic, minor = parsed
    names = pitch_names(tonic, minor)

    def chord(semitones: int, quality: str = "") -> str:
        return names[(tonic + semitones) % 12] + quality

    one = chord(0, "m" if minor else "")
    four = chord(5, "m" if minor else "")
    five = chord(7)  # a major V, as in the Am | E of the first milestone
    pattern = [one, one, four, five, one, four, five, one]
    return " | ".join((pattern * (bars // len(pattern) + 1))[:bars])


def find_chord_symbols(text: str) -> list[str]:
    """Chords from lines made up only of chord symbols (and bar lines)."""
    chords: list[str] = []
    for line in text.splitlines():
        tokens = [token for token in re.split(r"[\s|]+", line.strip()) if token]
        if len(tokens) >= 2 and all(parse_chord(token) for token in tokens):
            chords.extend(tokens)
    return chords[:MAX_BARS]


def analyze_text(text: str) -> SheetAnalysis:
    """Find what a PDF's embedded text says about key, metre, tempo and chords."""
    result = SheetAnalysis()

    for pattern in (_KEY_LABELLED, _KEY_IN, _KEY_BARE):
        match = pattern.search(text)
        if match:
            result.key = _normalise_key(*match.groups())
            break

    for match in _TIME_SIGNATURE.finditer(text):
        beats, unit = int(match.group(1)), int(match.group(2))
        if 1 <= beats <= 16:
            result.beats, result.unit = beats, unit
            break

    match = _TEMPO_MARK.search(text) or _TEMPO_BPM.search(text)
    if match:
        value = int(next(group for group in match.groups() if group))
        if MIN_BPM <= value <= MAX_BPM:
            result.tempo = value
    if result.tempo is None:
        lowered = text.lower()
        for word, bpm in TEMPO_WORDS.items():
            if re.search(rf"\b{word}\b", lowered):
                result.tempo = bpm
                result.notes.append(f"Tempo estimated from the word '{word}'.")
                break

    chords = find_chord_symbols(text)
    if chords:
        result.progression = " | ".join(chords)
        result.source = "chord symbols printed in the PDF"
    elif result.key:
        result.progression = suggest_progression(result.key)
        result.source = f"suggested from the key of {result.key}"
        result.notes.append(
            "No chord symbols found; this is a simple I-IV-V suggestion, not a "
            "harmonic analysis of the melody."
        )
    if not result.found_anything:
        result.notes.append(
            "No readable text found. Scanned or engraved scores need the AI hand-off."
        )
    return result


def parse_settings(text: str) -> tuple[int | None, tuple[int, int] | None]:
    """Read saved 'Tempo: 72 BPM' and 'Time signature: 3/4' lines back from an entry."""
    tempo = None
    signature = None
    for line in text.splitlines():
        lowered = line.lower()
        if lowered.startswith("tempo"):
            match = re.search(r"(\d{2,3})", line)
            if match and MIN_BPM <= int(match.group(1)) <= MAX_BPM:
                tempo = int(match.group(1))
        elif lowered.startswith("time signature"):
            match = _TIME_SIGNATURE.search(line)
            if match and 1 <= int(match.group(1)) <= 16:
                signature = (int(match.group(1)), int(match.group(2)))
    return tempo, signature


def format_for_entry(pdf_name: str, analysis: SheetAnalysis) -> str:
    """Text block saved into an entry once the learner accepts an analysis."""
    lines = [f"Sheet music: {pdf_name}"]
    if analysis.key:
        lines.append(f"Key: {analysis.key}")
    if analysis.time_signature:
        lines.append(f"Time signature: {analysis.time_signature}")
    if analysis.tempo:
        lines.append(f"Tempo: {analysis.tempo} BPM")
    if analysis.progression:
        lines.append(f"Chord progression: {analysis.progression}")
    return "\n".join(lines)
