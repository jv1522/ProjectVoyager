"""Standard MIDI file reader: notes and tempo changes (no Qt dependency)."""

import struct
from dataclasses import dataclass

from voyager.timing import TempoMap, TimedNote

DRUM_CHANNEL = 9


@dataclass
class MidiData:
    notes: list[TimedNote]
    tempo_map: TempoMap


def _read_variable_length(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    while True:
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position


def parse_midi(data: bytes) -> MidiData:
    try:
        return _parse(data)
    except (IndexError, struct.error) as error:
        raise ValueError("The MIDI file is truncated or corrupt") from error


def _parse(data: bytes) -> MidiData:
    if data[:4] != b"MThd":
        raise ValueError("Not a MIDI file")
    header_length = struct.unpack(">I", data[4:8])[0]
    _format, _tracks, division = struct.unpack(">HHH", data[8:14])
    if division & 0x8000:
        raise ValueError("SMPTE-timed MIDI files are not supported")
    if division == 0:
        raise ValueError("The MIDI file has an invalid time division")

    notes: list[tuple[int, int, int, int]] = []  # start tick, end tick, pitch, velocity
    tempos: list[tuple[float, float]] = []
    position = 8 + header_length
    track_number = 0
    while position + 8 <= len(data):
        chunk_id = data[position : position + 4]
        length = struct.unpack(">I", data[position + 4 : position + 8])[0]
        body_start = position + 8
        position = body_start + length
        if chunk_id != b"MTrk":
            continue
        track_number += 1
        _read_track(data, body_start, min(position, len(data)), track_number, notes, tempos, division)

    notes.sort()
    timed = [
        TimedNote(start / division, max(end - start, 1) / division, pitch, velocity)
        for start, end, pitch, velocity in notes
    ]
    return MidiData(timed, TempoMap(tempos))


def _read_track(data, position, end, track, notes, tempos, division) -> None:
    tick = 0
    status = None
    open_notes: dict[tuple[int, int, int], list[tuple[int, int]]] = {}
    while position < end:
        delta, position = _read_variable_length(data, position)
        tick += delta
        byte = data[position]
        if byte == 0xFF:  # meta event
            kind = data[position + 1]
            length, body = _read_variable_length(data, position + 2)
            if kind == 0x51 and length == 3:
                microseconds = int.from_bytes(data[body : body + 3], "big")
                if microseconds:
                    tempos.append((tick / division, 60_000_000 / microseconds))
            position = body + length
            if kind == 0x2F:
                break
            continue
        if byte in (0xF0, 0xF7):  # system exclusive
            length, body = _read_variable_length(data, position + 1)
            position = body + length
            status = None
            continue
        if byte & 0x80:
            status = byte
            position += 1
        elif status is None:
            raise ValueError("The MIDI file is corrupt")
        if status >= 0xF0:
            raise ValueError("The MIDI file contains unsupported events")
        kind, channel = status & 0xF0, status & 0x0F
        if kind in (0xC0, 0xD0):
            position += 1
            continue
        first, second = data[position], data[position + 1]
        position += 2
        if channel == DRUM_CHANNEL:
            continue
        key = (track, channel, first)
        if kind == 0x90 and second > 0:
            open_notes.setdefault(key, []).append((tick, second))
        elif kind == 0x80 or kind == 0x90:
            pending = open_notes.get(key)
            if pending:
                start, velocity = pending.pop(0)
                notes.append((start, tick, first, velocity))
    for (_, _, pitch), pending in open_notes.items():
        for start, velocity in pending:
            notes.append((start, max(tick, start + 1), pitch, velocity))
