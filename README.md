# Project Voyager
Native Python / Qt 6 guitar learning journal. Python 3.10+ recommended.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python main.py
```
On Windows activate with `.venv\Scripts\activate`.

The first launch seeds the Am/E lesson and copies the supplied image and video into local app data. The date is the upload date, not a verified practice date. Diary edits save on navigation and exit. Media open in the operating system's default player. The app displays its data directory; back up that entire directory, including SQLite and media, while the app is closed. AI brief export produces JSON; upload it and relevant media to ChatGPT, then import a matching JSON response. No API key or network service is required. AI suggestions append rather than overwrite. No automatic synchronization with ChatGPT Projects or Pages is implemented. This is a starter version, not a packaged installer.
