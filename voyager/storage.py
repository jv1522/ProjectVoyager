"""SQLite persistence and local attachment storage."""

import shutil
import sqlite3
import uuid
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping


ENTRY_FIELDS = (
    "day",
    "title",
    "notes",
    "reflection",
    "composition",
    "curriculum",
    "mission",
)


INSTRUMENTS = ("guitar", "violin")
DEFAULT_INSTRUMENT = "guitar"


class JournalRepository:
    """Owns the journal database and its locally stored attachments."""

    def __init__(self, database_path: Path, media_directory: Path):
        self.database_path = Path(database_path)
        self.media_directory = Path(media_directory)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_directory.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS entries(
                id INTEGER PRIMARY KEY,
                day TEXT,
                title TEXT,
                notes TEXT,
                reflection TEXT,
                composition TEXT,
                curriculum TEXT,
                mission TEXT
            );
            CREATE TABLE IF NOT EXISTS media(
                id INTEGER PRIMARY KEY,
                entry_id INTEGER,
                name TEXT,
                path TEXT
            );
            """
        )
        columns = {row["name"] for row in self.connection.execute("PRAGMA table_info(entries)")}
        if "instrument" not in columns:
            # Existing entries pre-date multiple diaries and belong to guitar.
            self.connection.execute(
                "ALTER TABLE entries ADD COLUMN instrument TEXT NOT NULL DEFAULT 'guitar'"
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def list_entries(self, instrument: str | None = None) -> list[sqlite3.Row]:
        if instrument is None:
            query, parameters = "SELECT * FROM entries ORDER BY day DESC, id DESC", ()
        else:
            query = "SELECT * FROM entries WHERE instrument=? ORDER BY day DESC, id DESC"
            parameters = (instrument,)
        return list(self.connection.execute(query, parameters))

    def count_entries(self, instrument: str) -> int:
        return int(
            self.connection.execute(
                "SELECT COUNT(*) FROM entries WHERE instrument=?", (instrument,)
            ).fetchone()[0]
        )

    def get_entry(self, entry_id: int) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM entries WHERE id=?", (entry_id,)
        ).fetchone()

    def create_entry(
        self, day_value: str, title: str, instrument: str = DEFAULT_INSTRUMENT
    ) -> int:
        if instrument not in INSTRUMENTS:
            raise ValueError(f"Unsupported instrument: {instrument}")
        cursor = self.connection.execute(
            "INSERT INTO entries(day,title,instrument) VALUES(?,?,?)",
            (day_value, title, instrument),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def save_entry(self, entry_id: int, values: Mapping[str, str]) -> None:
        unknown_fields = set(values) - set(ENTRY_FIELDS)
        if unknown_fields:
            names = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unsupported entry fields: {names}")

        fields = [field for field in ENTRY_FIELDS if field in values]
        if not fields:
            return

        assignments = ", ".join(f"{field}=?" for field in fields)
        parameters = [values[field] for field in fields] + [entry_id]
        self.connection.execute(
            f"UPDATE entries SET {assignments} WHERE id=?", parameters
        )
        self.connection.commit()

    def seed_initial_entry(self, seed_assets: Iterable[Path] = ()) -> int | None:
        if self.connection.execute("SELECT 1 FROM entries LIMIT 1").fetchone():
            return None

        progression = "Am | Am | E | E | Am | E | E | Am"
        cursor = self.connection.execute(
            """
            INSERT INTO entries(day,title,notes,reflection,composition,curriculum,mission)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                date.today().isoformat(),
                "Leaving Earth — initial milestone",
                "Instrument: Acoustic guitar\n"
                "Chords learned: A minor (Am), E major (E)\n"
                "Tempo: 60 BPM\n"
                "Time signature: 4/4\n"
                f"Chord progression: {progression}",
                "",
                "Leaving Earth\n"
                "Tempo: 60 BPM\n"
                "Time signature: 4/4\n"
                f"Chord progression: {progression}",
                "",
                "Earth and Moon",
            ),
        )
        entry_id = int(cursor.lastrowid)
        self.connection.commit()

        for asset_path in seed_assets:
            self.add_attachment(entry_id, Path(asset_path))
        return entry_id

    def list_attachments(self, entry_id: int) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM media WHERE entry_id=?", (entry_id,)
            )
        )

    def add_attachment(self, entry_id: int, source_path: Path) -> int:
        if self.get_entry(entry_id) is None:
            raise ValueError(f"Entry {entry_id} does not exist")
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(source)
        target = self.media_directory / f"{uuid.uuid4().hex}{source.suffix}"
        # copyfile, not copy2: copying macOS file flags can raise PermissionError.
        try:
            shutil.copyfile(source, target)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        cursor = self.connection.execute(
            "INSERT INTO media(entry_id,name,path) VALUES(?,?,?)",
            (entry_id, source.name, target.name),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def _copy_into_media(self, source_path: Path) -> Path:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(source)
        target = self.media_directory / f"{uuid.uuid4().hex}{source.suffix}"
        try:
            shutil.copyfile(source, target)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return target

    def delete_attachment(self, attachment_id: int) -> None:
        row = self.connection.execute(
            "SELECT path FROM media WHERE id=?", (attachment_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Attachment {attachment_id} does not exist")
        self.connection.execute("DELETE FROM media WHERE id=?", (attachment_id,))
        self.connection.commit()
        self.attachment_path(row["path"]).unlink(missing_ok=True)

    def replace_attachment(self, attachment_id: int, source_path: Path) -> None:
        """Swap the stored file behind an attachment, keeping its place in the entry."""
        row = self.connection.execute(
            "SELECT path FROM media WHERE id=?", (attachment_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Attachment {attachment_id} does not exist")
        target = self._copy_into_media(source_path)
        self.connection.execute(
            "UPDATE media SET name=?, path=? WHERE id=?",
            (Path(source_path).name, target.name, attachment_id),
        )
        self.connection.commit()
        self.attachment_path(row["path"]).unlink(missing_ok=True)

    def attachment_path(self, stored_name: str) -> Path:
        return self.media_directory / stored_name
