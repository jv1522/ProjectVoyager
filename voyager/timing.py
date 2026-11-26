"""Beat/second conversion shared by the MIDI and MusicXML readers (no Qt dependency)."""

from bisect import bisect_right
from dataclasses import dataclass

DEFAULT_BPM = 120.0


@dataclass(frozen=True)
class TimedNote:
    """A note positioned in quarter-note beats."""

    start: float
    duration: float
    pitch: int  # MIDI note number
    velocity: int = 80


class TempoMap:
    """Piecewise-constant tempo, with positions measured in quarter-note beats."""

    def __init__(self, changes: list[tuple[float, float]] | None = None):
        merged: dict[float, float] = {}
        for beat, bpm in sorted(changes or []):
            if bpm > 0:
                merged[max(0.0, beat)] = bpm
        if 0.0 not in merged:
            first = next(iter(merged.values()), DEFAULT_BPM)
            merged = {0.0: first, **merged}
        self._beats = sorted(merged)
        self._bpms = [merged[beat] for beat in self._beats]
        self._seconds = [0.0]
        for index in range(1, len(self._beats)):
            span = self._beats[index] - self._beats[index - 1]
            self._seconds.append(self._seconds[-1] + span * 60.0 / self._bpms[index - 1])

    @property
    def initial_bpm(self) -> float:
        return self._bpms[0]

    def scaled(self, factor: float) -> "TempoMap":
        """The same tempo changes, all faster (factor > 1) or slower (factor < 1)."""
        return TempoMap([(beat, bpm * factor) for beat, bpm in zip(self._beats, self._bpms)])

    def seconds_at(self, beat: float) -> float:
        beat = max(0.0, beat)
        index = bisect_right(self._beats, beat) - 1
        return self._seconds[index] + (beat - self._beats[index]) * 60.0 / self._bpms[index]

    def beat_at(self, seconds: float) -> float:
        seconds = max(0.0, seconds)
        index = bisect_right(self._seconds, seconds) - 1
        return self._beats[index] + (seconds - self._seconds[index]) * self._bpms[index] / 60.0
