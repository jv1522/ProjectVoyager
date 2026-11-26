import sqlite3
import tempfile
import unittest
from pathlib import Path

from voyager.storage import JournalRepository


class JournalRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.repository = JournalRepository(root / "voyager.sqlite", root / "media")

    def tearDown(self):
        self.repository.close()
        self.temporary_directory.cleanup()

    def test_seed_is_created_once_with_initial_learning_milestone(self):
        entry_id = self.repository.seed_initial_entry()

        self.assertIsNotNone(entry_id)
        entry = self.repository.get_entry(entry_id)
        self.assertIn("A minor (Am), E major (E)", entry["notes"])
        self.assertIn("Am | Am | E | E | Am | E | E | Am", entry["composition"])
        self.assertEqual(entry["mission"], "Earth and Moon")
        self.assertEqual(entry["reflection"], "")
        self.assertIsNone(self.repository.seed_initial_entry())
        self.assertEqual(len(self.repository.list_entries()), 1)

    def test_seed_does_not_replace_existing_entries(self):
        entry_id = self.repository.create_entry("2026-01-01", "My entry")

        self.assertIsNone(self.repository.seed_initial_entry())
        self.assertEqual(self.repository.get_entry(entry_id)["title"], "My entry")

    def test_existing_database_and_media_remain_readable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database_path = root / "existing.sqlite"
            media_directory = root / "existing-media"
            media_directory.mkdir()
            (media_directory / "recording.wav").write_bytes(b"existing recording")
            connection = sqlite3.connect(database_path)
            connection.executescript(
                """
                CREATE TABLE entries(
                    id INTEGER PRIMARY KEY, day TEXT, title TEXT, notes TEXT,
                    reflection TEXT, composition TEXT, curriculum TEXT, mission TEXT
                );
                CREATE TABLE media(
                    id INTEGER PRIMARY KEY, entry_id INTEGER, name TEXT, path TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO entries VALUES(1, '2026-01-01', 'Existing', "
                "'Notes', '', 'Composition', '', 'Earth and Moon')"
            )
            connection.execute(
                "INSERT INTO media VALUES(1, 1, 'recording.wav', 'recording.wav')"
            )
            connection.commit()
            connection.close()

            repository = JournalRepository(database_path, media_directory)
            try:
                self.assertEqual(repository.get_entry(1)["title"], "Existing")
                attachment = repository.list_attachments(1)[0]
                self.assertEqual(
                    repository.attachment_path(attachment["path"]).read_bytes(),
                    b"existing recording",
                )
                self.assertIsNone(repository.seed_initial_entry())
            finally:
                repository.close()

    def test_entry_changes_persist_and_order_by_date(self):
        first_id = self.repository.create_entry("2026-01-01", "First")
        second_id = self.repository.create_entry("2026-02-01", "Second")
        self.repository.save_entry(first_id, {"notes": "Practice notes"})

        self.assertEqual(
            [entry["id"] for entry in self.repository.list_entries()],
            [second_id, first_id],
        )
        self.assertEqual(self.repository.get_entry(first_id)["notes"], "Practice notes")

    def test_save_rejects_unknown_fields(self):
        entry_id = self.repository.create_entry("2026-01-01", "Entry")

        with self.assertRaisesRegex(ValueError, "Unsupported entry fields"):
            self.repository.save_entry(entry_id, {"title; DROP TABLE entries": "bad"})

        self.assertEqual(len(self.repository.list_entries()), 1)

    def test_attachment_is_copied_to_local_media_directory(self):
        root = Path(self.temporary_directory.name)
        source = root / "recording.wav"
        source.write_bytes(b"practice recording")
        entry_id = self.repository.create_entry("2026-01-01", "Entry")

        self.repository.add_attachment(entry_id, source)
        attachment = self.repository.list_attachments(entry_id)[0]
        stored_path = self.repository.attachment_path(attachment["path"])

        self.assertEqual(attachment["name"], "recording.wav")
        self.assertEqual(stored_path.read_bytes(), b"practice recording")
        self.assertNotEqual(stored_path, source)

    def test_delete_and_replace_attachment(self):
        root = Path(self.temporary_directory.name)
        old, new = root / "old.mid", root / "new.mid"
        old.write_bytes(b"old")
        new.write_bytes(b"new")
        entry_id = self.repository.create_entry("2026-01-01", "Entry")
        first = self.repository.add_attachment(entry_id, old)
        second = self.repository.add_attachment(entry_id, old)

        old_stored = self.repository.attachment_path(
            self.repository.list_attachments(entry_id)[0]["path"]
        )
        self.repository.replace_attachment(first, new)
        row = self.repository.list_attachments(entry_id)[0]
        self.assertEqual(row["name"], "new.mid")
        self.assertEqual(self.repository.attachment_path(row["path"]).read_bytes(), b"new")
        self.assertFalse(old_stored.exists())

        self.repository.delete_attachment(second)
        self.assertEqual(len(self.repository.list_attachments(entry_id)), 1)
        self.assertEqual(len(list(self.repository.media_directory.iterdir())), 1)
        with self.assertRaises(ValueError):
            self.repository.delete_attachment(second)

    def test_attachment_requires_an_existing_entry(self):
        root = Path(self.temporary_directory.name)
        source = root / "recording.wav"
        source.write_bytes(b"practice recording")

        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.repository.add_attachment(99, source)

    def test_diaries_are_separated_by_instrument(self):
        guitar = self.repository.create_entry("2026-01-01", "Chords")
        violin = self.repository.create_entry("2026-01-02", "Open strings", "violin")
        self.assertEqual(
            [e["id"] for e in self.repository.list_entries("violin")], [violin]
        )
        self.assertEqual(
            [e["id"] for e in self.repository.list_entries("guitar")], [guitar]
        )
        self.assertEqual(self.repository.count_entries("violin"), 1)
        with self.assertRaises(ValueError):
            self.repository.create_entry("2026-01-03", "Bad", "banjo")

    def test_existing_database_without_instrument_migrates_to_guitar(self):
        root = Path(self.temporary_directory.name) / "old"
        root.mkdir()
        connection = sqlite3.connect(root / "voyager.sqlite")
        connection.executescript(
            "CREATE TABLE entries(id INTEGER PRIMARY KEY, day TEXT, title TEXT, notes TEXT,"
            " reflection TEXT, composition TEXT, curriculum TEXT, mission TEXT);"
            "INSERT INTO entries(day,title) VALUES('2025-12-01','Old');"
        )
        connection.commit()
        connection.close()
        repository = JournalRepository(root / "voyager.sqlite", root / "media")
        self.addCleanup(repository.close)
        self.assertEqual(repository.count_entries("guitar"), 1)
        self.assertEqual(repository.count_entries("violin"), 0)

    def test_attachment_copy_ignores_file_flags_and_cleans_up_on_failure(self):
        from unittest import mock

        root = Path(self.temporary_directory.name)
        source = root / "score.pdf"
        source.write_bytes(b"%PDF-1.4")
        entry_id = self.repository.create_entry("2026-01-01", "Entry")
        with mock.patch("shutil.copystat", side_effect=PermissionError):
            self.repository.add_attachment(entry_id, source)
        self.assertEqual(len(self.repository.list_attachments(entry_id)), 1)

        before = list(self.repository.media_directory.iterdir())
        with mock.patch("shutil.copyfile", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                self.repository.add_attachment(entry_id, source)
        self.assertEqual(list(self.repository.media_directory.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
