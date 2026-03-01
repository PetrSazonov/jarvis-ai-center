import os
import tempfile
import unittest
from datetime import datetime

import db


class SubsDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="subs_", suffix=".db")
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

    def test_add_list_delete(self):
        now = datetime.now().isoformat(timespec="seconds")
        sub_id = db.subs_add(
            user_id=1,
            name="Netflix",
            next_date="2026-03-15",
            period="monthly",
            created_at=now,
        )
        rows = db.subs_list(user_id=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0][0]), sub_id)
        self.assertEqual(str(rows[0][1]), "Netflix")
        self.assertTrue(db.subs_delete(user_id=1, sub_id=sub_id))
        self.assertEqual(db.subs_list(user_id=1), [])


if __name__ == "__main__":
    unittest.main()
