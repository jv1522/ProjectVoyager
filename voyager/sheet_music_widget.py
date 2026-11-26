"""Sheet Music tab (violin diary): attach a PDF, analyse it, send chords to the metronome."""

import json
import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from voyager.ai_exchange import build_sheet_brief, parse_sheet_response
from voyager.metronome import MAX_BPM, MIN_BPM, parse_progression
from voyager.sheet_music import (
    SheetAnalysis,
    analyze_text,
    suggest_progression,
    tonic_and_mode,
)

NOTE_NAMES = ("C", "C#", "Db", "D", "Eb", "E", "F", "F#", "Gb", "G", "Ab", "A", "Bb", "B")


def extract_pdf_text(path: str) -> str:
    """All text embedded in a PDF; empty for scanned or image-only scores."""
    document = QPdfDocument()
    if document.load(path) != QPdfDocument.Error.None_:
        raise ValueError("The PDF could not be opened")
    pages = [
        document.getAllText(index).text() for index in range(document.pageCount())
    ]
    document.close()
    return "\n".join(pages)


class SheetMusicWidget(QWidget):
    """Emits `applied(name, analysis)` when the learner accepts an analysis."""

    applied = Signal(str, object)
    attachments_changed = Signal()

    def __init__(self, repository, ensure_entry=None, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.ensure_entry = ensure_entry  # creates and selects an entry when none exists
        self.entry_id: int | None = None
        self.document = QPdfDocument(self)

        self.pdfs = QListWidget()
        self.pdfs.setMaximumHeight(90)
        self.pdfs.currentItemChanged.connect(self._show_pdf)
        self.view = QPdfView()
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setDocument(self.document)
        self.view.setMinimumHeight(220)

        self.key_tonic = QComboBox()
        self.key_tonic.addItem("—", None)
        for name in NOTE_NAMES:
            self.key_tonic.addItem(name, name)
        self.key_mode = QComboBox()
        self.key_mode.addItems(["major", "minor"])
        self.beats = QSpinBox()
        self.beats.setRange(1, 16)
        self.beats.setValue(4)
        self.unit = QComboBox()
        for value in (2, 4, 8, 16):
            self.unit.addItem(str(value), value)
        self.unit.setCurrentText("4")
        self.tempo = QSpinBox()
        self.tempo.setRange(MIN_BPM, MAX_BPM)
        self.tempo.setValue(60)
        self.tempo.setSuffix(" BPM")
        self.progression = QLineEdit()
        self.progression.setPlaceholderText("G | C | D | G")
        self.status = QLabel("Attach a PDF of your sheet music to begin.")
        self.status.setWordWrap(True)

        key_row = QHBoxLayout()
        key_row.addWidget(self.key_tonic)
        key_row.addWidget(self.key_mode)
        key_row.addStretch(1)
        signature_row = QHBoxLayout()
        signature_row.addWidget(self.beats)
        signature_row.addWidget(QLabel("/"))
        signature_row.addWidget(self.unit)
        signature_row.addStretch(1)
        form = QFormLayout()
        form.addRow("Key", key_row)
        form.addRow("Time signature", signature_row)
        form.addRow("Tempo", self.tempo)
        form.addRow("Chords (one per bar)", self.progression)

        buttons = QHBoxLayout()
        for label, handler in (
            ("Attach PDF…", self.attach_pdf),
            ("Scan PDF text", self.scan),
            ("Suggest chords from key", self.suggest),
            ("Export AI brief", self.export_brief),
            ("Import AI analysis", self.import_analysis),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        self.use_button = QPushButton("Use in metronome ▶")
        self.use_button.clicked.connect(self.apply)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pdfs)
        layout.addWidget(self.view, 1)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        layout.addWidget(self.use_button)

    # --- data ------------------------------------------------------------

    def set_entry(self, entry_id: int | None) -> None:
        self.entry_id = entry_id
        self.pdfs.clear()
        self.document.close()
        if entry_id is None:
            return
        for attachment in self.repository.list_attachments(entry_id):
            if attachment["name"].lower().endswith(".pdf"):
                item = QListWidgetItem(attachment["name"])
                item.setData(
                    Qt.UserRole, str(self.repository.attachment_path(attachment["path"]))
                )
                self.pdfs.addItem(item)
        if self.pdfs.count():
            self.pdfs.setCurrentRow(0)

    def _show_pdf(self, item, _old) -> None:
        self.document.close()
        if item:
            self.document.load(item.data(Qt.UserRole))

    def _current_pdf(self) -> tuple[str, str] | None:
        item = self.pdfs.currentItem()
        if item is None:
            self.status.setText("Attach and select a PDF first.")
            return None
        return item.text(), item.data(Qt.UserRole)

    def analysis(self) -> SheetAnalysis:
        """The values currently on screen, which the learner may have edited."""
        tonic = self.key_tonic.currentData()
        return SheetAnalysis(
            key=f"{tonic} {self.key_mode.currentText()}" if tonic else None,
            beats=self.beats.value(),
            unit=self.unit.currentData(),
            tempo=self.tempo.value(),
            progression=" | ".join(parse_progression(self.progression.text())),
        )

    def show_analysis(self, analysis: SheetAnalysis) -> None:
        if analysis.key and (parsed := tonic_and_mode(analysis.key)):
            names = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
            wanted = analysis.key.split()[0].capitalize()
            index = self.key_tonic.findData(wanted)
            if index < 0:  # enharmonic spelling, e.g. D# for Eb
                index = self.key_tonic.findData(names[parsed[0]])
            self.key_tonic.setCurrentIndex(max(index, 0))
            self.key_mode.setCurrentText("minor" if parsed[1] else "major")
        if analysis.beats and analysis.unit:
            self.beats.setValue(analysis.beats)
            self.unit.setCurrentIndex(max(self.unit.findData(analysis.unit), 0))
        if analysis.tempo:
            self.tempo.setValue(analysis.tempo)
        if analysis.progression:
            self.progression.setText(analysis.progression)
        lines = [f"Source: {analysis.source}."] if analysis.source else []
        lines += analysis.notes
        lines.append("Review and edit the values, then press “Use in metronome”.")
        self.status.setText(" ".join(lines))

    # --- actions ---------------------------------------------------------

    def attach_pdf(self) -> None:
        if self.entry_id is None and self.ensure_entry:
            self.ensure_entry()
        if self.entry_id is None:
            self.status.setText("Create or select a diary entry first.")
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach sheet music", "", "PDF (*.pdf)"
        )
        for path in paths:
            try:
                self.repository.add_attachment(self.entry_id, Path(path))
            except (OSError, sqlite3.Error, ValueError) as error:
                QMessageBox.warning(self, "Attachment failed", str(error))
        self.set_entry(self.entry_id)
        self.pdfs.setCurrentRow(self.pdfs.count() - 1)
        self.attachments_changed.emit()

    def scan(self) -> None:
        current = self._current_pdf()
        if current is None:
            return
        try:
            result = analyze_text(extract_pdf_text(current[1]))
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.show_analysis(result)

    def suggest(self) -> None:
        tonic = self.key_tonic.currentData()
        if not tonic:
            self.status.setText("Choose a key first.")
            return
        key = f"{tonic} {self.key_mode.currentText()}"
        self.progression.setText(suggest_progression(key))
        self.status.setText(
            f"Simple I-IV-V suggestion for {key}. Edit it to match the piece, then use it."
        )

    def export_brief(self) -> None:
        current = self._current_pdf()
        if current is None or self.entry_id is None:
            return
        name, path = current
        try:
            hints = analyze_text(extract_pdf_text(path))
        except ValueError:
            hints = SheetAnalysis()
        brief = build_sheet_brief(
            self.entry_id,
            name,
            {"key": hints.key, "time_signature": hints.time_signature, "tempo": hints.tempo},
        )
        target, _ = QFileDialog.getSaveFileName(
            self, "Export sheet music brief", "sheet-music-brief.json", "JSON (*.json)"
        )
        if not target:
            return
        try:
            Path(target).write_text(json.dumps(brief, indent=2), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        self.status.setText(
            "Brief exported. Upload it together with the PDF to your AI assistant, "
            "then import its JSON answer."
        )

    def import_analysis(self) -> None:
        if self.entry_id is None:
            return
        source, _ = QFileDialog.getOpenFileName(
            self, "Import AI analysis", "", "JSON (*.json)"
        )
        if not source:
            return
        try:
            result = parse_sheet_response(
                Path(source).read_text(encoding="utf-8"), self.entry_id
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Invalid response", str(error))
            return
        self.show_analysis(result)

    def apply(self) -> None:
        current = self._current_pdf()
        if current is None:
            return
        analysis = self.analysis()
        if not analysis.progression:
            self.status.setText("Enter or suggest chords before using them.")
            return
        self.applied.emit(current[0], analysis)
