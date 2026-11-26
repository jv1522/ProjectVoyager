"""Reusable inline video player with playback controls."""

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)

VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v"}


def is_video_file(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def format_time(milliseconds: int) -> str:
    seconds = max(0, int(milliseconds)) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


class VideoPlayerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(240)
        self.player.setVideoOutput(self.video)

        style = self.style()
        self.play_button = QPushButton()
        self.play_button.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.play_button.setToolTip("Play / Pause")
        self.stop_button = QPushButton()
        self.stop_button.setIcon(style.standardIcon(QStyle.SP_MediaStop))
        self.stop_button.setToolTip("Stop")
        self.position_slider = QSlider(Qt.Horizontal)
        self.time_label = QLabel("0:00 / 0:00")
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setMaximumWidth(110)
        self.volume_slider.setToolTip("Volume")
        self.audio.setVolume(0.7)
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.position_slider, 1)
        controls.addWidget(self.time_label)
        controls.addWidget(QLabel("Vol"))
        controls.addWidget(self.volume_slider)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.error_label)
        layout.addLayout(controls)

        self.play_button.clicked.connect(self.toggle_playback)
        self.stop_button.clicked.connect(self.player.stop)
        self.position_slider.sliderMoved.connect(self.player.setPosition)
        self.volume_slider.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.errorOccurred.connect(self._error)

    def load(self, path) -> None:
        self.player.stop()
        self.error_label.hide()
        self.player.setSource(QUrl.fromLocalFile(str(path)))

    def clear(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.error_label.hide()
        self.position_slider.setValue(0)
        self.time_label.setText("0:00 / 0:00")

    def toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _position_changed(self, position: int) -> None:
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(position)
        self.time_label.setText(
            f"{format_time(position)} / {format_time(self.player.duration())}"
        )

    def _duration_changed(self, duration: int) -> None:
        self.position_slider.setRange(0, duration)
        self.time_label.setText(
            f"{format_time(self.player.position())} / {format_time(duration)}"
        )

    def _state_changed(self, state) -> None:
        icon = QStyle.SP_MediaPause if state == QMediaPlayer.PlayingState else QStyle.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))

    def _error(self, error, message: str) -> None:
        self.error_label.setText(f"Playback error: {message}")
        self.error_label.show()
