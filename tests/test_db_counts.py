import os
import tempfile
import unittest
from datetime import datetime, timedelta

import db


class DBCountsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="db_counts_", suffix=".db")
        os.close(fd)
        self._tmp_path = path
        db.DATABASE_NAME = self._tmp_path
        db.init_db()
        self.user_id = 101

        workout_id = db.fitness_create_workout(
            title="Count workout",
            tags="test",
            equipment="none",
            difficulty=2,
            duration_sec=900,
            notes="",
            vault_chat_id=1,
            vault_message_id=1001,
            file_id="",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self.workout_id = int(workout_id)

    def tearDown(self) -> None:
        db.DATABASE_NAME = self._orig_db_name
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def test_todo_done_count_between(self):
        base = datetime(2026, 3, 1, 10, 0, 0)
        t1 = base.isoformat(timespec="seconds")
        t2 = (base + timedelta(hours=3)).isoformat(timespec="seconds")
        t3 = (base + timedelta(days=1)).isoformat(timespec="seconds")

        todo_1 = db.todo_add(user_id=self.user_id, text="A", created_at=t1)
        todo_2 = db.todo_add(user_id=self.user_id, text="B", created_at=t2)
        todo_3 = db.todo_add(user_id=self.user_id, text="C", created_at=t3)

        db.todo_mark_done(user_id=self.user_id, todo_id=int(todo_1), done_at=t1)
        db.todo_mark_done(user_id=self.user_id, todo_id=int(todo_2), done_at=t2)
        db.todo_mark_done(user_id=self.user_id, todo_id=int(todo_3), done_at=t3)

        start = base.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
        end = (base.replace(hour=0, minute=0, second=0) + timedelta(days=1)).isoformat(timespec="seconds")
        count = db.todo_done_count_between(user_id=self.user_id, start_iso=start, end_iso=end)
        self.assertEqual(count, 2)

    def test_fitness_done_count_between(self):
        base = datetime(2026, 3, 1, 7, 0, 0)
        d1 = base.isoformat(timespec="seconds")
        d2 = (base + timedelta(hours=2)).isoformat(timespec="seconds")
        d3 = (base + timedelta(days=1)).isoformat(timespec="seconds")

        db.fitness_add_session(user_id=self.user_id, workout_id=self.workout_id, done_at=d1, rpe=7, comment=None)
        db.fitness_add_session(user_id=self.user_id, workout_id=self.workout_id, done_at=d2, rpe=8, comment=None)
        db.fitness_add_session(user_id=self.user_id, workout_id=self.workout_id, done_at=d3, rpe=6, comment=None)

        start = base.replace(hour=0, minute=0, second=0).isoformat(timespec="seconds")
        end = (base.replace(hour=0, minute=0, second=0) + timedelta(days=1)).isoformat(timespec="seconds")
        count = db.fitness_done_count_between(user_id=self.user_id, start_iso=start, end_iso=end)
        self.assertEqual(count, 2)

    def test_daily_checkin_count_between(self):
        now = datetime(2026, 3, 1, 9, 0, 0)
        for day_shift in (0, 1, 3):
            check_date = (now + timedelta(days=day_shift)).date().isoformat()
            stamp = (now + timedelta(days=day_shift)).isoformat(timespec="seconds")
            db.daily_checkin_upsert(
                user_id=self.user_id,
                check_date=check_date,
                done_text="ok",
                carry_text="",
                energy=7,
                created_at=stamp,
                updated_at=stamp,
            )
        start = now.date().isoformat()
        end = (now + timedelta(days=3)).date().isoformat()
        count = db.daily_checkin_count_between(
            user_id=self.user_id,
            start_date_iso=start,
            end_date_iso=end,
        )
        self.assertEqual(count, 2)

    def test_focus_and_reflection_stats(self):
        base = datetime(2026, 3, 1, 8, 0, 0)
        f1 = db.focus_session_start(
            user_id=self.user_id,
            duration_min=25,
            started_at=base.isoformat(timespec="seconds"),
        )
        db.focus_session_finish(
            user_id=self.user_id,
            focus_id=f1,
            finished_at=(base + timedelta(minutes=25)).isoformat(timespec="seconds"),
            status="done",
        )
        db.reflection_upsert(
            user_id=self.user_id,
            reflection_date=base.date().isoformat(),
            done_text="x",
            drain_text="y",
            remove_text="z",
            tomorrow_rule="rule",
            created_at=base.isoformat(timespec="seconds"),
            updated_at=base.isoformat(timespec="seconds"),
        )

        minutes, sessions = db.focus_stats_recent(
            user_id=self.user_id,
            since_iso=(base - timedelta(days=1)).isoformat(timespec="seconds"),
        )
        refl_count = db.reflection_count_between(
            user_id=self.user_id,
            start_date_iso=(base - timedelta(days=1)).date().isoformat(),
            end_date_iso=(base + timedelta(days=1)).date().isoformat(),
        )
        self.assertEqual(minutes, 25)
        self.assertEqual(sessions, 1)
        self.assertEqual(refl_count, 1)


if __name__ == "__main__":
    unittest.main()
