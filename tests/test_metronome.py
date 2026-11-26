import tempfile
import unittest
import wave
from pathlib import Path

from voyager.metronome import (
    beat_position,
    find_progression,
    interval_ms,
    parse_progression,
    write_chime_notes,
    write_jingle,
    write_shaker,
)


class MetronomeTests(unittest.TestCase):
    def test_parse_progression(self):
        self.assertEqual(
            parse_progression("Am | Am | E | E | Am | E | E | Am"),
            ["Am", "Am", "E", "E", "Am", "E", "E", "Am"],
        )
        self.assertEqual(parse_progression(" | |  "), [])

    def test_find_progression_in_composition_text(self):
        text = "Leaving Earth\nTempo: 60 BPM\nChord progression: Am | Am | E | E"
        self.assertEqual(find_progression(text), "Am | Am | E | E")
        self.assertIsNone(find_progression("Tempo: 60 BPM\nNo chords here"))

    def test_interval_ms(self):
        self.assertEqual(interval_ms(60), 1000.0)
        self.assertEqual(interval_ms(120), 500.0)
        with self.assertRaises(ValueError):
            interval_ms(0)

    def test_beat_position_wraps_through_bars(self):
        self.assertEqual(beat_position(0, 4, 8), (0, 0))
        self.assertEqual(beat_position(3, 4, 8), (0, 3))
        self.assertEqual(beat_position(4, 4, 8), (1, 0))
        self.assertEqual(beat_position(32, 4, 8), (0, 0))
        self.assertEqual(beat_position(5, 3, 2), (1, 2))

    def test_jingle_is_valid_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jingle.wav"
            write_jingle(path, 1900.0, duration=0.4)
            with wave.open(str(path)) as wav:
                self.assertEqual(wav.getnchannels(), 1)
                self.assertGreater(wav.getnframes(), 0)

    def test_chime_chord_and_shaker_are_valid_wavs(self):
        with tempfile.TemporaryDirectory() as directory:
            chime = Path(directory) / "chime.wav"
            write_chime_notes(chime, [(220.0, 0.0, 1.0), (277.2, 0.018, 0.8)], 0.5)
            shaker = Path(directory) / "shaker.wav"
            write_shaker(shaker)
            for path in (chime, shaker):
                with wave.open(str(path)) as wav:
                    self.assertGreater(wav.getnframes(), 1000)


    def test_every_timbre_and_percussion_renders(self):
        from voyager.metronome import PERCUSSION, TIMBRES

        with tempfile.TemporaryDirectory() as directory:
            for name, partials in TIMBRES.items():
                path = Path(directory) / f"{name}.wav"
                write_chime_notes(path, [(220.0, 0.0, 1.0)], 0.3, partials=partials)
                with wave.open(str(path)) as wav:
                    self.assertGreater(wav.getnframes(), 1000, name)
            for name, (accent, _normal, partials) in PERCUSSION.items():
                path = Path(directory) / f"{name}.wav"
                write_chime_notes(path, [(accent, 0.0, 1.0)], 0.3, partials=partials)
                with wave.open(str(path)) as wav:
                    self.assertGreater(wav.getnframes(), 1000, name)


if __name__ == "__main__":
    unittest.main()
