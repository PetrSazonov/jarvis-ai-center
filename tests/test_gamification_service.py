import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

import db
from services.gamification_service import (
    build_arena_text,
    build_boss_battle_status,
    build_cinematic_weekly_recap,
    mark_rescue_completed,
    rescue_completed_today,
    rescue_needed_today,
)


class GamificationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_name = db.DATABASE_NAME
        fd, path = tempfile.mkstemp(prefix="game_", suffix=".db")
        os.close(fd)
        self._tmp_path = path
        db.DATABASE_NAME = self._tmp_path
        db.init_db()
        self.user_id = 77
        self.now = datetime.now().replace(microsecond=0)

        workout_id = db.fitness_create_workout(
            title="Test workout",
            tags="test",
            equipment="none",
            difficulty=2,
            duration_sec=1200,
            notes="",
            vault_chat_id=1,
            vault_message_id=1001,
            file_id="",
            created_at=self.now.isoformat(timespec="seconds"),
        )
        self.workout_id = int(workout_id)

    def tearDown(self) -> None:
        db.DATABASE_NAME = self._orig_db_name
        try:
            os.remove(self._tmp_path)
        except OSError:
            pass

    def _add_done_task(self, when: datetime, text: str) -> None:
        todo_id = db.todo_add(
            user_id=self.user_id,
            text=text,
            created_at=when.isoformat(timespec="seconds"),
        )
        db.todo_mark_done(
            user_id=self.user_id,
            todo_id=int(todo_id),
            done_at=when.isoformat(timespec="seconds"),
        )

    def test_boss_battle_status_uses_week_metrics(self):
        self._add_done_task(self.now - timedelta(days=1), "Task A")
        self._add_done_task(self.now, "Task B")
        db.fitness_add_session(
            user_id=self.user_id,
            workout_id=self.workout_id,
            done_at=self.now.isoformat(timespec="seconds"),
            rpe=7,
            comment=None,
        )

        status = build_boss_battle_status(user_id=self.user_id, today=self.now.date())
        self.assertGreaterEqual(status.damage_pct, 1)
        self.assertIn(status.rank_title, {"Operator I", "Strategist II", "Commander III"})
        self.assertGreaterEqual(status.done_tasks, 2)
        self.assertGreaterEqual(status.workouts_done, 1)

    def test_daily_arena_text_contains_comparison(self):
        yesterday = self.now - timedelta(days=1)
        self._add_done_task(yesterday, "yesterday task")
        self._add_done_task(self.now, "today task")
        self._add_done_task(self.now, "today task 2")
        db.daily_checkin_upsert(
            user_id=self.user_id,
            check_date=self.now.date().isoformat(),
            done_text="done",
            carry_text="",
            energy=8,
            created_at=self.now.isoformat(timespec="seconds"),
            updated_at=self.now.isoformat(timespec="seconds"),
        )
        db.daily_checkin_upsert(
            user_id=self.user_id,
            check_date=yesterday.date().isoformat(),
            done_text="done",
            carry_text="",
            energy=5,
            created_at=yesterday.isoformat(timespec="seconds"),
            updated_at=yesterday.isoformat(timespec="seconds"),
        )

        text = build_arena_text(user_id=self.user_id, today=self.now.date())
        self.assertIn("Daily Arena", text)
        self.assertIn("Сегодня:", text)
        self.assertIn("Вчера:", text)

    def test_rescue_flow(self):
        today = date.today()
        self.assertTrue(rescue_needed_today(user_id=self.user_id, today=today))
        self.assertFalse(rescue_completed_today(user_id=self.user_id, today=today))

        mark_rescue_completed(user_id=self.user_id, now=self.now)
        self.assertTrue(rescue_completed_today(user_id=self.user_id, today=today))
        self.assertFalse(rescue_needed_today(user_id=self.user_id, today=today))

    def test_cinematic_recap_shape(self):
        text = build_cinematic_weekly_recap(user_id=self.user_id, today=self.now.date())
        self.assertIn("Cinematic Weekly Recap", text)
        self.assertIn("Следующая миссия", text)


if __name__ == "__main__":
    unittest.main()

