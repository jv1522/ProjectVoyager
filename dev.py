"""Hot-reload runner: restarts the app whenever a source file changes.

Usage: .venv/bin/python dev.py
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
POLL_SECONDS = 0.5


def snapshot() -> dict[Path, float]:
    files = [ROOT / "main.py", *(ROOT / "voyager").glob("*.py")]
    return {path: path.stat().st_mtime for path in files if path.exists()}


def main() -> int:
    process = subprocess.Popen([sys.executable, str(ROOT / "main.py")])
    seen = snapshot()
    try:
        while True:
            time.sleep(POLL_SECONDS)
            if process.poll() is not None:
                return process.returncode  # window closed normally
            current = snapshot()
            if current != seen:
                seen = current
                print("Change detected, restarting…", flush=True)
                process.terminate()
                process.wait()
                process = subprocess.Popen([sys.executable, str(ROOT / "main.py")])
    except KeyboardInterrupt:
        process.terminate()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
