"""Metronome panel: musical chime chords with the progression highlighted."""

import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt, QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from voyager.chords import (
    arpeggio_notes,
    bass_note,
    chord_tones,
    midi_to_frequency,
    parse_chord,
)
from voyager.metronome import (
    DEFAULT_PROGRESSION,
    MAX_BPM,
    MIN_BPM,
    PERCUSSION,
    TIMBRES,
    Layer,
    beat_position,
    interval_ms,
    parse_progression,
    write_jingle,
    write_layers,
    write_shaker,
)

# Wooden timbres are layered with a metal companion, and vice versa.
WOODY = {"marimba", "kalimba", "nylon", "steel"}

GOLD = "#d4af37"
BAR_STYLE = (
    "QLabel{background:#202b3d;border:1px solid #38475d;border-radius:8px;"
    "padding:14px;font-size:22px;font-weight:bold;color:#9fb0c6}"
)
BAR_ACTIVE_STYLE = (
    f"QLabel{{background:#3a3220;border:2px solid {GOLD};border-radius:8px;"
    f"padding:14px;font-size:22px;font-weight:bold;color:{GOLD}}}"
)
DOT_STYLE = "QLabel{font-size:26px;color:#38475d}"
DOT_ACTIVE_STYLE = f"QLabel{{font-size:26px;color:{GOLD}}}"
DOT_ACCENT_ACTIVE_STYLE = "QLabel{font-size:26px;color:#ffffff}"

STYLE_JINGLE = "jingle"
# (label, key): keys in TIMBRES play chords; keys in PERCUSSION play unpitched clicks.
SOUND_CHOICES = (
    ("Chime chords", "chime"),
    ("Marimba (wood)", "marimba"),
    ("Kalimba (thumb piano)", "kalimba"),
    ("Vibraphone (metal)", "vibraphone"),
    ("Nylon guitar pluck", "nylon"),
    ("Steel guitar pluck", "steel"),
    ("Woodblock", "woodblock"),
    ("Claves (wood)", "claves"),
    ("Cowbell (metal)", "cowbell"),
    ("Triangle (metal)", "triangle"),
    ("Jingle bell (classic)", STYLE_JINGLE),
)
STRUM_SPREAD = 0.018  # seconds between strummed strings


class MetronomeWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sound_dir = tempfile.TemporaryDirectory(prefix="voyager-sounds-")
        self._effects: dict[str, QSoundEffect] = {}
        self.bars: list[str] = []
        self.bar_labels: list[QLabel] = []
        self.beat_dots: list[QLabel] = []
        self.tick = 0
        self._count_ticks = 0
        self._start = 0.0
        self._active = (-1, -1)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._on_tick)

        self.progression_edit = QLineEdit(DEFAULT_PROGRESSION)
        self.progression_edit.setPlaceholderText("Am | Am | E | E | Am | E | E | Am")
        self.bpm = QSpinBox()
        self.bpm.setRange(MIN_BPM, MAX_BPM)
        self.bpm.setValue(60)
        self.bpm.setSuffix(" BPM")
        self.beats = QSpinBox()
        self.beats.setRange(1, 16)
        self.beats.setValue(4)
        self.unit = QComboBox()
        for value in (2, 4, 8, 16):
            self.unit.addItem(str(value), value)
        self.unit.setCurrentText("4")
        self.sound_style = QComboBox()
        for label, key in SOUND_CHOICES:
            self.sound_style.addItem(label, key)
        self.subdivision = QComboBox()
        self.subdivision.addItem("Quarter notes", 1)
        self.subdivision.addItem("Eighth notes (shaker)", 2)
        self.count_in = QCheckBox("Count-in (first round only)")
        self.count_in.setChecked(True)
        self.loop = QCheckBox("Loop")
        self.loop.setChecked(True)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.toggle)
        self.status = QLabel("Chime metronome ready")

        signature = QHBoxLayout()
        signature.addWidget(self.beats)
        signature.addWidget(QLabel("/"))
        signature.addWidget(self.unit)
        signature.addStretch(1)
        form = QFormLayout()
        form.addRow("Progression", self.progression_edit)
        form.addRow("Tempo", self.bpm)
        form.addRow("Time signature", signature)
        form.addRow("Sound", self.sound_style)
        form.addRow("Rhythm", self.subdivision)

        self.bars_row = QHBoxLayout()
        self.dots_row = QHBoxLayout()
        self.dots_row.setAlignment(Qt.AlignCenter)
        controls = QHBoxLayout()
        controls.addWidget(self.start_button)
        controls.addWidget(self.loop)
        controls.addWidget(self.count_in)
        controls.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(self.bars_row)
        layout.addLayout(self.dots_row)
        layout.addLayout(controls)
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.progression_edit.editingFinished.connect(self.rebuild)
        self.beats.valueChanged.connect(self.rebuild)
        self.rebuild()

    # --- sounds -----------------------------------------------------------

    def _effect(self, key: str, render, volume: float = 0.9) -> QSoundEffect:
        """Render a sound once (cached by key) and wrap it in a QSoundEffect."""
        if key not in self._effects:
            path = Path(self._sound_dir.name) / f"{len(self._effects)}.wav"
            render(path)
            effect = QSoundEffect(self)
            effect.setSource(QUrl.fromLocalFile(str(path)))
            effect.setVolume(volume)
            self._effects[key] = effect
        return self._effects[key]

    def _layers(self, chord_name: str, beat: int) -> tuple[list[Layer], str] | None:
        """Instrument layers for one beat: every beat sounds several voices."""
        key = self.sound_style.currentData()
        chord = parse_chord(chord_name)
        if chord is None or key not in TIMBRES and key not in PERCUSSION:
            return None
        bass = bass_note(chord)
        tones = chord_tones(chord)
        top = arpeggio_notes(chord)
        if key in PERCUSSION:
            accent_hz, normal_hz, partials = PERCUSSION[key]
            click = [(accent_hz if beat == 0 else normal_hz, 0.0, 1.0)]
            pad = [
                (midi_to_frequency(n), i * 0.012, 0.35)
                for i, n in enumerate(([bass] if beat == 0 else []) + tones)
            ]
            return [(click, partials), (pad, TIMBRES["chime"])], f"{key}:{beat == 0}"
        main = TIMBRES[key]
        companion = TIMBRES["vibraphone" if key in WOODY else "marimba"]
        if beat == 0:
            strum = [
                (midi_to_frequency(n), i * STRUM_SPREAD, 1.0 if i == 0 else 0.8)
                for i, n in enumerate([bass] + tones)
            ]
            sparkle = [(midi_to_frequency(n), 0.0, 0.3) for n in top]
            return [(strum, main), (sparkle, companion)], f"{key}:down"
        index = (beat - 1) % len(top)
        low = bass if beat % 2 == 0 else bass + 7  # alternating root and fifth
        lead = [(midi_to_frequency(top[index]), 0.0, 1.0)]
        harmony = [
            (midi_to_frequency(n), 0.012 * (i + 1), 0.4)
            for i, n in enumerate(t for j, t in enumerate(tones) if j != index)
        ]
        bass_part = [(midi_to_frequency(low), 0.0, 0.6)]
        layers = [(lead, main), (harmony, companion), (bass_part, main)]
        return layers, f"{key}:{index}:{beat % 2}"

    def _beat_effect(self, chord_name: str, beat: int) -> QSoundEffect | None:
        built = self._layers(chord_name, beat)
        if built is None:
            return None
        layers, variant = built
        return self._effect(
            f"beat:{chord_name}:{variant}",
            lambda p: write_layers(p, layers, 1.5 if beat == 0 else 0.9),
            volume=0.9 if beat == 0 else 0.8,
        )

    def _count_effect(self, accent: bool) -> QSoundEffect:
        _, _, partials = PERCUSSION["claves"]
        frequency = 2500.0 if accent else 2000.0
        return self._effect(
            f"count:{accent}",
            lambda p: write_layers(p, [([(frequency, 0.0, 1.0)], partials)], 0.3),
            volume=1.0 if accent else 0.8,
        )

    def _shaker_effect(self) -> QSoundEffect:
        return self._effect("shaker", write_shaker, volume=0.45)

    def _jingle_effect(self, accent: bool) -> QSoundEffect:
        frequency = 2600.0 if accent else 1900.0
        return self._effect(
            f"jingle:{accent}", lambda p: write_jingle(p, frequency)
        )

    def _prepare_sounds(self) -> None:
        """Render every sound the run will use, before the first beat."""
        self.status.setText("Preparing sounds…")
        QCoreApplication.processEvents()
        for chord in set(self.bars):
            for beat in range(self.beats.value()):
                self._beat_effect(chord, beat)
        # Jingle is the selected style, and the fallback for unrecognised chord names.
        self._jingle_effect(True)
        self._jingle_effect(False)
        if self.count_in.isChecked():
            self._count_effect(True)
            self._count_effect(False)
        if self.subdivision.currentData() == 2:
            self._shaker_effect()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and not all(
            effect.status() == QSoundEffect.Ready for effect in self._effects.values()
        ):
            QCoreApplication.processEvents()

    def _play_beat(self, chord: str, beat: int) -> None:
        key = self.sound_style.currentData()
        effect = self._beat_effect(chord, beat)
        if effect is not None:
            effect.play()
        else:
            self._jingle_effect(beat == 0).play()

    # --- progression and display -------------------------------------------

    def shutdown(self) -> None:
        """Stop and release every sound so nothing is playing at exit."""
        self.stop()
        for effect in self._effects.values():
            effect.stop()
            effect.setSource(QUrl())
        self._effects.clear()

    def set_timing(self, bpm: int | None = None, signature: tuple[int, int] | None = None) -> None:
        if bpm is not None:
            self.bpm.setValue(bpm)
        if signature is not None:
            self.beats.setValue(signature[0])
            index = self.unit.findData(signature[1])
            if index >= 0:
                self.unit.setCurrentIndex(index)

    def set_progression(self, text: str) -> None:
        self.progression_edit.setText(text)
        self.rebuild()

    def rebuild(self) -> None:
        if self.timer.isActive():
            self.stop()
        self.bars = parse_progression(self.progression_edit.text())
        self._clear_row(self.bars_row)
        self._clear_row(self.dots_row)
        self.bar_labels = []
        self.beat_dots = []
        for chord in self.bars:
            label = QLabel(chord)
            label.setAlignment(Qt.AlignCenter)
            label.setStyleSheet(BAR_STYLE)
            self.bars_row.addWidget(label, 1)
            self.bar_labels.append(label)
        for _ in range(self.beats.value()):
            dot = QLabel("●")
            dot.setStyleSheet(DOT_STYLE)
            self.dots_row.addWidget(dot)
            self.beat_dots.append(dot)
        self.start_button.setEnabled(bool(self.bars))
        self._active = (-1, -1)

    @staticmethod
    def _clear_row(row) -> None:
        while row.count():
            widget = row.takeAt(0).widget()
            if widget:
                widget.deleteLater()

    # --- transport ----------------------------------------------------------

    def toggle(self) -> None:
        if self.timer.isActive():
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        self.rebuild()
        if not self.bars:
            return
        self._prepare_sounds()
        # Negative ticks are the count-in; the progression starts at tick 0.
        self._count_ticks = (
            self.beats.value() * self.subdivision.currentData()
            if self.count_in.isChecked()
            else 0
        )
        self.tick = -self._count_ticks
        self._start = time.monotonic()
        self.start_button.setText("Stop")
        self._on_tick()

    def stop(self) -> None:
        self.timer.stop()
        self.start_button.setText("Start")
        self.status.setText("Stopped")
        self._highlight(-1, -1)

    def _on_tick(self) -> None:
        divisions = self.subdivision.currentData()
        beats = self.beats.value()
        if not self.loop.isChecked() and self.tick >= beats * len(self.bars) * divisions:
            self.stop()
            self.status.setText("Finished")
            return
        if self.tick < 0:
            if self.tick % divisions == 0:
                count = (self._count_ticks + self.tick) // divisions
                self._highlight(-1, count)
                self._count_effect(count == 0).play()
                self.status.setText(f"Count-in  {count + 1}/{beats}")
            self.tick += 1
            self._schedule(divisions)
            return
        bar, beat = beat_position(self.tick // divisions, beats, len(self.bars))
        if self.tick % divisions == 0:
            self._highlight(bar, beat)
            self._play_beat(self.bars[bar], beat)
            self.status.setText(
                f"{self.bars[bar]}  —  bar {bar + 1}/{len(self.bars)}, beat {beat + 1}/{beats}"
            )
        else:
            self._shaker_effect().play()
        self.tick += 1
        self._schedule(divisions)

    def _schedule(self, divisions: int) -> None:
        # Schedule against the absolute start time so timer jitter never accumulates.
        elapsed = self.tick + self._count_ticks
        due = self._start + elapsed * interval_ms(self.bpm.value()) / divisions / 1000.0
        self.timer.start(max(0, int((due - time.monotonic()) * 1000)))

    def _highlight(self, bar: int, beat: int) -> None:
        previous_bar, _ = self._active
        if 0 <= previous_bar < len(self.bar_labels):
            self.bar_labels[previous_bar].setStyleSheet(BAR_STYLE)
        for index, dot in enumerate(self.beat_dots):
            if index == beat:
                dot.setStyleSheet(DOT_ACCENT_ACTIVE_STYLE if beat == 0 else DOT_ACTIVE_STYLE)
            else:
                dot.setStyleSheet(DOT_STYLE)
        if 0 <= bar < len(self.bar_labels):
            self.bar_labels[bar].setStyleSheet(BAR_ACTIVE_STYLE)
        self._active = (bar, beat)
