import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import *

from voyager.ai_exchange import build_entry_brief, parse_ai_response
from voyager.home import DIARIES, HomePage
from voyager.metronome import find_progression
from voyager.metronome_widget import MetronomeWidget
from voyager.sheet_music import format_for_entry, parse_settings
from voyager.sheet_music_widget import SheetMusicWidget
from voyager.player import VideoPlayerWidget, is_video_file
from voyager.score_widget import ScoreWidget

SCORE_SUFFIXES = {".musicxml", ".xml", ".mxl"}
MIDI_SUFFIXES = {".mid", ".midi"}
from voyager.storage import JournalRepository
from voyager.themes import DEFAULT_THEME, INSTRUMENT_THEMES, THEMES, build_stylesheet


class Window(QMainWindow):
    def __init__(self, repository):
        super().__init__()
        self.repository = repository
        self.setWindowTitle("Project Voyager | Guitar learning journal")
        self.resize(1200, 800)
        self.eid = None
        self.instrument = None
        self.dirty = False
        self.loading = False
        self.settings = QSettings()

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.home = HomePage()
        self.home.diary_selected.connect(self.open_diary)
        self.stack.addWidget(self.home)
        base = QWidget()
        self.stack.addWidget(base)
        layout = QHBoxLayout(base)
        side = QVBoxLayout()
        layout.addLayout(side, 1)
        home_button = QPushButton("← Home")
        home_button.clicked.connect(self.go_home)
        side.addWidget(home_button)
        self.diary_label = QLabel("PROJECT VOYAGER")
        side.addWidget(self.diary_label)
        self.theme_box = QComboBox()
        for theme in THEMES.values():
            self.theme_box.addItem(theme.name, theme.key)
        self.theme_box.activated.connect(self.choose_theme)
        side.addWidget(self.theme_box)
        self.list = QListWidget()
        side.addWidget(self.list)
        self.list.currentItemChanged.connect(self.select)
        for label, fn in [
            ("New diary entry", self.new),
            ("Save entry", lambda: self.save()),
            ("Export AI brief", self.export),
            ("Import AI response", self.import_ai),
            ("Reload app (Ctrl+R)", self.reload_app),
        ]:
            button = QPushButton(label)
            button.clicked.connect(fn)
            side.addWidget(button)
        QShortcut(QKeySequence("Ctrl+R"), self, self.reload_app)
        self.restart_requested = False
        side.addWidget(QLabel(str(repository.database_path.parent)))

        right = QVBoxLayout()
        layout.addLayout(right, 3)
        self.heading = QLabel("Learning diary")
        self.heading.setObjectName("heading")
        right.addWidget(self.heading)
        self.tabs = QTabWidget()
        right.addWidget(self.tabs)
        self.widgets = {}
        for tab, fields in [
            ("Diary", ["day", "title", "notes", "reflection"]),
            ("Composition", ["composition"]),
            ("Curriculum", ["curriculum"]),
            ("Voyager mission", ["mission"]),
        ]:
            page = QWidget()
            form = QFormLayout(page)
            for field in fields:
                widget = QLineEdit() if field in ["day", "title"] else QPlainTextEdit()
                self.widgets[field] = widget
                form.addRow(field.capitalize(), widget)
                widget.textChanged.connect(self.changed)
            if tab == "Voyager mission":
                form.addRow(self.build_voyager_video())
            self.tabs.addTab(page, tab)

        page = QWidget()
        media_layout = QVBoxLayout(page)
        self.assets = QListWidget()
        media_layout.addWidget(self.assets)
        self.preview = QLabel("Select an image to preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.player = VideoPlayerWidget()
        self.preview_stack = QStackedWidget()
        self.preview_stack.addWidget(self.preview)
        self.preview_stack.addWidget(self.player)
        self.score = ScoreWidget()
        self.score.applied.connect(self.use_sheet_analysis)
        self.preview_stack.addWidget(self.score)
        media_layout.addWidget(self.preview_stack, 1)
        self.assets.currentItemChanged.connect(self.show_media)
        for label, fn in [
            ("Attach images / videos / audio", self.add_media),
            ("Open selected file", self.open_media),
            ("Replace selected file…", self.replace_media),
            ("Delete selected file", self.delete_media),
        ]:
            button = QPushButton(label)
            button.clicked.connect(fn)
            media_layout.addWidget(button)
        self.tabs.addTab(page, "Media")
        self.metronome = MetronomeWidget()
        self.tabs.addTab(self.metronome, "Metronome")
        self.sheet = SheetMusicWidget(repository, self.ensure_entry)
        self.sheet.applied.connect(self.use_sheet_analysis)
        self.sheet.attachments_changed.connect(self.load_media)
        self.sheet_tab = self.tabs.addTab(self.sheet, "Sheet music")
        self.go_home(force=True)
        self.statusBar().showMessage("Local journal ready")

    # --- home page, diaries and themes --------------------------------------

    def apply_theme(self, key):
        theme = THEMES.get(key, THEMES[DEFAULT_THEME])
        QApplication.instance().setStyleSheet(build_stylesheet(theme))
        return theme

    def go_home(self, checked=False, force=False):
        if not force and self.instrument is not None:
            self.save(False)
            if self.dirty:
                return
        self.metronome.stop()
        self.player.clear()
        self.voyager_player.clear()
        self.instrument = None
        self.eid = None
        self.home.set_counts(
            {key: self.repository.count_entries(key) for key, _, _ in DIARIES}
        )
        self.apply_theme(DEFAULT_THEME)
        self.setWindowTitle("Project Voyager | Choose a diary")
        self.stack.setCurrentIndex(0)

    def open_diary(self, instrument):
        self.load_voyager_video()
        self.instrument = instrument
        self.eid = None
        name = instrument.capitalize()
        self.setWindowTitle(f"Project Voyager | {name} learning journal")
        self.diary_label.setText(f"PROJECT VOYAGER · {name.upper()}")
        self.heading.setText(f"{name} learning diary")
        key = self.settings.value(f"theme/{instrument}", INSTRUMENT_THEMES[instrument])
        if key not in THEMES:
            key = INSTRUMENT_THEMES[instrument]
        self.tabs.setTabVisible(self.sheet_tab, instrument == "violin")
        self.tabs.setCurrentIndex(0)
        self.theme_box.setCurrentIndex(self.theme_box.findData(key))
        self.apply_theme(key)
        self.stack.setCurrentIndex(1)
        self.refresh()

    def choose_theme(self, index):
        key = self.theme_box.itemData(index)
        self.settings.setValue(f"theme/{self.instrument}", key)
        self.apply_theme(key)

    def clear_entry(self):
        self.loading = True
        for widget in self.widgets.values():
            widget.clear()
        self.loading = False
        self.dirty = False
        self.assets.clear()
        self.preview.clear()
        self.player.clear()
        self.score.clear()
        self.sheet.set_entry(None)

    def changed(self):
        if not self.loading:
            self.dirty = True

    def refresh(self):
        if self.instrument is None:
            return
        self.list.blockSignals(True)
        self.list.clear()
        for entry in self.repository.list_entries(self.instrument):
            item = QListWidgetItem(entry["day"] + "  " + entry["title"])
            item.setData(Qt.UserRole, entry["id"])
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.list.count():
            index = next(
                (
                    index
                    for index in range(self.list.count())
                    if self.list.item(index).data(Qt.UserRole) == self.eid
                ),
                0,
            )
            self.list.setCurrentRow(index)
        else:
            self.eid = None
            self.clear_entry()

    def select(self, item, old):
        if not item:
            return
        if self.dirty and self.eid is not None:
            self.save(False)
            if self.dirty:
                self.refresh()
                return
        self.eid = item.data(Qt.UserRole)
        entry = self.repository.get_entry(self.eid)
        if entry is None:
            QMessageBox.warning(self, "Entry unavailable", "The selected entry no longer exists.")
            self.refresh()
            return
        self.loading = True
        for field, widget in self.widgets.items():
            value = entry[field] or ""
            if isinstance(widget, QLineEdit):
                widget.setText(value)
            else:
                widget.setPlainText(value)
        self.loading = False
        self.dirty = False
        progression = find_progression(entry["composition"] or "")
        if progression:
            self.metronome.set_progression(progression)
        tempo, signature = parse_settings(entry["composition"] or "")
        self.metronome.set_timing(tempo, signature)
        self.load_media()
        self.sheet.set_entry(self.eid)

    def use_sheet_analysis(self, pdf_name, analysis):
        """Accepted by the learner: save it in the entry and load the metronome."""
        composition = self.widgets["composition"]
        block = format_for_entry(pdf_name, analysis)
        existing = composition.toPlainText().rstrip()
        composition.setPlainText(f"{existing}\n\n{block}" if existing else block)
        self.metronome.set_progression(analysis.progression)
        self.metronome.set_timing(
            analysis.tempo,
            (analysis.beats, analysis.unit) if analysis.beats and analysis.unit else None,
        )
        self.save(False)
        self.tabs.setCurrentWidget(self.metronome)
        self.statusBar().showMessage("Sheet music chords loaded into the metronome", 5000)

    def values(self):
        return {
            field: widget.text() if isinstance(widget, QLineEdit) else widget.toPlainText()
            for field, widget in self.widgets.items()
        }

    def save(self, refresh=True):
        if self.eid is None:
            return
        try:
            self.repository.save_entry(self.eid, self.values())
        except sqlite3.Error as error:
            QMessageBox.warning(self, "Save failed", str(error))
            return
        self.dirty = False
        self.statusBar().showMessage("Saved", 3000)
        if refresh:
            self.refresh()

    def new(self):
        self.save(False)
        if self.dirty:
            return
        self.eid = self.repository.create_entry(
            date.today().isoformat(), "New lesson", self.instrument
        )
        self.refresh()

    def build_voyager_video(self):
        """A mission video shared by both diaries, kept in the app data folder."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        self.voyager_player = VideoPlayerWidget()
        self.voyager_caption = QLabel()
        button = QPushButton("Choose Voyager video…")
        button.clicked.connect(lambda: self.choose_voyager_video())
        layout.addWidget(self.voyager_caption)
        layout.addWidget(self.voyager_player, 1)
        layout.addWidget(button)
        self.load_voyager_video()
        return box

    @property
    def voyager_video_path(self):
        name = self.settings.value("voyager_video", "")
        path = self.repository.database_path.parent / "voyager_video" / name
        return path if name and path.is_file() else None

    def load_voyager_video(self):
        path = self.voyager_video_path
        if path:
            self.voyager_caption.setText(f"Voyager mission video: {path.name[33:] or path.name}")
            self.voyager_player.load(str(path))
        else:
            self.voyager_player.clear()
            self.voyager_caption.setText(
                "No Voyager video yet. Choose one (for example a NASA/JPL Voyager "
                "video you have downloaded); it is copied into the app's data folder."
            )

    def choose_voyager_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a Voyager video", "", "Video (*.mov *.mp4 *.m4v);;All files (*)"
        )
        if not path:
            return
        folder = self.repository.database_path.parent / "voyager_video"
        folder.mkdir(parents=True, exist_ok=True)
        stored = f"{uuid.uuid4().hex}-{Path(path).name}"
        self.voyager_player.clear()
        try:
            shutil.copyfile(path, folder / stored)
        except OSError as error:
            (folder / stored).unlink(missing_ok=True)
            QMessageBox.warning(self, "Video failed", str(error))
        else:
            old = self.voyager_video_path
            self.settings.setValue("voyager_video", stored)
            if old:
                old.unlink(missing_ok=True)
        self.load_voyager_video()

    def load_media(self):
        self.assets.clear()
        self.preview.clear()
        for attachment in self.repository.list_attachments(self.eid):
            item = QListWidgetItem(attachment["name"])
            item.setData(
                Qt.UserRole,
                str(self.repository.attachment_path(attachment["path"])),
            )
            item.setData(Qt.UserRole + 1, attachment["id"])
            self.assets.addItem(item)

    def ensure_entry(self):
        """Create a fresh entry when the learner attaches something to an empty diary."""
        if self.eid is None and self.instrument is not None:
            self.new()

    def add_media(self):
        self.ensure_entry()
        if self.eid is None:
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach practice evidence",
            "",
            "Media (*.png *.jpg *.jpeg *.webp *.mov *.mp4 *.wav *.mp3 *.m4a *.pdf *.mid *.midi *.musicxml *.xml *.mxl);;All files (*)",
        )
        for path in paths:
            try:
                self.repository.add_attachment(self.eid, path)
            except (OSError, sqlite3.Error, ValueError) as error:
                QMessageBox.warning(self, "Attachment failed", str(error))
        self.load_media()
        if paths and self.assets.count():
            self.assets.setCurrentRow(self.assets.count() - 1)
        self.sheet.set_entry(self.eid)

    def show_media(self, item, old):
        self.preview.clear()
        self.player.clear()
        self.score.clear()
        self.preview_stack.setCurrentWidget(self.preview)
        if item:
            path = Path(item.data(Qt.UserRole))
            suffix = path.suffix.lower()
            if suffix in SCORE_SUFFIXES | MIDI_SUFFIXES:
                self.show_score(item, suffix in MIDI_SUFFIXES)
                return
            if is_video_file(item.data(Qt.UserRole)):
                self.preview_stack.setCurrentWidget(self.player)
                self.player.load(item.data(Qt.UserRole))
                return
            pixmap = QPixmap(item.data(Qt.UserRole))
            if pixmap.isNull():
                self.preview.setText(
                    "Use Open selected file to play or view this attachment."
                )
            else:
                self.preview.setPixmap(
                    pixmap.scaled(
                        max(self.preview_stack.width() - 20, 200),
                        max(self.preview_stack.height() - 20, 200),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )

    def show_score(self, item, is_midi):
        """Pair a MusicXML attachment with a MIDI one and show the animated notation."""
        stem = Path(item.text()).stem.lower()
        found = {"score": None, "midi": None}
        for row in range(self.assets.count()):
            other = self.assets.item(row)
            suffix = Path(other.data(Qt.UserRole)).suffix.lower()
            kind = "midi" if suffix in MIDI_SUFFIXES else "score" if suffix in SCORE_SUFFIXES else None
            if kind is None:
                continue
            better = Path(other.text()).stem.lower() == stem
            if found[kind] is None or (better and Path(found[kind].text()).stem.lower() != stem):
                found[kind] = other
        found["midi" if is_midi else "score"] = item
        if found["score"] is None:
            self.preview.setText("Attach the matching MusicXML file to see animated notation.")
            return
        midi = found["midi"]
        self.preview_stack.setCurrentWidget(self.score)
        self.score.load(
            found["score"].data(Qt.UserRole),
            midi.data(Qt.UserRole) if midi else None,
            found["score"].text(),
        )

    def _release_media(self):
        """Let go of every open handle on attachment files before changing them."""
        self.player.clear()
        self.score.clear()
        self.preview.clear()
        self.sheet.set_entry(None)

    def _after_media_change(self, row):
        self.load_media()
        self.sheet.set_entry(self.eid)
        if self.assets.count():
            self.assets.setCurrentRow(min(row, self.assets.count() - 1))

    def delete_media(self):
        item = self.assets.currentItem()
        if item is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete file",
            f"Delete \"{item.text()}\" from this entry? The stored copy is removed; "
            "your original file is not touched.",
        )
        if answer != QMessageBox.Yes:
            return
        row = self.assets.currentRow()
        self._release_media()
        try:
            self.repository.delete_attachment(item.data(Qt.UserRole + 1))
        except (OSError, sqlite3.Error, ValueError) as error:
            QMessageBox.warning(self, "Delete failed", str(error))
        self._after_media_change(row)

    def replace_media(self):
        item = self.assets.currentItem()
        if item is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose the replacement file", "", "All files (*)"
        )
        if not path:
            return
        row = self.assets.currentRow()
        self._release_media()
        try:
            self.repository.replace_attachment(item.data(Qt.UserRole + 1), Path(path))
        except (OSError, sqlite3.Error, ValueError) as error:
            QMessageBox.warning(self, "Replace failed", str(error))
        self._after_media_change(row)

    def open_media(self):
        item = self.assets.currentItem()
        if item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))

    def export(self):
        if self.eid is None:
            return
        self.save(False)
        if self.dirty:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export AI brief", "voyager-brief.json", "JSON (*.json)"
        )
        if not path:
            return
        data = build_entry_brief(
            self.eid,
            self.values(),
            [item["name"] for item in self.repository.list_attachments(self.eid)],
            self.instrument,
        )
        try:
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as error:
            QMessageBox.warning(self, "Export failed", str(error))
            return
        QMessageBox.information(
            self,
            "Exported",
            "Upload this JSON and the relevant media to ChatGPT. Media are not embedded in JSON.",
        )

    def import_ai(self):
        if self.eid is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import AI response", "", "JSON (*.json)"
        )
        if not path:
            return
        try:
            updates = parse_ai_response(
                Path(path).read_text(encoding="utf-8"), self.eid
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Invalid response", str(error))
            return
        if (
            QMessageBox.question(
                self, "Apply AI response", "Append AI suggestions to selected entry?"
            )
            != QMessageBox.Yes
        ):
            return
        for field, value in updates.items():
            self.widgets[field].appendPlainText("\nAI suggestion:\n" + value)
        self.save()

    def reload_app(self):
        """Save, close and relaunch the app so code changes take effect."""
        self.restart_requested = True
        self.close()
        if self.isVisible():  # close was refused (unsaved data); stay open
            self.restart_requested = False

    def closeEvent(self, event):
        self.save(False)
        if self.dirty:
            event.ignore()
            return
        self.player.clear()
        self.voyager_player.clear()
        self.score.shutdown()
        self.sheet.set_entry(None)
        self.metronome.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("Voyager")
    app.setApplicationName("GuitarDiary")
    app.setStyle("Fusion")
    app.setStyleSheet(build_stylesheet(THEMES[DEFAULT_THEME]))

    data_directory = Path(
        QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    )
    repository = JournalRepository(
        data_directory / "voyager.sqlite", data_directory / "media"
    )
    try:
        seed_directory = Path(__file__).parent / "seed"
        repository.seed_initial_entry(
            path for path in seed_directory.glob("*") if path.is_file()
        )
        window = Window(repository)
        window.show()
        result = app.exec()
    finally:
        repository.close()
    if window.restart_requested:
        os.execv(sys.executable, [sys.executable, *sys.argv])
    # Media backends can stall while Python tears Qt objects down; everything
    # is saved and closed by now, so leave immediately.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(result)


if __name__ == "__main__":
    raise SystemExit(main())
