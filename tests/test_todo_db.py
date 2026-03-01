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
            text="Проверить прайс",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.assertGreater(todo_id, 0)
        rows = db.todo_list_open(user_id=1, limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), todo_id)
        self.assertIn("Проверить", str(rows[0][1]))

    def test_done_removes_from_open(self):
        todo_id = db.todo_add(
            user_id=1,
            text="Сделать дайджест",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        ok = db.todo_mark_done(user_id=1, todo_id=todo_id, done_at=datetime.now().isoformat(timespec="seconds"))
        self.assertTrue(ok)
        rows = db.todo_list_open(user_id=1, limit=10)
        self.assertEqual(rows, [])

    def test_delete(self):
        todo_id = db.todo_add(
            user_id=1,
            text="Удалить задачу",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.assertTrue(db.todo_delete(user_id=1, todo_id=todo_id))
        self.assertEqual(db.todo_list_open(user_id=1, limit=10), [])


if __name__ == "__main__":
    unittest.main()
