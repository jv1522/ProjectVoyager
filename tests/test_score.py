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
            widget.apply_button.click()
            self.assertEqual(got[-1][1].tempo, 60)
            got.clear()
            widget.apply_button.click()
            self.assertEqual(len(got), 1)
            widget.load(Path(folder) / "missing.musicxml")
            self.assertIn("Could not read", widget.status.text())
            widget.shutdown()
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
            write_score_audio(score.timed_notes(), tempo, wav, 4, 0.25)
            export_video(score, tempo, wav, 1.5, 1.0, 0.25, 0, out)
            self.assertGreater(out.stat().st_size, 1000)
