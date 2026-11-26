import unittest

from voyager.chords import (
    arpeggio_notes,
    bass_note,
    chord_tones,
    midi_to_frequency,
    parse_chord,
    strum_notes,
)


class ChordTests(unittest.TestCase):
    def test_parse_common_chords(self):
        am = parse_chord("Am")
        self.assertEqual((am.root, am.intervals), (9, (0, 3, 7)))
        e = parse_chord("E")
        self.assertEqual((e.root, e.intervals), (4, (0, 4, 7)))
        self.assertEqual(parse_chord("F#m7").root, 6)
        self.assertEqual(parse_chord("Bb").root, 10)
        self.assertEqual(parse_chord("A/C#").bass, 1)

    def test_unrecognised_names_return_none(self):
        self.assertIsNone(parse_chord("H"))
        self.assertIsNone(parse_chord("Axyz"))
        self.assertIsNone(parse_chord(""))

    def test_voicings_for_initial_progression(self):
        am, e = parse_chord("Am"), parse_chord("E")
        self.assertEqual(bass_note(am), 45)  # A2
        self.assertEqual(bass_note(e), 40)  # E2
        self.assertEqual(chord_tones(am), [57, 60, 64])  # A3 C4 E4
        self.assertEqual(arpeggio_notes(e), [64, 68, 71])  # E4 G#4 B4
        self.assertEqual(strum_notes(am), [45, 57, 60, 64])

    def test_frequency(self):
        self.assertAlmostEqual(midi_to_frequency(69), 440.0)
        self.assertAlmostEqual(midi_to_frequency(57), 220.0)


if __name__ == "__main__":
    unittest.main()
