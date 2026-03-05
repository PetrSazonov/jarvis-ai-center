import os
import tempfile
import unittest
from datetime import datetime

import db


class TodoDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="todo_", suffix=".db")
        os.close(fd)
        self._tmp_path = path
        db.DATABASE_NAME = self._tmp_path
        db.init_db()

    def tearDown(self) -> None:
        db.DATABASE_NAME = self._orig_db_name
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def test_add_and_list_open(self):
        todo_id = db.todo_add(
            user_id=1,
            text="check price",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.assertGreater(todo_id, 0)
        rows = db.todo_list_open(user_id=1, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), todo_id)
        self.assertIn("check", str(rows[0][1]))

    def test_done_removes_from_open(self):
        todo_id = db.todo_add(
            user_id=1,
            text="build digest",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        ok = db.todo_mark_done(user_id=1, todo_id=todo_id, done_at=datetime.now().isoformat(timespec="seconds"))
        self.assertTrue(ok)
        rows = db.todo_list_open(user_id=1, limit=10)
        self.assertEqual(rows, [])

    def test_delete(self):
        todo_id = db.todo_add(
            user_id=1,
            text="delete task",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.assertTrue(db.todo_delete(user_id=1, todo_id=todo_id))
        self.assertEqual(db.todo_list_open(user_id=1, limit=10), [])

    def test_due_and_reminder_metadata(self):
        todo_id = db.todo_add(
            user_id=7,
            text="check calendar",
            created_at="2026-03-05T10:00:00",
            due_date="2026-03-07",
            remind_at="2026-03-06T19:30:00",
            remind_telegram=True,
        )
        rows = db.todo_list_open(user_id=7, limit=10, include_meta=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), todo_id)
        self.assertEqual(str(rows[0][3]), "2026-03-07")
        self.assertEqual(str(rows[0][4]), "2026-03-06T19:30:00")

        due = db.todo_due_reminders(now_iso="2026-03-06T19:31:00", limit=10)
        self.assertEqual(len(due), 1)
        self.assertEqual(int(due[0][0]), todo_id)
        self.assertTrue(db.todo_mark_reminder_sent(todo_id=todo_id, sent_at="2026-03-06T19:31:15"))
        self.assertEqual(db.todo_due_reminders(now_iso="2026-03-06T19:32:00", limit=10), [])

    def test_update_item_allows_text_and_schedule(self):
        todo_id = db.todo_add(
            user_id=11,
            text="old title",
            created_at="2026-03-05T09:00:00",
            notes="old note",
            due_date="2026-03-08",
            remind_at=None,
            remind_telegram=True,
        )
        ok = db.todo_update_item(
            user_id=11,
            todo_id=todo_id,
            text="new title",
            has_text=True,
            notes="new note",
            has_notes=True,
            due_date="2026-03-09",
            has_due_date=True,
            remind_at="2026-03-08T20:30:00",
            has_remind_at=True,
            remind_telegram=True,
            has_remind_telegram=True,
        )
        self.assertTrue(ok)
        rows = db.todo_list_open(user_id=11, limit=5, include_meta=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0][1]), "new title")
        self.assertEqual(str(rows[0][3]), "2026-03-09")
        self.assertEqual(str(rows[0][4]), "2026-03-08T20:30:00")
        self.assertEqual(str(rows[0][5]), "new note")


if __name__ == "__main__":
    unittest.main()
