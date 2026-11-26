"""Home page: one tile per diary."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# (instrument key, title, glyph)
DIARIES = (
    ("guitar", "Guitar diary", "🎸"),
    ("violin", "Violin diary", "🎻"),
)


class HomePage(QWidget):
    diary_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiles: dict[str, QPushButton] = {}
        title = QLabel("PROJECT VOYAGER")
        title.setObjectName("heading")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("Choose a diary to open")
        subtitle.setAlignment(Qt.AlignCenter)
        row = QHBoxLayout()
        row.setSpacing(32)
        for key, name, glyph in DIARIES:
            tile = QPushButton()
            tile.setObjectName("tile")
            tile.setCursor(Qt.PointingHandCursor)
            tile.setMinimumSize(240, 220)
            tile.setProperty("diary_name", f"{glyph}\n\n{name}")
            tile.clicked.connect(lambda _checked=False, k=key: self.diary_selected.emit(k))
            self.tiles[key] = tile
            row.addWidget(tile)
        self.set_counts({})

        layout = QVBoxLayout(self)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(24)
        layout.addLayout(row)
        layout.addStretch(2)

    def set_counts(self, counts: dict[str, int]) -> None:
        for key, tile in self.tiles.items():
            count = counts.get(key, 0)
            noun = "entry" if count == 1 else "entries"
            tile.setText(f"{tile.property('diary_name')}\n\n{count} {noun}")
