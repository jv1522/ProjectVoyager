"""Provider-independent JSON exchange for learner-reviewed AI suggestions."""

import json
import re
from collections.abc import Mapping, Sequence

from voyager.chords import parse_chord
from voyager.metronome import MAX_BPM, MIN_BPM, parse_progression
from voyager.sheet_music import SheetAnalysis, tonic_and_mode


SUGGESTION_FIELDS = ("composition", "curriculum", "reflection", "mission")
EXPORT_REQUEST = (
    "Review attached evidence, suggest an original composition and curriculum. "
    "Return JSON with entry_id, composition, curriculum, reflection, mission. "
    "Do not invent performance observations."
)


def build_entry_brief(
    entry_id: int,
    values: Mapping[str, str],
    attachment_names: Sequence[str],
    instrument: str = "guitar",
) -> dict[str, object]:
    return {
        **values,
        "instrument": instrument,
        "entry_id": entry_id,
        "attachments": list(attachment_names),
        "request": EXPORT_REQUEST,
    }


def parse_ai_response(response_text: str, expected_entry_id: int) -> dict[str, str]:
    response = json.loads(response_text)
    if not isinstance(response, dict):
        raise ValueError("Response must be a JSON object")
    response_entry_id = response.get("entry_id")
    if type(response_entry_id) is not int or response_entry_id != expected_entry_id:
        raise ValueError("Response must match selected entry ID")

    updates = {
        field: response[field]
        for field in SUGGESTION_FIELDS
        if isinstance(response.get(field), str)
    }
    if not updates:
        raise ValueError("No supported fields found")
    return updates


SHEET_REQUEST = (
    "I attached a PDF of sheet music for a violin piece I am learning. Read it and return "
    "JSON with entry_id, key (e.g. 'G major'), time_signature (e.g. '3/4'), tempo (BPM as "
    "a number), and progression (one chord per bar, separated by ' | ', e.g. "
    "'G | C | D | G'). Choose chords that fit the key and the melody. Say so in 'notes' "
    "if you are unsure; do not invent details you cannot read."
)


def build_sheet_brief(
    entry_id: int, pdf_name: str, hints: Mapping[str, object]
) -> dict[str, object]:
    return {
        "entry_id": entry_id,
        "instrument": "violin",
        "pdf": pdf_name,
        "local_scan_hints": dict(hints),
        "request": SHEET_REQUEST,
    }


def parse_sheet_response(response_text: str, expected_entry_id: int) -> SheetAnalysis:
    """Validate an AI sheet-music analysis; the learner previews it before use."""
    response = json.loads(response_text)
    if not isinstance(response, dict):
        raise ValueError("Response must be a JSON object")
    entry_id = response.get("entry_id")
    if type(entry_id) is not int or entry_id != expected_entry_id:
        raise ValueError("Response must match selected entry ID")

    analysis = SheetAnalysis(source="AI analysis")
    key = response.get("key")
    if isinstance(key, str) and key.strip():
        if tonic_and_mode(key) is None:
            raise ValueError(f"Unrecognised key: {key!r}")
        analysis.key = key.strip()

    signature = response.get("time_signature")
    if isinstance(signature, str) and signature.strip():
        match = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(2|4|8|16)\s*", signature)
        if not match or not 1 <= int(match.group(1)) <= 16:
            raise ValueError(f"Unsupported time signature: {signature!r}")
        analysis.beats, analysis.unit = int(match.group(1)), int(match.group(2))

    tempo = response.get("tempo")
    if tempo is not None:
        if type(tempo) is not int or not MIN_BPM <= tempo <= MAX_BPM:
            raise ValueError(f"Tempo must be a whole number from {MIN_BPM} to {MAX_BPM}")
        analysis.tempo = tempo

    progression = response.get("progression")
    if isinstance(progression, str) and progression.strip():
        bars = parse_progression(progression)
        unknown = [bar for bar in bars if parse_chord(bar) is None]
        if unknown:
            raise ValueError("Unrecognised chords: " + ", ".join(unknown))
        analysis.progression = " | ".join(bars)

    notes = response.get("notes")
    if isinstance(notes, str) and notes.strip():
        analysis.notes.append(notes.strip())
    if not (analysis.key or analysis.beats or analysis.tempo or analysis.progression):
        raise ValueError("No supported fields found")
    return analysis
