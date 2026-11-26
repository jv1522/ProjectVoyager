"""MusicXML reader: notes, key, metre, tempo, and chords derived from the notes.

Reads the first part of a score-partwise file (plain .musicxml/.xml or compressed
.mxl). Repeats and ornaments are ignored; the piece is played straight through.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

from voyager.chords import parse_chord
from voyager.metronome import MAX_BPM, MIN_BPM
from voyager.sheet_music import SheetAnalysis, pitch_names
from voyager.timing import TempoMap, TimedNote

MAX_BARS = 32
STEP_BASE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
STEP_INDEX = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
BEAT_UNIT_QUARTERS = {"whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5, "16th": 0.25}
SHARP_ORDER = "FCGDAEB"
FLAT_ORDER = "BEADGCF"


@dataclass(frozen=True)
class ScoreNote:
    start: float  # quarter-note beats from the beginning
    duration: float
    pitch: int  # MIDI note number
    step: str
    octave: int
    alter: int
    measure: int
    articulation: str = "sustain"

    @property
    def diatonic(self) -> int:
        """Staff position counted in diatonic steps (C0 = 0, E4 = 30)."""
        return self.octave * 7 + STEP_INDEX[self.step]


@dataclass(frozen=True)
class Measure:
    index: int
    start: float
    length: float


@dataclass
class Score:
    title: str = ""
    notes: list[ScoreNote] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    fifths: int = 0
    minor: bool = False
    beats: int = 4
    unit: int = 4
    tempo_map: TempoMap = field(default_factory=TempoMap)
    has_tempo: bool = False

    @property
    def total_beats(self) -> float:
        return sum(measure.length for measure in self.measures)

    @property
    def tonic(self) -> int:
        return (self.fifths * 7 + (9 if self.minor else 0)) % 12

    @property
    def key_name(self) -> str:
        return f"{pitch_names(self.tonic, self.minor)[self.tonic]} {'minor' if self.minor else 'major'}"

    def key_alterations(self) -> dict[str, int]:
        """Sharps or flats implied by the key signature, by note letter."""
        if self.fifths >= 0:
            return {letter: 1 for letter in SHARP_ORDER[: self.fifths]}
        return {letter: -1 for letter in FLAT_ORDER[: -self.fifths]}

    def timed_notes(self) -> list[TimedNote]:
        return [TimedNote(n.start, n.duration, n.pitch, articulation=n.articulation) for n in self.notes]


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _name(child) == name), None)


def _text(element: ET.Element, name: str) -> str | None:
    child = _child(element, name)
    return child.text.strip() if child is not None and child.text else None


def _read_tempo(direction: ET.Element, position: float) -> tuple[float, float] | None:
    for element in direction.iter():
        if _name(element) == "sound" and element.get("tempo"):
            try:
                return position, float(element.get("tempo"))
            except ValueError:
                pass
    for metronome in direction.iter():
        if _name(metronome) != "metronome":
            continue
        unit = _text(metronome, "beat-unit")
        per_minute = _text(metronome, "per-minute")
        if unit in BEAT_UNIT_QUARTERS and per_minute:
            try:
                factor = BEAT_UNIT_QUARTERS[unit] * (1.5 if _child(metronome, "beat-unit-dot") is not None else 1.0)
                return position, float(per_minute) * factor
            except ValueError:
                pass
    return None


def parse_musicxml(data: bytes) -> Score:
    if b"<!ENTITY" in data:
        raise ValueError("MusicXML files with entity declarations are not supported")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"Not valid MusicXML: {error}") from error
    if _name(root) == "score-timewise":
        raise ValueError("Time-wise MusicXML is not supported; export a part-wise file")
    if _name(root) != "score-partwise":
        raise ValueError("This file is not a MusicXML score")
    parts = [child for child in root if _name(child) == "part"]
    if not parts:
        raise ValueError("The MusicXML file contains no parts")

    score = Score()
    for container, tag in (("work", "work-title"), (None, "movement-title")):
        holder = _child(root, container) if container else root
        title = _text(holder, tag) if holder is not None else None
        if title:
            score.title = title
            break

    divisions = 1
    key_seen = time_seen = False
    tempos: list[tuple[float, float]] = []
    open_ties: dict[int, int] = {}
    measure_start = 0.0

    for measure_index, measure in enumerate(c for c in parts[0] if _name(c) == "measure"):
        cursor = longest = last_start = 0.0
        for element in measure:
            name = _name(element)
            if name == "attributes":
                for attribute in element:
                    kind = _name(attribute)
                    if kind == "divisions" and attribute.text:
                        divisions = max(1, int(float(attribute.text)))
                    elif kind == "key" and not key_seen:
                        fifths = _text(attribute, "fifths")
                        if fifths is not None:
                            score.fifths = int(fifths)
                            score.minor = (_text(attribute, "mode") or "major").lower() == "minor"
                            key_seen = True
                    elif kind == "time" and not time_seen:
                        beats = re.match(r"\d+", _text(attribute, "beats") or "")
                        unit = _text(attribute, "beat-type")
                        if beats and unit and unit.isdigit():
                            score.beats, score.unit = int(beats.group()), int(unit)
                            time_seen = True
            elif name in ("direction", "sound"):
                found = _read_tempo(element, measure_start + cursor)
                if found:
                    tempos.append(found)
            elif name in ("backup", "forward"):
                amount = float(_text(element, "duration") or 0) / divisions
                cursor += -amount if name == "backup" else amount
            elif name == "note":
                if _child(element, "grace") is not None:
                    continue
                duration = float(_text(element, "duration") or 0) / divisions
                is_chord = _child(element, "chord") is not None
                start = last_start if is_chord else cursor
                pitch = _child(element, "pitch")
                if pitch is not None and _child(element, "rest") is None:
                    step = _text(pitch, "step") or "C"
                    octave = int(_text(pitch, "octave") or 4)
                    alter = int(round(float(_text(pitch, "alter") or 0)))
                    midi = 12 * (octave + 1) + STEP_BASE[step] + alter
                    ties = {t.get("type") for t in element if _name(t) == "tie"}
                    if "stop" in ties and midi in open_ties:
                        index = open_ties[midi]
                        previous = score.notes[index]
                        score.notes[index] = replace(
                            previous, duration=start + duration - previous.start
                        )
                        if "start" not in ties:
                            del open_ties[midi]
                    else:
                        short_bow = any(
                            _name(mark) in ("staccato", "staccatissimo", "spiccato")
                            for notations in element if _name(notations) == "notations"
                            for articulations in notations if _name(articulations) == "articulations"
                            for mark in articulations
                        )
                        score.notes.append(
                            ScoreNote(
                                measure_start + start, duration, midi, step, octave, alter,
                                measure_index, "spiccato" if short_bow else "sustain",
                            )
                        )
                        if "start" in ties:
                            open_ties[midi] = len(score.notes) - 1
                if not is_chord:
                    last_start = cursor
                    cursor += duration
            longest = max(longest, cursor)
        length = longest or score.beats * 4.0 / score.unit
        score.measures.append(Measure(measure_index, measure_start, length))
        measure_start += length

    if not score.notes:
        raise ValueError("The score contains no notes")
    score.has_tempo = bool(tempos)
    score.tempo_map = TempoMap(tempos)
    return score


def load_musicxml(path: str | Path) -> Score:
    path = Path(path)
    data = path.read_bytes()
    if path.suffix.lower() == ".mxl" or data[:2] == b"PK":
        try:
            with zipfile.ZipFile(path) as archive:
                container = archive.read("META-INF/container.xml")
                rootfile = ET.fromstring(container).find(".//{*}rootfile")
                data = archive.read(rootfile.get("full-path"))
        except (zipfile.BadZipFile, KeyError, AttributeError, ET.ParseError) as error:
            raise ValueError("The compressed MusicXML file could not be read") from error
    return parse_musicxml(data)


# --- chord derivation -------------------------------------------------------

_MAJOR_DIATONIC = {(0, False), (2, True), (4, True), (5, False), (7, False), (9, True)}
_MINOR_DIATONIC = {(0, True), (5, True), (7, False), (7, True), (3, False), (8, False), (10, False)}


def _best_chord(weights: list[float], tonic: int, minor: bool, names, first_or_last: bool) -> str:
    total = sum(weights)
    diatonic = _MINOR_DIATONIC if minor else _MAJOR_DIATONIC
    best_name, best_score = "", float("-inf")
    for root in range(12):
        for is_minor in (False, True):
            tones = {(root + i) % 12 for i in ((0, 3, 7) if is_minor else (0, 4, 7))}
            inside = sum(weights[pc] for pc in tones)
            score = inside - 0.4 * (total - inside)
            offset = (root - tonic) % 12
            if (offset, is_minor) in diatonic:
                score += 0.3 * total
            if offset in (0, 5, 7) and (offset, is_minor) in diatonic:
                score += 0.05 * total  # favour I, IV and V on ties
            if offset == 0 and is_minor == minor:
                score += (0.3 if first_or_last else 0.1) * total
            if score > best_score:
                best_name, best_score = names[root] + ("m" if is_minor else ""), score
    return best_name


def derive_chords(
    score: Score, *, include_pickup: bool = False, max_bars: int | None = MAX_BARS
) -> list[str]:
    """One simple triad per bar, chosen from the notes that sound in it."""
    names = pitch_names(score.tonic, score.minor)
    nominal = score.beats * 4.0 / score.unit
    measures = list(score.measures)
    if not include_pickup and len(measures) > 1 and measures[0].length < nominal * 0.75:
        measures = measures[1:]  # skip a pickup bar
    if max_bars is not None:
        measures = measures[:max_bars]
    tonic_chord = names[score.tonic] + ("m" if score.minor else "")
    chords: list[str] = []
    for position, measure in enumerate(measures):
        weights = [0.0] * 12
        end = measure.start + measure.length
        for note in score.notes:
            overlap = min(end, note.start + note.duration) - max(measure.start, note.start)
            if overlap > 0:
                on_beat = abs((note.start - measure.start) % 1.0) < 1e-6
                weights[note.pitch % 12] += overlap * (1.5 if on_beat else 1.0)
        if sum(weights) == 0:
            chords.append(chords[-1] if chords else tonic_chord)
        else:
            edge = position in (0, len(measures) - 1)
            chords.append(_best_chord(weights, score.tonic, score.minor, names, edge))
    return chords


def analyze_score(score: Score) -> SheetAnalysis:
    """Key, metre, tempo and per-bar chords, ready for the learner to review."""
    chords = derive_chords(score)
    analysis = SheetAnalysis(
        key=score.key_name,
        beats=score.beats,
        unit=score.unit,
        progression=" | ".join(chords),
        source="the notes in the MusicXML file",
    )
    if score.has_tempo:
        # The metronome clicks once per beat of the time-signature unit, not per quarter note.
        clicks = score.tempo_map.initial_bpm * score.unit / 4.0
        analysis.tempo = int(round(min(max(clicks, MIN_BPM), MAX_BPM)))
        if score.unit != 4:
            analysis.notes.append(f"Tempo converted to beats of 1/{score.unit}.")
    analysis.notes.append("Chords are simple triads chosen from each bar's notes.")
    if len(score.measures) > MAX_BARS:
        analysis.notes.append(f"Only the first {MAX_BARS} bars are included.")
    assert all(parse_chord(chord) for chord in chords)
    return analysis
