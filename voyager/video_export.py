"""Exports the animated notation plus its audio as a video using the ffmpeg program.

ffmpeg is an external tool, not a Python dependency. Frames are painted by the same
ScoreView that the app shows and streamed to ffmpeg as raw pixels.
"""

import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QColor, QImage

from voyager.musicxml import Score
from voyager.score_view import ScoreView
from voyager.timing import TempoMap

FPS = 30
SIZE = (1280, 720)
_EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


class ExportError(RuntimeError):
    pass


def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    for folder in _EXTRA_PATHS:  # apps started from Finder do not inherit the shell PATH
        candidate = Path(folder) / "ffmpeg"
        if candidate.is_file():
            return str(candidate)
    return None


def playback_state(
    seconds: float, tempo_map: TempoMap, lead: float, beat_seconds: float
) -> tuple[float, int, float]:
    """Map time since the start of the audio to (beat, count-in number left, count-in phase)."""
    if seconds < lead and beat_seconds > 0:
        slot = seconds / beat_seconds
        index = int(slot)
        total = round(lead / beat_seconds)
        return 0.0, max(1, total - index), slot - index
    return tempo_map.beat_at(seconds - lead), 0, 0.0


def export_video(
    score: Score,
    tempo_map: TempoMap,
    audio_path: Path,
    audio_seconds: float,
    lead: float,
    beat_seconds: float,
    bars_per_page: int,
    output: Path,
    transparent: bool = False,
    progress: Callable[[int, int], bool] | None = None,
) -> None:
    """Render every frame and encode with ffmpeg. progress(done, total) returns False to cancel."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ExportError("ffmpeg was not found. Install it (for example `brew install ffmpeg`) and try again.")
    view = ScoreView()
    view.resize(*SIZE)
    view.transparent = transparent
    view.set_score(score)
    view.set_bars_per_page(bars_per_page)
    width, height = SIZE
    total = max(1, math.ceil(audio_seconds * FPS))
    if transparent:
        codec = ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-c:a", "pcm_s16le"]
    else:
        codec = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", "-b:a", "192k"]
    command = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
        "-i", str(audio_path), *codec, "-shortest", str(output),
    ]
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        image = QImage(width, height, QImage.Format_ARGB32)
        cancelled = False
        try:
            for frame in range(total):
                beat, countdown, phase = playback_state(frame / FPS, tempo_map, lead, beat_seconds)
                view.set_beat(beat, countdown, phase)
                image.fill(QColor(0, 0, 0, 0) if transparent else QColor("#0b1026"))
                view.render(image)
                process.stdin.write(bytes(image.constBits()))
                if progress and not progress(frame + 1, total):
                    cancelled = True
                    break
        except (BrokenPipeError, OSError):
            pass  # ffmpeg exited early; its message is reported below
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.wait()
        if cancelled:
            Path(output).unlink(missing_ok=True)
            return
        if process.returncode != 0:
            errors.seek(0)
            Path(output).unlink(missing_ok=True)
            raise ExportError(errors.read().decode(errors="replace").strip() or "ffmpeg failed")
