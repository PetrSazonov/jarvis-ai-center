import os
import tempfile
import unittest
from datetime import datetime, timedelta

import db


class FitnessStreakTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="fit_streak_", suffix=".db")
        os.close(fd)
        self._tmp_path = path
        db.DATABASE_NAME = self._tmp_path
        db.init_db()

        self.workout_id = db.fitness_create_workout(
            title="Test workout",
            tags="",
            equipment="",
            difficulty=2,
            duration_sec=600,
            notes="",
            vault_chat_id=-1000000000001,
            vault_message_id=1,
            file_id="",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    def tearDown(self) -> None:
        db.DATABASE_NAME = self._orig_db_name
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def test_streak_empty(self):
        self.assertEqual(db.fitness_current_streak_days(user_id=1), 0)

    def test_streak_consecutive_days(self):
        now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        for offset in (0, 1, 2):
            db.fitness_add_session(
                user_id=1,
                workout_id=self.workout_id,
                done_at=(now - timedelta(days=offset)).isoformat(timespec="seconds"),
                rpe=7,
                comment=None,
            )
        self.assertEqual(db.fitness_current_streak_days(user_id=1), 3)

    def test_streak_break_on_gap(self):
        now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        for offset in (0, 1, 3):
            db.fitness_add_session(
                user_id=1,
                workout_id=self.workout_id,
                done_at=(now - timedelta(days=offset)).isoformat(timespec="seconds"),
                rpe=7,
                comment=None,
            )
        self.assertEqual(db.fitness_current_streak_days(user_id=1), 2)

    def test_streak_zero_if_last_session_too_old(self):
        now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        db.fitness_add_session(
            user_id=1,
            workout_id=self.workout_id,
            done_at=(now - timedelta(days=2)).isoformat(timespec="seconds"),
            rpe=7,
            comment=None,
        )
        self.assertEqual(db.fitness_current_streak_days(user_id=1), 0)

    def test_week_done_dates(self):
        now = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        monday = now - timedelta(days=now.weekday())
        for offset in (0, 2):
            db.fitness_add_session(
                user_id=1,
                workout_id=self.workout_id,
                done_at=(monday + timedelta(days=offset)).isoformat(timespec="seconds"),
                rpe=7,
                comment=None,
            )
        rows = db.fitness_week_done_dates(
            user_id=1,
            week_start_iso=monday.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds"),
            week_end_iso=(monday + timedelta(days=7)).replace(hour=0, minute=0, second=0).isoformat(timespec="seconds"),
        )
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
