import json
import tempfile
import unittest
from pathlib import Path

from voyager.ai_exchange import build_sheet_brief, parse_sheet_response
from voyager.sheet_music import (
    analyze_text,
    find_chord_symbols,
    format_for_entry,
    parse_settings,
    suggest_progression,
)


class AnalyzeTextTests(unittest.TestCase):
    def test_reads_key_time_signature_and_tempo(self):
        result = analyze_text("Minuet in G major\n3/4\n♩ = 96\nViolin")
        self.assertEqual(result.key, "G major")
        self.assertEqual((result.beats, result.unit), (3, 4))
        self.assertEqual(result.tempo, 96)

    def test_chord_symbols_win_over_a_key_suggestion(self):
        result = analyze_text("Key: A minor\n4/4\nAm  E  Am  E\nlyrics here")
        self.assertEqual(result.progression, "Am | E | Am | E")
        self.assertIn("chord symbols", result.source)

    def test_key_only_gives_a_labelled_suggestion(self):
        result = analyze_text("Concerto in D major, Allegro")
        self.assertEqual(result.progression.split(" | ")[:2], ["D", "D"])
        self.assertEqual(result.tempo, 128)
        self.assertTrue(any("suggestion" in note for note in result.notes))

    def test_dates_are_not_time_signatures(self):
        self.assertIsNone(analyze_text("Printed 12/4/2024").beats)

    def test_no_text_explains_next_step(self):
        result = analyze_text("")
        self.assertFalse(result.found_anything)
        self.assertTrue(result.notes)

    def test_words_are_not_chords(self):
        self.assertEqual(find_chord_symbols("A Dance For Violin"), [])


class ProgressionTests(unittest.TestCase):
    def test_major_and_minor_keys(self):
        self.assertEqual(suggest_progression("G major"), "G | G | C | D | G | C | D | G")
        self.assertEqual(suggest_progression("A minor"), "Am | Am | Dm | E | Am | Dm | E | Am")

    def test_flat_keys_use_flat_names(self):
        self.assertEqual(suggest_progression("Bb major", 4), "Bb | Bb | Eb | F")

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(ValueError):
            suggest_progression("H major")


class SettingsTests(unittest.TestCase):
    def test_saved_block_round_trips(self):
        result = analyze_text("Key of E minor 6/8 ♩ = 72")
        result.progression = "Em | B"
        tempo, signature = parse_settings(format_for_entry("piece.pdf", result))
        self.assertEqual((tempo, signature), (72, (6, 8)))


class AiSheetResponseTests(unittest.TestCase):
    def test_valid_response(self):
        text = json.dumps(
            {"entry_id": 4, "key": "D major", "time_signature": "6/8", "tempo": 90,
             "progression": "D | A | Bm | G", "notes": "Melody is simple"}
        )
        result = parse_sheet_response(text, 4)
        self.assertEqual((result.key, result.time_signature, result.tempo), ("D major", "6/8", 90))
        self.assertEqual(result.progression, "D | A | Bm | G")

    def test_rejects_wrong_entry_bad_chord_and_bad_tempo(self):
        good = {"entry_id": 4, "progression": "D | A"}
        with self.assertRaises(ValueError):
            parse_sheet_response(json.dumps({**good, "entry_id": 5}), 4)
        with self.assertRaises(ValueError):
            parse_sheet_response(json.dumps({**good, "progression": "D | Zz"}), 4)
        with self.assertRaises(ValueError):
            parse_sheet_response(json.dumps({**good, "tempo": 999}), 4)
        with self.assertRaises(ValueError):
            parse_sheet_response(json.dumps({"entry_id": 4}), 4)

    def test_brief_names_the_pdf(self):
        brief = build_sheet_brief(2, "bach.pdf", {"key": None})
        self.assertEqual((brief["pdf"], brief["instrument"]), ("bach.pdf", "violin"))


class PdfExtractionTests(unittest.TestCase):
    def test_text_is_read_from_a_real_pdf(self):
        from PySide6.QtGui import QPainter, QPdfWriter
        from PySide6.QtWidgets import QApplication

        from voyager.sheet_music_widget import extract_pdf_text

        QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "score.pdf"
            writer = QPdfWriter(str(path))
            painter = QPainter(writer)
            painter.drawText(500, 800, "Etude in G major")
            painter.drawText(500, 1200, "3/4  quarter = 84")
            painter.drawText(500, 1600, "G   C   D   G")
            painter.end()
            result = analyze_text(extract_pdf_text(str(path)))
        self.assertEqual(result.key, "G major")
        self.assertEqual((result.beats, result.unit, result.tempo), (3, 4, 84))
        self.assertEqual(result.progression, "G | C | D | G")


if __name__ == "__main__":
    unittest.main()
