"""Paged, video-style notation: a static staff with key and time signature.

Bars are shown a page at a time (4 or 8). Two staves alternate: while the last bar
of the current page plays, the next page fades in on the other staff.
"""

import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from voyager.musicxml import Score

W = 1000.0  # logical width; the painter scales this to the widget
SPACE = 12.0  # staff line spacing
STAFF_BOTTOM = 4 * 7 + 2  # E4 as a diatonic index (octave * 7 + step)
BG = QColor("#0b1026")
INK = QColor("#e9e6dc")
DIM = QColor("#7f87a8")
GOLD = QColor("#f0c14b")
PLAYED = QColor("#b8993f")
PLAYHEAD_WIDTH = 120.0  # logical px; wide, soft-edged translucent band
SCROLL_X = 360.0  # where the playhead sits in scrolling mode
SCROLL_PPB = 90.0  # pixels per beat in scrolling mode
MAX_ZOOM = 1.7
LOOKAHEAD = 2.0  # beats ahead of the playhead in which upcoming notes glow
CLEF = "\U0001d11e"


def _draw_centered(painter, text, x, y_centre):
    """Draw text with its visual centre at y_centre (accidental glyph metrics vary by font)."""
    box = QFontMetrics(painter.font()).tightBoundingRect(text)
    painter.drawText(int(x - box.x()), int(y_centre - box.y() - box.height() / 2), text)


class ScoreView(QWidget):
    seek_requested = Signal(float)  # beat

    def __init__(self, parent=None):
        super().__init__(parent)
        self.score: Score | None = None
        self.beat = 0.0
        self.countdown = 0  # beats left in the count-in; 0 when not counting in
        self.countdown_phase = 0.0  # 0..1 through the current count-in beat
        self.transparent = False  # leave the background clear (for overlay exports)
        self.bars_per_page = 4
        self._pages: list[list] = []
        self._low, self._high = 28, 40
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(260)

    # --- model -----------------------------------------------------------

    def set_score(self, score: Score | None):
        self.score = score
        self.beat = 0.0
        if score:
            diatonics = [n.diatonic for n in score.notes]
            self._low = min(min(diatonics) - 2, STAFF_BOTTOM - 4)
            self._high = max(max(diatonics) + 2, STAFF_BOTTOM + 12)
        self._paginate()

    def set_bars_per_page(self, count: int):
        """Bars shown per page; 0 selects continuous scrolling."""
        self.bars_per_page = max(0, count)
        self._paginate()

    @property
    def scrolling(self) -> bool:
        return self.bars_per_page == 0

    def set_beat(self, beat: float, countdown: int = 0, phase: float = 0.0):
        self.beat = max(0.0, beat)
        self.countdown, self.countdown_phase = countdown, phase
        self.update()

    def _paginate(self):
        n = self.bars_per_page or len(self.score.measures if self.score else []) or 1
        measures = self.score.measures if self.score else []
        self._pages = [measures[i : i + n] for i in range(0, len(measures), n)]
        self.update()

    def page_of(self, beat: float) -> int:
        for index, page in enumerate(self._pages):
            if beat < page[-1].start + page[-1].length:
                return index
        return max(0, len(self._pages) - 1)

    @property
    def row_height(self) -> float:
        return (self._high - self._low) * SPACE / 2 + 44

    # --- geometry --------------------------------------------------------

    def _scale(self) -> tuple[float, float, float]:
        height = self.row_height * (1 if self.scrolling else 2)
        scale = min(self.width() / W, self.height() / height)
        return scale, (self.width() - W * scale) / 2, (self.height() - height * scale) / 2

    def _left(self) -> float:
        return 140 + 16 * abs(self.score.fifths if self.score else 0)

    def _y(self, diatonic: float, row: int) -> float:
        return row * self.row_height + 30 + (self._high - diatonic) * SPACE / 2

    def _x_range(self, page) -> tuple[float, float]:
        left = self._left()
        if self.scrolling:
            return SCROLL_X - (self.beat - page[0].start) * SCROLL_PPB, SCROLL_PPB
        return left, (W - 24 - left) / (self.bars_per_page_beats(page))

    def bars_per_page_beats(self, page) -> float:
        return sum(m.length for m in page) or 1.0

    def _x(self, beat: float, page) -> float:
        left, per_beat = self._x_range(page)
        return left + (beat - page[0].start) * per_beat

    def mousePressEvent(self, event):
        if not self._pages:
            return
        scale, ox, oy = self._scale()
        x = (event.position().x() - ox) / scale
        row = int(((event.position().y() - oy) / scale) // self.row_height)
        current = self.page_of(self.beat)
        page_index = current if row == current % 2 else current + 1
        if not 0 <= page_index < len(self._pages):
            return
        page = self._pages[page_index]
        left, per_beat = self._x_range(page)
        beat = page[0].start + (x - left) / per_beat
        self.seek_requested.emit(min(max(beat, page[0].start), page[-1].start + page[-1].length))

    # --- painting --------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.transparent:
            painter.fillRect(self.rect(), BG)
        if not self.score or not self._pages:
            return
        scale, ox, oy = self._scale()
        painter.translate(ox, oy)
        painter.scale(scale, scale)
        current = self.page_of(self.beat)
        measure = next(
            (m for m in self._pages[current] if m.start <= self.beat < m.start + m.length),
            self._pages[current][-1],
        )
        in_last_bar = measure is self._pages[current][-1]
        fade = (self.beat - measure.start) / measure.length if in_last_bar else 0.0
        fade = min(1.0, max(0.0, fade * 1.3))
        for index in (current, current + 1):
            if index < len(self._pages) and (index == current or not self.scrolling):
                self._draw_page(painter, index, 1.0 if index == current else fade, index == current)
        if self.countdown:
            self._draw_countdown(painter)

    def _draw_countdown(self, painter):
        """A large number that shrinks and fades through each count-in beat."""
        painter.setOpacity(0.9 - 0.55 * self.countdown_phase)
        painter.setPen(QColor(255, 224, 140))
        font = QFont("Helvetica", int(96 - 26 * self.countdown_phase), QFont.Bold)
        painter.setFont(font)
        _draw_centered(painter, str(self.countdown), W / 2, self.row_height / 2 + 4)
        painter.setOpacity(1.0)

    def _draw_page(self, painter, index, alpha, is_current):
        page, row, score = self._pages[index], index % 2, self.score
        left, per_beat = self._x_range(page)
        end_x = self._x(page[-1].start + page[-1].length, page)
        if self.scrolling:
            end_x = min(end_x, W - 12)
        lines = [self._y(STAFF_BOTTOM + 8 - 2 * i, row) for i in range(5)]  # top to bottom

        painter.setOpacity(1.0 if is_current else 0.25 + 0.75 * alpha)
        painter.setPen(QPen(DIM, 1.2))
        for y in lines:
            painter.drawLine(int(48), int(y), int(end_x), int(y))
        painter.drawLine(48, int(lines[0]), 48, int(lines[-1]))

        painter.setOpacity(1.0 if is_current else alpha)
        self._draw_clef(painter, lines)
        self._draw_signatures(painter, score, lines, index == 0)
        painter.setFont(QFont("Helvetica", 10))
        for m in page:
            x = self._x(m.start, page)
            if self.scrolling and not self._left() < x < W:
                continue
            painter.setPen(QPen(DIM, 1.2))
            painter.drawLine(int(x), int(lines[0]), int(x), int(lines[-1]))
            painter.drawText(int(x + 4), int(lines[0] - 14), str(m.index + 1))
        if not self.scrolling or end_x < W - 12:
            painter.setPen(QPen(INK, 2.4))
            painter.drawLine(int(end_x), int(lines[0]), int(end_x), int(lines[-1]))

        first, last = page[0].start, page[-1].start + page[-1].length
        for note in score.notes:
            if first <= note.start < last:
                if self.scrolling:
                    x = self._x(note.start, page)
                    if not self._left() - 10 < x < W:
                        continue
                    # Notes dissolve into the key signature on the left and appear from the right.
                    edge = min((x - self._left()) / 90, (W - x) / 140, 1.0)
                    painter.setOpacity(max(0.0, edge))
                self._draw_note(painter, note, page, row, lines, is_current)
        if is_current:
            x = self._x(min(self.beat, last), page)
            painter.setOpacity(1.0)
            half = PLAYHEAD_WIDTH / 2
            band = QLinearGradient(x - half, 0, x + half, 0)
            for stop, alpha in ((0.0, 0), (0.3, 62), (0.7, 62), (1.0, 0)):
                band.setColorAt(stop, QColor(255, 236, 150, alpha))
            painter.fillRect(
                QRectF(x - half, lines[0] - 40, PLAYHEAD_WIDTH, lines[-1] - lines[0] + 80), band
            )
        painter.setOpacity(1.0)

    def _draw_clef(self, painter, lines):
        font = QFont("Times", 54)
        painter.setPen(INK)
        if QFontMetrics(font).inFontUcs4(0x1D11E):
            painter.setFont(font)
            painter.drawText(54, int(lines[3] + 14), CLEF)
        else:
            font = QFont("Times", 40, QFont.Bold, True)
            painter.setFont(font)
            painter.drawText(58, int(lines[3] + 6), "G")

    def _draw_signatures(self, painter, score, lines, show_time):
        painter.setPen(INK)
        painter.setFont(QFont("Helvetica", 22))
        symbol = "\u266f" if score.fifths >= 0 else "\u266d"
        # Staff-line offsets (in half spaces from the top line) for each accidental.
        sharps = [0, 3, -1, 2, 5, 1, 4]
        flats = [4, 1, 5, 2, 6, 3, 7]
        for i in range(abs(score.fifths)):
            half = (sharps if score.fifths > 0 else flats)[i]
            _draw_centered(painter, symbol, 98 + 16 * i, lines[0] + half * SPACE / 2)
        if show_time:
            x = 104 + 16 * abs(score.fifths)
            painter.setFont(QFont("Helvetica", 24, QFont.Bold))
            _draw_centered(painter, str(score.beats), x, (lines[0] + lines[2]) / 2)
            _draw_centered(painter, str(score.unit), x, (lines[2] + lines[4]) / 2)

    def _next_note(self):
        return next((n for n in self.score.notes if n.start > self.beat), None)

    def _draw_glow(self, painter, x, y, closeness, is_next):
        """A halo that brightens as the note approaches, to guide the eye ahead of the playhead."""
        radius = 20 + 14 * closeness
        glow = QRadialGradient(x, y, radius)
        glow.setColorAt(0.0, QColor(255, 214, 120, int(150 * closeness)))
        glow.setColorAt(1.0, QColor(255, 214, 120, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
        if is_next:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 214, 120, int(200 * closeness)), 2))
            painter.drawEllipse(QRectF(x - 14, y - 14, 28, 28))

    def _draw_note(self, painter, note, page, row, lines, is_current):
        x = self._x(note.start, page) + 22
        y = self._y(note.diatonic, row)
        end = note.start + note.duration
        if is_current and note.start <= self.beat < end:
            colour = GOLD
        elif is_current and end <= self.beat:
            colour = PLAYED
        else:
            colour = INK
        if is_current and 0 < note.start - self.beat <= LOOKAHEAD:
            self._draw_glow(painter, x, y, 1.0 - (note.start - self.beat) / LOOKAHEAD, note is self._next_note())
        zoom = 1.0
        if is_current and note.start <= self.beat < end:
            progress = (self.beat - note.start) / note.duration
            zoom = 1.0 + (MAX_ZOOM - 1.0) * math.sin(math.pi * min(1.0, progress)) ** 0.5
        painter.setPen(QPen(colour, 1.6))
        top, bottom = lines[0], lines[-1]
        ly = top - SPACE
        while y <= ly + 1:
            painter.drawLine(int(x - 11), int(ly), int(x + 11), int(ly))
            ly -= SPACE
        ly = bottom + SPACE
        while y >= ly - 1:
            painter.drawLine(int(x - 11), int(ly), int(x + 11), int(ly))
            ly += SPACE
        implied = self.score.key_alterations().get(note.step, 0)
        if note.alter != implied:
            painter.setFont(QFont("Helvetica", 16))
            _draw_centered(painter, {0: "\u266e", 1: "\u266f", -1: "\u266d"}.get(note.alter, ""), x - 26, y)
        painter.save()
        painter.translate(x, y)
        painter.scale(zoom, zoom)
        painter.translate(-x, -y)
        painter.setBrush(colour if note.duration < 2.0 else Qt.NoBrush)
        painter.drawEllipse(QRectF(x - 7, y - 5.5, 14, 11))
        if note.duration < 4.0:
            up = note.diatonic < STAFF_BOTTOM + 4
            sx = x + 6.5 if up else x - 6.5
            ey = y - 36 if up else y + 36
            painter.drawLine(int(sx), int(y), int(sx), int(ey))
            if note.duration <= 0.5:
                flip = 1 if up else -1
                painter.drawLine(int(sx), int(ey), int(sx + 9), int(ey + 12 * flip))
        painter.restore()
        painter.setBrush(Qt.NoBrush)
