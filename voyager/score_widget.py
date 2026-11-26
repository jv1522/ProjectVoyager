"""Animated notation view: a MusicXML score with a playhead driven by synthesized audio."""

import math
import tempfile
import wave
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from voyager.metronome import MAX_BPM, MIN_BPM
from voyager.midi_file import parse_midi
from voyager.musicxml import Score, analyze_score, load_musicxml
from voyager.player import format_time
from voyager.score_audio import write_score_audio
from voyager.score_view import ScoreView
from voyager.timing import TempoMap
from voyager.video_export import ExportError, export_video, playback_state


class ScoreWidget(QWidget):
    applied = Signal(str, object)  # score name, SheetAnalysis

    def __init__(self, parent=None):
        super().__init__(parent)
        self.score: Score | None = None
        self.tempo_map = TempoMap()
        self._source_map = TempoMap()
        self.notes = []
        self.name = ""
        self._wav: Path | None = None
        self._tmp = tempfile.TemporaryDirectory(prefix="voyager-score-")
        self._analysis = None

        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            "font-family: Georgia, 'Times New Roman', serif; "
            "font-size: 19px; font-weight: bold;"
        )
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.view = ScoreView()
        self.view.seek_requested.connect(self.seek_beat)
        self.bpm_box = QSpinBox()
        self.bpm_box.setRange(20, 300)
        self.bpm_box.setSuffix(" BPM")
        self.bpm_box.setToolTip("Playback tempo in quarter notes per minute; change it before pressing Play")
        self.bpm_box.valueChanged.connect(lambda: self._bpm_changed())
        self.count_box = QCheckBox("Count-in")
        self.count_box.setChecked(True)
        self.count_box.setToolTip("Count one bar at 120 BPM before playback")
        self.count_box.toggled.connect(lambda: self._invalidate_audio())
        self.backing_box = QCheckBox("Accompaniment")
        self.backing_box.setToolTip(
            "Add percussion, bass and approximate chords derived from the score"
        )
        self.backing_box.toggled.connect(lambda: self._invalidate_audio())
        self.dance_box = QCheckBox("Dancing notes")
        self.dance_box.setChecked(True)
        self.dance_box.setToolTip("Add a brief wobble as each note starts")
        self.dance_box.toggled.connect(self._set_dancing_notes)
        self.bars_box = QComboBox()
        self.bars_box.addItem("Scrolling", 0)
        self.bars_box.addItem("4 bars per page", 4)
        self.bars_box.addItem("8 bars per page", 8)
        self.bars_box.currentIndexChanged.connect(
            lambda: self.view.set_bars_per_page(self.bars_box.currentData())
        )

        self.play_button = QPushButton("Play")
        self.stop_button = QPushButton("Stop")
        self.time_label = QLabel("0:00 / 0:00")
        self.export_button = QPushButton("Export video…")
        self.export_button.clicked.connect(lambda: self.export())
        self.apply_button = QPushButton("Use key, tempo && chords in metronome \u25b6")
        self.apply_button.setEnabled(False)
        self.play_button.clicked.connect(lambda: self.toggle())
        self.stop_button.clicked.connect(lambda: self.stop())
        self.apply_button.clicked.connect(lambda: self._apply())

        self.view.set_bars_per_page(self.bars_box.currentData())
        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.time_label)
        controls.addStretch(1)
        controls.addWidget(self.export_button)
        controls.addWidget(self.apply_button)
        settings = QHBoxLayout()
        settings.addWidget(self.bpm_box)
        settings.addWidget(self.count_box)
        settings.addWidget(self.backing_box)
        settings.addWidget(self.dance_box)
        settings.addWidget(self.bars_box)
        settings.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)
        layout.addLayout(settings)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.playbackStateChanged.connect(lambda *_: self._sync_button())
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self._set_controls(False)

    # --- loading ---------------------------------------------------------

    def load(self, score_path, midi_path=None, name: str = ""):
        self.clear()
        self.name = name or Path(score_path).name
        try:
            self.score = load_musicxml(score_path)
        except (ValueError, OSError) as error:
            self.status.setText(f"Could not read the MusicXML file: {error}")
            return
        self.notes = self.score.timed_notes()
        self.tempo_map = self._source_map = self.score.tempo_map
        source = "the MusicXML tempo"
        if midi_path:
            try:
                midi = parse_midi(Path(midi_path).read_bytes())
                if midi.notes:
                    self.notes, self.tempo_map = midi.notes, midi.tempo_map
                    self._source_map = self.tempo_map
                    source = "the MIDI file"
            except (ValueError, OSError) as error:
                source = f"the MusicXML (MIDI unreadable: {error})"
        self._analysis = analyze_score(self.score)
        self.bpm_box.blockSignals(True)
        self.bpm_box.setValue(int(round(self._source_map.initial_bpm)))
        self.bpm_box.blockSignals(False)
        self.view.set_score(self.score)
        self.title_label.setText(self.score.title or self.name)
        self.status.setText(f"Playback timing from {source}.")
        self._set_controls(True)
        self._update_time(0.0)

    def clear(self):
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.score = None
        self.notes = []
        self._wav = None
        self._analysis = None
        self.view.set_score(None)
        self.status.setText("")
        self.title_label.setText("")
        self._set_controls(False)

    def shutdown(self):
        self.clear()
        self.player.setAudioOutput(None)
        self._tmp.cleanup()

    def _bpm_changed(self):
        """Rescale the timing; the audio is re-rendered at the new tempo on the next Play."""
        if not self.score:
            return
        self.timer.stop()
        self._invalidate_audio()
        factor = self.bpm_box.value() / self._source_map.initial_bpm
        self.tempo_map = self._source_map.scaled(factor)
        self.view.set_beat(0.0)
        self._update_time(0.0)

    def _set_dancing_notes(self, enabled: bool):
        self.view.dance_enabled = enabled
        self.view.update()

    def _invalidate_audio(self):
        if not self.score:
            return
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self._wav = None
        self.view.set_beat(0.0)
        self._update_time(0.0)

    @property
    def count_in_beats(self) -> int:
        return self.score.beats if self.score and self.count_box.isChecked() else 0

    @property
    def beat_seconds(self) -> float:
        """Length of a count-in beat at 120 BPM, independently of the score."""
        return 0.5

    @property
    def lead(self) -> float:
        return self.count_in_beats * self.beat_seconds

    def _set_controls(self, enabled: bool):
        for button in (
            self.play_button, self.stop_button, self.apply_button, self.bpm_box,
            self.count_box, self.backing_box, self.export_button,
        ):
            button.setEnabled(enabled)

    # --- playback --------------------------------------------------------

    def _ensure_audio(self) -> bool:
        if self._wav:
            return True
        path = Path(self._tmp.name) / f"score-{int(time.time() * 1000)}.wav"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            written = write_score_audio(
                self.notes, self.tempo_map, path, self.count_in_beats, self.beat_seconds,
                accompaniment=self.score if self.backing_box.isChecked() else None,
            )
        finally:
            QApplication.restoreOverrideCursor()
        if not written:
            self.status.setText("Nothing to play in this score.")
            return False
        self._wav = path
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        return True

    def toggle(self):
        if not self.score:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
            self.timer.stop()
        elif self._ensure_audio():
            self.player.play()
            self.timer.start()

    def stop(self):
        self.player.stop()
        self.timer.stop()
        self.view.set_beat(0.0)
        self._update_time(0.0)

    def seek_beat(self, beat: float):
        if not self.score:
            return
        beat = min(beat, self.score.total_beats)
        if self._wav:
            self.player.setPosition(int((self.tempo_map.seconds_at(beat) + self.lead) * 1000))
        self.view.set_beat(beat)
        self._update_time(beat)

    def _tick(self):
        beat, countdown, phase = playback_state(
            self.player.position() / 1000, self.tempo_map, self.lead, self.beat_seconds
        )
        self.view.set_beat(beat, countdown, phase)
        self._update_time(beat)
        if self.player.playbackState() == QMediaPlayer.StoppedState:
            self.timer.stop()

    def export(self):
        """Save the animation and audio as a video (MP4, or a transparent MOV overlay)."""
        if not self.score or not self._ensure_audio():
            return
        path, chosen = QFileDialog.getSaveFileName(
            self, "Export video", f"{self.title_label.text() or 'score'}.mp4",
            "MP4 video (*.mp4);;Transparent MOV overlay (*.mov)",
        )
        if not path:
            return
        transparent = "MOV" in chosen or path.lower().endswith(".mov")
        if transparent and not path.lower().endswith(".mov"):
            path += ".mov"
        elif not transparent and not path.lower().endswith(".mp4"):
            path += ".mp4"
        self.stop()
        with wave.open(str(self._wav)) as handle:
            seconds = handle.getnframes() / handle.getframerate()
        dialog = QProgressDialog("Exporting video…", "Cancel", 0, 100, self)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)

        def progress(done: int, total: int) -> bool:
            dialog.setValue(int(done * 100 / total))
            QApplication.processEvents()
            return not dialog.wasCanceled()

        try:
            export_video(
                self.score, self.tempo_map, self._wav, seconds, self.lead, self.beat_seconds,
                self.view.bars_per_page,
                Path(path), transparent, progress,
                title=self.title_label.text(), dance_enabled=self.view.dance_enabled,
            )
        except ExportError as error:
            dialog.close()
            QMessageBox.warning(self, "Export failed", str(error))
            return
        dialog.close()
        if not dialog.wasCanceled():
            self.status.setText(f"Exported {Path(path).name}")

    def _update_time(self, beat: float):
        end = self.tempo_map.seconds_at(self.score.total_beats) if self.score else 0
        self.time_label.setText(
            f"{format_time(int(self.tempo_map.seconds_at(beat) * 1000))} / {format_time(int(end * 1000))}"
        )

    def _sync_button(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.play_button.setText("Pause" if playing else "Play")

    def _apply(self):
        if self._analysis:
            analysis = self._analysis
            clicks = self.bpm_box.value() * (self.score.unit / 4.0)
            analysis.tempo = int(round(min(max(clicks, MIN_BPM), MAX_BPM)))
            self.applied.emit(self.name, analysis)
