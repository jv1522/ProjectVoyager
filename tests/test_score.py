import io
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from voyager.midi_file import parse_midi
from voyager.musicxml import analyze_score, derive_chords, load_musicxml, parse_musicxml
from voyager.score_audio import render_score
from voyager.timing import TempoMap

NOTE = "<note><pitch><step>{s}</step><octave>{o}</octave></pitch><duration>{d}</duration>{extra}</note>"


def xml(measures: str, fifths=0, mode="major", tempo=90) -> bytes:
    return f"""<score-partwise><work><work-title>Demo</work-title></work><part-list/>
<part id="P1">{measures.replace("@A", f'<attributes><divisions>2</divisions><key><fifths>{fifths}</fifths><mode>{mode}</mode></key><time><beats>4</beats><beat-type>4</beat-type></time></attributes><direction><sound tempo="{tempo}"/></direction>')}</part></score-partwise>""".encode()


def bar(number, *notes):
    return f'<measure number="{number}">' + "".join(notes) + "</measure>"


def n(step, octave, duration, extra=""):
    return NOTE.format(s=step, o=octave, d=duration, extra=extra)


def midi_bytes() -> bytes:
    track = b"\x00\xff\x51\x03\x07\xa1\x20"  # 120 bpm
    track += b"\x00\x90\x3c\x60" + b"\x83\x60\x80\x3c\x00"  # C4 for one beat (480 ticks)
    track += b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 480) + b"MTrk" + struct.pack(">I", len(track)) + track


class TimingAndMidi(unittest.TestCase):
    def test_tempo_map_round_trip(self):
        tm = TempoMap([(0, 60), (4, 120)])
        self.assertAlmostEqual(tm.seconds_at(4), 4.0)
        self.assertAlmostEqual(tm.seconds_at(6), 5.0)
        self.assertAlmostEqual(tm.beat_at(5.0), 6.0)

    def test_parse_midi(self):
        data = parse_midi(midi_bytes())
        self.assertEqual(len(data.notes), 1)
        self.assertEqual(data.notes[0].pitch, 60)
        self.assertAlmostEqual(data.notes[0].duration, 1.0)
        self.assertAlmostEqual(data.tempo_map.initial_bpm, 120.0)

    def test_bad_midi(self):
        with self.assertRaises(ValueError):
            parse_midi(b"nonsense")


class MusicXml(unittest.TestCase):
    def test_notes_ties_chords_rests(self):
        body = bar(
            1,
            "@A",
            n("C", 4, 4, '<tie type="start"/>'),
            n("C", 4, 4, '<tie type="stop"/>'),
            n("E", 4, 2),
            "<backup><duration>2</duration></backup>",
            n("G", 3, 2, "<chord/>") if False else n("G", 3, 2),
            "<note><rest/><duration>2</duration></note>",
            n("A", 4, 1, "<grace/>"),
        )
        score = parse_musicxml(xml(body))
        self.assertEqual(score.title, "Demo")
        pitches = sorted((round(x.start, 2), x.pitch, round(x.duration, 2)) for x in score.notes)
        self.assertIn((0.0, 60, 4.0), pitches)  # tie merged into one 4-beat note
        self.assertIn((4.0, 64, 1.0), pitches)
        self.assertIn((4.0, 55, 1.0), pitches)  # backup returned to the same position
        self.assertEqual(len(score.notes), 3)  # grace note skipped
        self.assertAlmostEqual(score.tempo_map.initial_bpm, 90)

    def test_key_and_chords(self):
        c_major = bar(1, "@A", n("C", 4, 4), n("E", 4, 4)) + bar(2, n("G", 4, 4), n("E", 4, 4))
        g_major = bar(3, n("G", 3, 4), n("B", 3, 4)) + bar(4, n("D", 4, 8))
        score = parse_musicxml(xml(c_major + g_major))
        chords = derive_chords(score)
        self.assertEqual(chords[0], "C")
        self.assertEqual(chords[2], "G")
        analysis = analyze_score(score)
        self.assertEqual(analysis.key, "C major")
        self.assertEqual(analysis.tempo, 90)

    def test_minor_key_name(self):
        score = parse_musicxml(xml(bar(1, "@A", n("A", 3, 8)), fifths=0, mode="minor"))
        self.assertEqual(score.key_name, "A minor")

    def test_rejects_entities_and_garbage(self):
        with self.assertRaises(ValueError):
            parse_musicxml(b'<!DOCTYPE x [<!ENTITY a "b">]><score-partwise/>')
        with self.assertRaises(ValueError):
            parse_musicxml(b"<html/>")

    def test_mxl(self):
        body = bar(1, "@A", n("C", 4, 8))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("META-INF/container.xml", '<container><rootfiles><rootfile full-path="s.xml"/></rootfiles></container>')
            archive.writestr("s.xml", xml(body))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.mxl"
            path.write_bytes(buffer.getvalue())
            self.assertEqual(len(load_musicxml(path).notes), 1)

    def test_render_audio(self):
        score = parse_musicxml(xml(bar(1, "@A", n("A", 4, 2))))
        samples = render_score(score.timed_notes(), score.tempo_map)
        self.assertGreater(len(samples), 8000)
        self.assertGreater(max(samples), 0.1)

    def test_explicit_short_bow_marks_propagate(self):
        marked = lambda mark: f"<notations><articulations><{mark}/></articulations></notations>"
        body = bar(1, "@A", n("A", 4, 1, marked("staccato")),
                   n("B", 4, 1, marked("spiccato")), n("C", 5, 1, marked("staccatissimo")),
                   n("D", 5, 1), n("E", 5, 1, marked("tenuto")))
        score = parse_musicxml(xml(body))
        notes = score.timed_notes()
        self.assertEqual([note.articulation for note in notes],
                         ["spiccato", "spiccato", "spiccato", "sustain", "sustain"])
        self.assertEqual([note.start for note in notes], [0, 0.5, 1, 1.5, 2])
        self.assertTrue(all(note.duration == 0.5 for note in notes))


class ViolinSamples(unittest.TestCase):
    def test_bundled_recordings_are_used_and_long_notes_loop(self):
        from voyager import score_audio

        recordings = score_audio._load_recordings()
        self.assertGreaterEqual(len(recordings), 15)
        # A note longer than the 4 s recording must still sound throughout.
        tone = score_audio._sampled_tone(69, 8.0)
        tail = tone[int(6 * score_audio.RATE) : int(7 * score_audio.RATE)]
        self.assertGreater(max(abs(v) for v in tail), 0.05)

    def test_falls_back_to_synth_without_recordings(self):
        from unittest import mock

        from voyager import score_audio

        with mock.patch.object(score_audio, "_recordings", []):
            self.assertIsNone(score_audio._sampled_tone(69, 1.0))
            samples = score_audio.render_score(
                parse_musicxml(xml(bar(1, "@A", n("A", 4, 2)))).timed_notes(), TempoMap([(0, 120)])
            )
        self.assertGreater(max(samples), 0.1)

    def test_short_bow_samples_have_two_takes_and_are_not_looped(self):
        from voyager import score_audio

        takes = score_audio._load_short_recordings()
        self.assertEqual([len(take) for take in takes], [11, 11])
        self.assertEqual({recording.root for recording in takes[0]},
                         {recording.root for recording in takes[1]})
        first = score_audio._sampled_tone(69, 8.0, "spiccato", 0)
        second = score_audio._sampled_tone(69, 8.0, "spiccato", 1)
        self.assertLess(len(first), 2 * score_audio.RATE)
        self.assertNotEqual(first, second)
        self.assertGreater(max(abs(value) for value in first), 0.05)
        self.assertEqual(first[-1], 0.0)
        shorter = score_audio._sampled_tone(70, 0.1, "spiccato")
        self.assertLessEqual(len(shorter), int((0.1 + score_audio.RELEASE) * score_audio.RATE))
        self.assertEqual(shorter[-1], 0.0)

    def test_short_bow_falls_back_to_sustain_and_synth(self):
        from unittest import mock
        from voyager import score_audio

        with mock.patch.object(score_audio, "_short_recordings", [[], []]):
            self.assertEqual(score_audio._sampled_tone(69, 0.2, "spiccato"),
                             score_audio._sampled_tone(69, 0.2))
            with mock.patch.object(score_audio, "_recordings", []):
                self.assertIsNone(score_audio._sampled_tone(69, 0.2, "spiccato"))
                notes = parse_musicxml(xml(bar(1, "@A", n(
                    "A", 4, 1, "<notations><articulations><staccato/></articulations></notations>"
                )))).timed_notes()
                self.assertGreater(max(render_score(notes, TempoMap())), 0.1)

    def test_short_bow_picks_nearest_recorded_pitch(self):
        from unittest import mock
        from voyager import score_audio

        recordings = [score_audio._Recording(69, [0.5] * 10000),
                      score_audio._Recording(72, [0.1] * 10000)]
        with mock.patch.object(score_audio, "_short_recordings", [recordings, recordings]):
            lower = score_audio._sampled_tone(70, 0.2, "spiccato")
            upper = score_audio._sampled_tone(71, 0.2, "spiccato")
        self.assertAlmostEqual(lower[300], 0.5)
        self.assertAlmostEqual(upper[300], 0.1)

    def test_round_robin_per_pitch_and_render_length(self):
        from unittest import mock
        from voyager import score_audio
        from voyager.timing import TimedNote

        notes = [TimedNote(0, 0.5, 69, articulation="spiccato"),
                 TimedNote(0.5, 0.5, 71, articulation="spiccato"),
                 TimedNote(1, 0.5, 69, articulation="spiccato"),
                 TimedNote(1.5, 0.5, 69, articulation="spiccato")]
        with mock.patch.object(score_audio, "_sampled_tone", wraps=score_audio._sampled_tone) as sample:
            result = render_score(notes, TempoMap([(0, 120)]))
        self.assertEqual([call.args for call in sample.call_args_list],
                         [(69, 0.25, "spiccato", 0), (71, 0.25, "spiccato", 0),
                          (69, 0.25, "spiccato", 1)])
        self.assertEqual(len(result), int(1.2 * score_audio.RATE))
        self.assertGreater(max(result), 0.1)


class Widget(unittest.TestCase):
    def test_load_tick_and_apply(self):
        from PySide6.QtWidgets import QApplication

        from voyager.score_widget import ScoreWidget

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            xml_path = Path(folder) / "s.musicxml"
            xml_path.write_bytes(xml(bar(1, "@A", n("A", 4, 8))))
            midi_path = Path(folder) / "s.mid"
            midi_path.write_bytes(midi_bytes())
            widget = ScoreWidget()
            got = []
            widget.applied.connect(lambda name, analysis: got.append((name, analysis)))
            widget.load(xml_path, midi_path)
            self.assertIn("MIDI", widget.status.text())
            self.assertNotIn(widget.score.key_name, widget.status.text())
            self.assertNotIn("4/4", widget.status.text())
            self.assertNotIn("Chords:", widget.status.text())
            widget.view.grab()  # exercise painting
            widget.seek_beat(2.0)
            self.assertAlmostEqual(widget.view.beat, 2.0)
            self.assertTrue(widget.view.scrolling)  # scrolling is the default view
            widget.view.set_beat(1.0)
            widget.view.grab()
            widget.bars_box.setCurrentIndex(1)
            self.assertFalse(widget.view.scrolling)
            widget.view.grab()
            self.assertEqual(widget.bpm_box.value(), 120)  # from the MIDI file
            widget.bpm_box.setValue(60)
            self.assertAlmostEqual(widget.tempo_map.seconds_at(4.0), 4.0)
            self.assertEqual(widget.beat_seconds, 0.5)
            self.assertEqual(widget.lead, 2.0)
            self.assertFalse(widget.backing_box.isChecked())
            self.assertTrue(widget.view.dance_enabled)
            widget.dance_box.setChecked(False)
            self.assertFalse(widget.view.dance_enabled)
            widget.dance_box.setChecked(True)
            self.assertTrue(widget.view.dance_enabled)
            widget._wav = Path(folder) / "old.wav"
            widget.backing_box.setChecked(True)
            self.assertIsNone(widget._wav)
            widget.apply_button.click()
            self.assertEqual(got[-1][1].tempo, 60)
            got.clear()
            widget.apply_button.click()
            self.assertEqual(len(got), 1)
            midi_path.write_bytes(b"not a MIDI file")
            widget.load(xml_path, midi_path)
            self.assertIn("MIDI unreadable", widget.status.text())
            widget.load(Path(folder) / "missing.musicxml")
            self.assertIn("Could not read", widget.status.text())
            widget.shutdown()
            del app

    def test_selected_backing_is_passed_to_audio_renderer(self):
        from unittest.mock import patch

        from PySide6.QtWidgets import QApplication

        from voyager.score_widget import ScoreWidget

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.musicxml"
            path.write_bytes(xml(bar(1, "@A", n("C", 4, 2)), tempo=60))
            widget = ScoreWidget()
            widget.load(path)
            self.assertEqual(widget.tempo_map.initial_bpm, 60)
            with patch("voyager.score_widget.write_score_audio", return_value=True) as render:
                self.assertTrue(widget._ensure_audio())
                self.assertIsNone(render.call_args.kwargs["accompaniment"])
                self.assertEqual(render.call_args.args[3:], (4, 0.5))
                widget.backing_box.setChecked(True)
                self.assertIsNone(widget._wav)
                self.assertTrue(widget._ensure_audio())
                self.assertIs(render.call_args.kwargs["accompaniment"], widget.score)
            widget.shutdown()
        del app


class ScoreAppearanceTests(unittest.TestCase):
    def test_score_view_uses_parchment_canvas_and_engraved_ink(self):
        from PySide6.QtWidgets import QApplication

        from voyager.score_view import BG, INK, ScoreView

        app = QApplication.instance() or QApplication([])
        view = ScoreView()
        view.resize(600, 300)
        image = view.grab().toImage()
        self.assertEqual(BG.name(), "#f7f2e6")
        self.assertEqual(INK.name(), "#29271f")
        self.assertEqual(image.pixelColor(0, 0), BG)
        del view
        del app

    def test_only_sounding_notes_glow(self):
        from unittest.mock import patch

        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtWidgets import QApplication

        from voyager.score_view import ScoreView

        app = QApplication.instance() or QApplication([])
        score = parse_musicxml(xml(bar(1, "@A", n("C", 4, 2), n("D", 4, 2))))
        view = ScoreView()
        view.set_score(score)
        next_note = score.notes[1]
        page = score.measures
        image = QImage(1000, 400, QImage.Format_ARGB32)
        painter = QPainter(image)
        with patch.object(view, "_draw_glow", wraps=view._draw_glow) as glow:
            view.set_beat(0.5)
            view._draw_note(painter, next_note, page, 0, [40, 52, 64, 76, 88], True)
            glow.assert_not_called()
            view.set_beat(0.0, countdown=4)
            view._draw_note(painter, score.notes[0], page, 0, [40, 52, 64, 76, 88], True)
            glow.assert_not_called()
            view.set_beat(1.5)
            view._draw_note(painter, next_note, page, 0, [40, 52, 64, 76, 88], True)
            glow.assert_called_once()
        painter.end()
        del view
        del app

    def test_dance_is_brief_and_stays_within_note_duration(self):
        from voyager.score_view import note_dance_angle

        self.assertEqual(note_dance_angle(-0.1, 1), 0)
        self.assertEqual(note_dance_angle(0, 1), 0)
        self.assertGreater(abs(note_dance_angle(0.06, 1)), 1)
        self.assertEqual(note_dance_angle(0.5, 1), 0)
        self.assertEqual(note_dance_angle(0.25, 0.25), 0)
        self.assertEqual(note_dance_angle(0, 0), 0)

    def test_paged_staves_remain_and_inactive_notes_transition(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication
        from voyager.score_view import ScoreView

        app = QApplication.instance() or QApplication([])
        body = "".join(
            bar(i + 1, "@A" if i == 0 else "", n("C", 4, 8))
            for i in range(12)
        )
        view = ScoreView()
        view.resize(1000, 600)
        view.set_score(parse_musicxml(xml(body)))
        view.set_bars_per_page(4)
        seeks = []
        view.seek_requested.connect(seeks.append)
        scale, ox, oy = view._scale()
        inactive_pos = QPoint(int(ox + 300 * scale), int(oy + view.row_height * 1.5 * scale))
        QTest.mouseClick(view, Qt.LeftButton, pos=inactive_pos)
        self.assertEqual(seeks, [])
        staves, pages = [], []
        draw_staff, draw_page = view._draw_staff, view._draw_page

        def capture_staff(painter, row, opacity, page=None):
            staves.append((row, opacity))
            draw_staff(painter, row, opacity, page)

        def capture_page(painter, index, alpha, is_current):
            pages.append((index, alpha))
            draw_page(painter, index, alpha, is_current)

        view._draw_staff, view._draw_page = capture_staff, capture_page
        view.set_beat(0)
        view.grab()
        self.assertEqual([row for row, _ in staves], [0, 1])
        self.assertEqual(pages, [(0, 1.0)])
        self.assertEqual(view._inactive_pages(0), (None, 1, 0.0))

        staves.clear()
        pages.clear()
        view.set_beat(14)
        view.grab()
        self.assertEqual([row for row, _ in staves], [0, 1])
        self.assertEqual(view._inactive_pages(0), (None, 1, 0.5))
        self.assertEqual(pages, [(1, 0.5), (0, 1.0)])

        pages.clear()
        view.set_beat(16)
        view.grab()
        self.assertEqual(view._inactive_pages(1), (0, 2, 0.0))
        self.assertEqual(pages, [(0, 0.35), (1, 1.0)])

        view.set_beat(30)
        self.assertEqual(view._inactive_pages(1), (0, 2, 0.5))
        upper_pos = QPoint(int(ox + 300 * scale), int(oy + view.row_height * 0.5 * scale))
        QTest.mouseClick(view, Qt.LeftButton, pos=upper_pos)
        self.assertGreaterEqual(seeks[-1], 32)
        view.set_beat(16)
        QTest.mouseClick(view, Qt.LeftButton, pos=upper_pos)
        self.assertLess(seeks[-1], 16)
        view.set_beat(48)
        self.assertEqual(view._inactive_pages(2), (1, None, 0.0))
        del view
        del app

    def test_export_title_draws_on_normal_and_transparent_frames(self):
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication

        from voyager.score_view import BG
        from voyager.video_export import TITLE_HEIGHT, _draw_title

        app = QApplication.instance() or QApplication([])
        for transparent in (False, True):
            image = QImage(600, 300, QImage.Format_ARGB32)
            image.fill(QColor(0, 0, 0, 0) if transparent else BG)
            _draw_title(image, "Leaving Earth", transparent)
            self.assertTrue(any(
                image.pixelColor(x, y).red() < 150
                and image.pixelColor(x, y).alpha() > 0
                for x in range(40, 300) for y in range(TITLE_HEIGHT)
            ))
            if transparent:
                self.assertEqual(image.pixelColor(599, 0).alpha(), 0)
                self.assertGreater(image.pixelColor(25, 30).alpha(), 0)
        del app


if __name__ == "__main__":
    unittest.main()


class CountInTests(unittest.TestCase):
    def test_audio_shifted_by_lead(self):
        from voyager import score_audio
        from voyager.timing import TempoMap, TimedNote

        notes = [TimedNote(0, 1, 69)]
        plain = score_audio.render_score(notes, TempoMap([(0, 120)]))
        lead = score_audio.render_score(notes, TempoMap([(0, 120)]), 4, 0.5)
        self.assertAlmostEqual(len(lead) - len(plain), 2 * score_audio.RATE, delta=10)
        self.assertGreater(max(abs(v) for v in lead[: score_audio.RATE // 20]), 0.05)

    def test_playback_state(self):
        from voyager.timing import TempoMap
        from voyager.video_export import playback_state

        tempo = TempoMap([(0, 120)])
        self.assertEqual(playback_state(0.0, tempo, 2.0, 0.5)[:2], (0.0, 4))
        self.assertEqual(playback_state(1.6, tempo, 2.0, 0.5)[:2], (0.0, 1))
        beat, countdown, _ = playback_state(3.0, tempo, 2.0, 0.5)
        self.assertEqual((beat, countdown), (2.0, 0))

    def test_count_in_is_independent_of_score_tempo(self):
        from voyager.video_export import playback_state

        tempo = TempoMap([(0, 60)])
        self.assertEqual(playback_state(1.5, tempo, 2.0, 0.5)[:2], (0.0, 1))
        self.assertEqual(playback_state(3.0, tempo, 2.0, 0.5)[:2], (1.0, 0))

    def test_accompaniment_follows_pickup_meter_and_tempo_changes(self):
        from voyager.musicxml import Measure, Score, ScoreNote
        from voyager.score_audio import accompaniment_events

        score = Score(
            beats=6,
            unit=8,
            measures=[Measure(0, 0, 0.5), Measure(1, 0.5, 3.0)],
            notes=[ScoreNote(0, 0.5, 60, "C", 4, 0, 0),
                   ScoreNote(0.5, 3, 67, "G", 4, 0, 1)],
        )
        events = accompaniment_events(score, TempoMap([(0, 120), (1, 60)]))
        beats = sorted(time for time, kind, _ in events if kind in ("kick", "snare"))
        self.assertEqual(beats, [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 2.5])
        self.assertEqual(len([event for event in events if event[1] == "chord"]), 6)
        self.assertEqual(len([event for event in events if event[1] == "shaker"]), 7)

    def test_backing_is_optional_and_starts_after_count_in(self):
        from voyager.score_audio import RATE, render_score

        score = parse_musicxml(xml(bar(1, "@A", n("C", 4, 2), n("E", 4, 2))))
        tempo = TempoMap([(0, 120)])
        plain = render_score(score.timed_notes(), tempo, 4, 0.5)
        backing = render_score(score.timed_notes(), tempo, 4, 0.5, accompaniment=score)
        self.assertEqual(plain[:2 * RATE], backing[:2 * RATE])
        self.assertNotEqual(plain[2 * RATE:], backing[2 * RATE:])

    def test_backing_chords_cover_all_measures(self):
        from voyager.musicxml import Measure, Score, ScoreNote, derive_chords
        from voyager.score_audio import accompaniment_events

        measures = [Measure(i, i * 4, 4) for i in range(34)]
        score = Score(measures=measures, notes=[ScoreNote(0, 1, 60, "C", 4, 0, 0)])
        self.assertEqual(len(derive_chords(score)), 32)
        self.assertEqual(len(derive_chords(score, include_pickup=True, max_bars=None)), 34)
        chords = [event for event in accompaniment_events(score, TempoMap()) if event[1] == "chord"]
        self.assertEqual(len(chords), 34 * 3)

    def test_export_smoke(self):
        import tempfile
        from pathlib import Path

        from voyager.score_audio import write_score_audio
        from voyager.timing import TempoMap, TimedNote
        from voyager.video_export import export_video, find_ffmpeg
        from voyager.musicxml import parse_musicxml

        if not find_ffmpeg():
            self.skipTest("ffmpeg not installed")
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance() or QApplication([])
        score = parse_musicxml(xml(bar(1, "@A", n("C", 4, 8))))
        tempo = TempoMap([(0, 240)])
        with tempfile.TemporaryDirectory() as folder:
            wav, out = Path(folder, "a.wav"), Path(folder, "o.mp4")
            write_score_audio(score.timed_notes(), tempo, wav, 4, 0.25, accompaniment=score)
            export_video(score, tempo, wav, 1.5, 1.0, 0.25, 0, out)
            self.assertGreater(out.stat().st_size, 1000)
